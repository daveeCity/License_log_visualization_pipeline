
# License Log Archival and Visualization Pipeline

- This project automates the **extraction, transformation, and loading (ETL)** of license usage data from log files into **Elasticsearch** for visualization in Kibana.
  The system is built for modularity and resilience:
-	Logstash handles real-time monitoring and ingestion (Parsing → Elasticsearch).
-	Python script manages long-term archival and Redis-based buffering.

---

## Project Overview
This pipeline is designed to:
1.	Parse raw .log files directly from the environment (/path/to/license/logs/) via Logstash Grok filters.
2.	Archive parsed data into a structured SQLite database (licenses.db).
3.	Queue processed entries in Redis for fault tolerance and decoupled downstream analytics.
4.	Consume Redis events asynchronously for further processing or alerting.
5.	Visualize license activity and server health in Kibana dashboards.
   
---

## System Architecture
                 ┌────────────────────────────┐
                 │       License Server       │
                 │      (Log Source .log)     │
                 └────────────┬───────────────┘
                              │
                              ▼
                      ┌────────────────┐
                      │    Logstash    │   → Grok Parsing + Enrichment
                      └───────┬────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │    Elasticsearch  │  → Indexed Storage
                    └─────────┬─────────┘
                              │
                              ▼
                      ┌────────────────┐
                      │     Kibana     │  → Visualization
                      └────────────────┘


                  ┌──────────────────────────────┐
                  │         Python Archiver      │
                  │ (log_archiver.py)            │
                  │   - Regex Extraction         │
                  │   - SQLite Archival          │
                  │   - Redis Queue Feed         │
                  └────────────┬─────────────────┘
                               │
                     ┌─────────┴─────────┐
                     ▼                   ▼
           ┌─────────────────┐   ┌──────────────────┐
           │   SQLite (db/)  │   │   Redis Queue    │
           │  Permanent Store│   │ license_log_queue│
           └─────────────────┘   └──────────────────┘

              ┌────────────────────────┐
              │ Redis Consumer Service │
              │ (redis_consumer.py)    │
              │  - Polls queue         │
              │  - Custom processing   │
              └────────────────────────┘


---

## Project Structure

    License_log_visualization_pipeline/
    ├── config/
    │   ├── elasticsearch.yml
    │   ├── kibana.yml
    │   ├── logstash.yml
    │   ├── license_logs.conf
    │   ├── sample_log_archiver.service
    │   ├── sample_log_archiver.timer
    │   └── sample_redis_consumer.service
    │
    ├── scripts/
    │   ├── log_archiver.py        # Parses, archives, and queues logs
    │   └── redis_consumer.py      # Consumes queued logs from Redis
    │
    ├── sample_logs/
    │   └── sample_logs.log
    │
    ├── requirements.txt
    ├── requirements-dev.txt
    ├── LICENSE
    └── README.md

---

## Background Services
**Log archiver (systemd timer)**
Automates periodic archival of license logs into SQLite and Redis.
Config files 
- config/sample_log_archiver.service
- config/sample:log_archiver.timer
**Enable and start**
  sudo cp config/sample_log_archiver.* /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable --now sample_log_archiver.timer

**Check logs**
  journalctl -u sample_log_archiver.service -f

---

## Redis Consumer (service)
Consumes queued license data for downstream tasks (alerting, export, etc.)
- **Config file**
  - config/sample_redis_consumer.service
- **Enable and start**
  - sudo cp config/sample_redis_consumer.service /etc/systemd/system/
  - sudo systemctl daemon-reload
  - sudo systemctl enable --now sample_redis_consumer.service
- **Monitor**
  - sudo syestemctl status sample_redis_consumer.service
  - journalctl -u sample_redis_consumer.service -f

---

## Redis queue operations
|Command|Description|
|-----:|-------|
|redis-cli llen license_log_queue|Check pending messages|
|redis-cli flushall| Clear all queues|
|redis-cli| Stream live Redis traffic|

---


## Environment Setup

|Component|Version|	Purpose|
|-------:|----|--------------|
|Python|3.8+|Archiving, Redis buffering|
|Redis|6+	|Event queue / buffer|
|SQLite|Built-in|Local, permanent storage|
|Logstash|8.x|Parsing and ingestion|
|Elasticsearch|8.x|Data storage and indexing|
|Kibana|8.x|Visualization layer|

