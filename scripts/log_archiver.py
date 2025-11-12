#!/usr/bin/env python3
"""
Log Archiver & Redis Buffer Script (log_archiver.py)

- ARCHIVE: Inserts parsed logs into SQLite DB (deduplicated by raw_hash).
- BUFFER: Enqueues parsed events to Redis for optional downstream consumption.
- TRACKING: Uses parsed tracker to process files only once.
"""

import re
import sqlite3
import json
import os
import logging
import argparse
import hashlib
from datetime import datetime

try:
    import redis
except ImportError:
    redis = None

# === Paths ===
LOG_DIRECTORY = "/path/to/license/logs/"
DB_PATH = os.path.expanduser("~/data/.db")
PARSED_TRACKER = os.path.expanduser("~/data/parsed_files.json")
SCHEMA_VERSION = "1.0"

# Redis connection settings
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))
REDIS_QUEUE_NAME = os.getenv("REDIS_QUEUE", "license_log_queue")

# === Logging config ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# === Database setup ===
def connect_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            schema_version TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            log_level TEXT,
            component TEXT,
            action TEXT,
            license_type TEXT,
            user_name TEXT,
            client_ip TEXT,
            raw_message TEXT,
            raw_hash TEXT UNIQUE
        )
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp)")

    cur.execute("SELECT COUNT(*) FROM meta")
    if cur.fetchone()[0] == 0:
        cur.execute("INSERT INTO meta (schema_version) VALUES (?)", (SCHEMA_VERSION,))
        conn.commit()

    return conn


# === Helpers ===
def sha1_hex(s):
    h = hashlib.sha1()
    h.update(s.encode("utf-8", errors="ignore"))
    return h.hexdigest()


# === Parsing logic ===
# Adjust pattern to match your log vendor signature (e.g., "!<type>!Vendor")

LOG_PATTERN = re.compile(
    r"^(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}:\d{3})\s+([A-Z])\s+([A-Z_]+)\s+(.*?)(Grant|Detachment|TimeOut|not granted)",
    re.IGNORECASE
)

def parse_log_line(line):
    m = LOG_PATTERN.search(line)
    if not m:
        return None

    timestamp_raw, level_letter, component, pre_message, action = m.groups()
    timestamp = timestamp_raw

    license_type_match = re.search(r"!(\w+)!Vendor", line)
    if not license_type_match:
        mlt = re.search(r"!(\w+)!([^!\s]+)\s", line)
        license_type = mlt.group(1) if mlt else "Unknown"
    else:
        license_type = license_type_match.group(1)

    user_match = re.search(r"\|?([A-Za-z0-9_.-]+)@[\w.-]+", line)
    if not user_match:
        user_match = re.search(r"\|([A-Za-z0-9_.-]+)\|", line)
    user_name = user_match.group(1) if user_match else "Unknown"

    ip_match = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", line)
    client_ip = ip_match.group(1) if ip_match else "Unknown"

    raw_message = line.rstrip("\n")

    return {
        "timestamp": timestamp,
        "log_level": level_letter,
        "component": component,
        "action": action,
        "license_type": license_type,
        "user_name": user_name,
        "client_ip": client_ip,
        "raw_message": raw_message
    }


# === Process individual log files ===
def process_log_file(file_path, conn, redis_conn=None):
    cur = conn.cursor()
    parsed = []
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if not line.strip():
                    continue
                entry = parse_log_line(line)
                if entry:
                    # compute hash for dedupe
                    entry["raw_hash"] = sha1_hex(entry["raw_message"])
                    parsed.append(entry)

        if not parsed:
            logging.warning(f"No valid entries found in {os.path.basename(file_path)}")
            return 0

        # 1. ARCHIVE TO SQLITE DB
        to_insert = [
            (
                e["timestamp"],
                e["log_level"],
                e["component"],
                e["action"],
                e["license_type"],
                e["user_name"],
                e["client_ip"],
                e["raw_message"],
                e["raw_hash"]
            ) for e in parsed
        ]

        # Use INSERT OR IGNORE to handle 'raw_hash UNIQUE' constraint
        cur.executemany("""
            INSERT OR IGNORE INTO logs
            (timestamp, log_level, component, action, license_type, user_name, client_ip, raw_message, raw_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, to_insert)
        conn.commit()
        logging.info(f"Archived {len(parsed)} entries to SQLite from {os.path.basename(file_path)}")


        # 2. PUSH TO REDIS
        if redis_conn:
            pushed_count = 0
            for e in parsed:
                try:
                    redis_conn.rpush(REDIS_QUEUE_NAME, json.dumps(e, ensure_ascii=False))
                    pushed_count += 1
                except Exception as ex:
                    logging.debug(f"Redis push failed (continuing): {ex}")
            logging.info(f"Pushed {pushed_count} entries to Redis queue '{REDIS_QUEUE_NAME}'")


        logging.info(f"Parsed {len(parsed)} entries from {os.path.basename(file_path)} (insert attempted; duplicates ignored)")
        return len(parsed)

    except Exception as exc:
        logging.error(f"Error processing {file_path}: {exc}")
        return 0


# === Tracking mechanism ===
def load_parsed_files():
    if not os.path.exists(PARSED_TRACKER):
        return []
    try:
        with open(PARSED_TRACKER, "r", encoding="utf-8") as f:
            return json.load(f) or []
    except Exception:
        logging.warning("Parsed tracker corrupted or unreadable, starting fresh.")
        return []


def save_parsed_files(parsed_files):
    os.makedirs(os.path.dirname(PARSED_TRACKER), exist_ok=True)
    with open(PARSED_TRACKER, "w", encoding="utf-8") as f:
        json.dump(parsed_files, f, indent=2)


# === Redis helper ===
def get_redis_connection():
    if redis is None:
        logging.debug("redis python package not installed; skipping Redis enqueue.")
        return None
    try:
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, socket_connect_timeout=2)
        r.ping()
        logging.info(f"Connected to Redis {REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}")
        return r
    except Exception as e:
        logging.debug(f"Redis not available: {e}")
        return None


# === Main ===
def main():
    parser = argparse.ArgumentParser(description="Parse license logs to sqlite + optionally enqueue to Redis")
    parser.add_argument("--force", action="store_true", help="Force reprocess all logs (clears parsed tracker)")
    args = parser.parse_args()

    conn = connect_db()
    parsed_files = [] if args.force else load_parsed_files()

    if args.force:
                logging.info("Forcing reprocess: JSON output is no longer generated.")

    total_parsed = 0

    if not os.path.exists(LOG_DIRECTORY):
        logging.error(f"Log directory not found: {LOG_DIRECTORY}")
        return

    redis_conn = get_redis_connection()

    all_logs = sorted([f for f in os.listdir(LOG_DIRECTORY) if f.endswith(".log")])

    for log_file in all_logs:
        full_path = os.path.join(LOG_DIRECTORY, log_file)
        if log_file in parsed_files and not args.force:
            continue
        parsed_count = process_log_file(full_path, conn, redis_conn=redis_conn)
        if parsed_count > 0:
            parsed_files.append(log_file)
            total_parsed += parsed_count

    save_parsed_files(parsed_files)
    conn.close()

    logging.info(f"Log archival complete: {total_parsed} entries saved to DB and/or Redis.")


if __name__ == "__main__":
    main()
