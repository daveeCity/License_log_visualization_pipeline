#!/usr/bin/env python3
"""
Redis Consumer - License Log Pipeline
Consumes parsed log events from Redis and processes or forwards them.

This script is vendor-agnostic and works with any structured log producer pushing JSON to Redis.
"""

import json
import redis
import time
import logging

# === Config ===
REDIS_HOST = "127.0.0.1"
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_QUEUE_NAME = "license_log_queue"

# === Logging ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

def process_event(event):
    """
    Define what to do with the event.
    You can forward to an API, Elasticsearch, or print/log it.
    """
    logging.info(f"Processing: {event['license_type']} | {event['user_name']} | {event['action']}")

def main():
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)
    logging.info(f"Connected to Redis at {REDIS_HOST}:{REDIS_PORT}, listening on '{REDIS_QUEUE_NAME}'")

    while True:
        try:
            _, data = r.blpop(REDIS_QUEUE_NAME, timeout=5)
            if data:
                event = json.loads(data)
                process_event(event)
            else:
                time.sleep(1)
        except KeyboardInterrupt:
            logging.info("Shutting down consumer...")
            break
        except Exception as e:
            logging.error(f"Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