---

## Quick Start (Full Deployment)
1. Install and enable Redis, Logstash, Elasticsearch, Kibana
2. Configure .yml files under /etc/ or config/
3. Test Logstash pipelines (--config.test_and_exit)
4. Start Python Archiver manually or via systemd timer
5. Enable Redis consumer for real-time event processing
6. Access Kibana dashboards at http://locealhost:5601

### 1. Install Core Services

- sudo apt update && sudo apt install -y redis-server python3 python3-pip
- sudo systemctl enable --now redis-server
- sudo apt install -y elasticsearch kibana logstash
- sudo systemctl enable elasticsearch kibana logstash
  
---

### 2. Configure Elasticsearch

- /etc/elasticsearch/elasticsearch.yml
- network.host: 0.0.0.0
- http.port: 9200
- sudo systemctl restart elasticsearch
- curl -u elastic:<password> http://localhost:9200
---

### 3. Configure Kibana

- /etc/kibana/kibana.yml
- server.host: "0.0.0.0"
- elasticsearch.hosts: ["http://localhost:9200"]
- sudo systemctl restart kibana
- Access: http://localhost:5601
  
---

## 4. Logstash Configuration Language (LSCL) & Ruby integration

Logstash pipelines are written in LSCL (Logstash Configuration Language), a Ruby-based DSL that defines what transformations to perform on incoming log data. Each section (input, filter, output) uses modular plugins to handle specific tasks.

## Parsing and enrichment

The Dassault pipeline leverages built-in filters such as:

- grok: to extract structured fields from unstructured license logs
- mutate: to rename, add or remove fields
- date: to standardize timestamps
- fingerprint: to generate deterministic document IDs

## Ruby plugin

Logstash runs on Jruby, allowing the execution of custom Ruby logic when built-in plugins aren't sufficient.
A Ruby block can be embedded directly in the .conf file using the ruby filter to provide full scripting flexibility for dinamic conditions or field logic.
optionally, for even more complex use cases, custom Ruby plugins can be developed and packaged as .gem extensions.

Altough Ruby scripting is powerful, **Grok** is preferred for this pipeline due to its: 
- simplicity and readabilty
- native performance optimiazition
- built-in pattern library and community support

## Validate and restart:

- sudo -u logstash /usr/share/logstash/bin/logstash --config.test_and_exit -f /etc/logstash/conf.d/license_logs.conf
- sudo systemctl restart logstash
  
---

### 5. Python Archiver (log_archiver.py)

- **Role**:
  Handles archival and Redis queueing, decoupled from the live Logstash ingestion.
- **Run Manually**
  python3 /path/to/license/archiver/log_archiver.py
- **Force Reprocess**
  python3 /path/to/license/archiver/log_archiver.py --force
-**Redis Commands**
  redis-cli llen license_log_queue   # Check queue depth
  redis-cli flushall                 # Flush queue
  
---

### 6. Kibana Setup
1.	Open Stack Management → Data Views
2.	Create new Data View:
3.	license-grok-logs-*
4.	Time field: @timestamp
   
---

## Maintenance Commands

|Task|Command|
|---------------:|-----------------|
|Check services|systemctl status logstash elasticsearch redis-server|
|Reset parser cache|rm ~/path/to/json/parsed_files.json|
|Flush Redis queue|redis-cli flushall|
|Inspect database| sqlite3 db/licenses.db "SELECT COUNT (*) FROM licenses;"

---

## Versioning
|Component|Version|
|---------------:|-----------------|
|Parser Schema|1.1|
|Logstash Config|1.0|
|Python Archiver|2025-10-27|
|Redis consumer|2025-11-04|

---

## //TODO
- Maintenance Automation (es_maintenance.sh):
  - Clean up system & journal logs
  - automatically delete logs older than 60 days
  - reset "read_only_allow_delete" flag when disk is full

- Python ingestion automation
  - Schedule periodic ingestion of DSLS logs via python script
  - Sync parsed data to SQLite db for long term archiving
  - Buffer pending logs with Redis during index or network downtime
  - Integrate status feedback into Logstash/Kibana dashboard
