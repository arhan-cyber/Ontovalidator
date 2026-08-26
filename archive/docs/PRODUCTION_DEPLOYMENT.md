# Production Deployment Guide

Complete deployment and operational guide for the SVO Verification Pipeline in production environments.

## Table of Contents

1. [Pre-Deployment Checklist](#1-pre-deployment-checklist)
2. [Environment Setup](#2-environment-setup)
3. [Running Health Checks](#3-running-health-checks)
4. [Starting the Pipeline](#4-starting-the-pipeline)
5. [Monitoring & Fallback Behavior](#5-monitoring--fallback-behavior)
6. [Docker Deployment](#6-docker-deployment)
7. [Troubleshooting](#7-troubleshooting)
8. [Production Best Practices](#8-production-best-practices)

---

## 1. Pre-Deployment Checklist

Before deploying to production, ensure the following are in place:

- [ ] All 3 production backends (Elasticsearch, Neo4j, Milvus) are running and accessible
- [ ] Environment variables are properly configured (see Section 2)
- [ ] Health checks pass successfully (see Section 3)
- [ ] Firewall rules allow inbound connections to backend ports:
  - Elasticsearch: 9200 (HTTP), 9300 (node communication)
  - Neo4j: 7687 (Bolt)
  - Milvus: 19530 (gRPC)
  - SQLite: local filesystem access
- [ ] SQLite database directory exists and is writable
- [ ] Sufficient disk space for data storage:
  - SQLite: varies by document volume
  - Elasticsearch: ~10-20% of raw data size
  - Neo4j: ~20-30% of raw data size
  - Milvus: ~10% of raw data size (for embeddings)
- [ ] Backup procedures are documented and tested
- [ ] Logging and monitoring are configured

---

## 2. Environment Setup

### 2.1 Copy Configuration Template

If an `.env` file doesn't exist, create one from the example:

```bash
cp .env.example .env
```

### 2.2 Configure Backend Credentials

Edit `.env` with your backend connection details:

```env
# Elasticsearch
ELASTICSEARCH_ENABLED=true
ELASTICSEARCH_HOSTS=http://localhost:9200
ELASTICSEARCH_USERNAME=elastic
ELASTICSEARCH_PASSWORD=your_password_here
ELASTICSEARCH_TIMEOUT=5
ELASTICSEARCH_RETRY_ATTEMPTS=3

# Neo4j
NEO4J_ENABLED=true
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password_here
NEO4J_TIMEOUT=5
NEO4J_RETRY_ATTEMPTS=3

# Milvus
MILVUS_ENABLED=true
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_TIMEOUT=5
MILVUS_RETRY_ATTEMPTS=3

# Pipeline Configuration
USE_PRODUCTION_BACKENDS=true
REQUIRE_PRODUCTION_BACKENDS=false
SQLITE_DB_PATH=data/svo_data.db

# Logging
LOG_LEVEL=INFO
```

### 2.3 Validate Configuration

Load and validate the configuration:

```bash
python -c "from src.config import load_config_from_env; cfg = load_config_from_env(); print('Config loaded successfully'); print(f'Production mode: {cfg.use_production_backends}')"
```

---

## 3. Running Health Checks

### 3.1 Quick Health Check (All Backends)

Run a complete health check of all backends:

```bash
python scripts/health_check.py --all
```

**Expected Output:**
```
================================================================================
BACKEND HEALTH CHECK REPORT
================================================================================

Report Time: 2024-07-10 10:30:45 UTC
Overall Status: HEALTHY

--------------------------------------------------------------------------------
Backend Status:
--------------------------------------------------------------------------------
elasticsearch    HEALTHY         latency: 45.23ms
neo4j            HEALTHY         latency: 32.15ms
milvus           HEALTHY         latency: 28.47ms
sqlite           HEALTHY         latency: 2.34ms

--------------------------------------------------------------------------------
Recommendations:
--------------------------------------------------------------------------------
1. All enabled backends are operational.

--------------------------------------------------------------------------------
Fallback Chain Summary:
--------------------------------------------------------------------------------
Query Chain: elasticsearch -> neo4j -> milvus -> SQLite

================================================================================
```

### 3.2 Check Specific Backend

```bash
# Check only Elasticsearch
python scripts/health_check.py --elasticsearch

# Check only Neo4j
python scripts/health_check.py --neo4j

# Check only Milvus
python scripts/health_check.py --milvus

# Check only SQLite
python scripts/health_check.py --sqlite
```

### 3.3 Export Health Report

Export results to JSON or Markdown for archival:

```bash
# Export to JSON
python scripts/health_check.py --all --export-json health_report.json

# Export to Markdown
python scripts/health_check.py --all --export-markdown health_report.md
```

### 3.4 Interpret Health Check Results

- **Overall Status: HEALTHY** - All backends operational, full functionality available
- **Overall Status: DEGRADED** - Some backends unavailable, but SQLite fallback available
- **Overall Status: FAILED** - Critical failure; SQLite also unavailable

Exit codes:
- `0` - HEALTHY (all systems operational)
- `1` - DEGRADED (fallback available)
- `2` - FAILED (cannot proceed)

### 3.5 Troubleshoot Failed Checks

If a backend health check fails:

1. **Check connectivity**: Verify network/firewall access to the backend
2. **Check credentials**: Verify username/password in `.env`
3. **Check service status**: Verify the backend service is running
4. **Check logs**: Review backend service logs for errors
5. **Retry with timeout override**:
   ```bash
   python scripts/health_check.py --all --timeout 10  # 10 second timeout
   ```
6. **Disable the backend** (temporary):
   ```env
   # In .env, set to false to disable a backend
   ELASTICSEARCH_ENABLED=false
   ```

---

## 4. Starting the Pipeline

### 4.1 Python API Usage

Create a verification engine and start processing:

```python
from src.config import load_config_from_env
from src.engine import SVOVerificationEngine
from src.routing import MoERouter
from src.retrieval import (
    SQLiteLexicalRetriever,
    SQLiteSemanticRetriever,
    SQLiteGraphRetriever,
)
from src.fusion import WeightedFusionEngine
from src.storage import SQLiteChunkStore
from src.validation import MinimalValidator
from src.integration import HealthCheckRunner, print_health_report

# Load configuration and run health checks
config = load_config_from_env()
health_report = HealthCheckRunner.check_all(config)
print_health_report(health_report)

# Only proceed if system is healthy
if health_report.overall_status == "FAILED":
    print("ERROR: System is not ready for production")
    exit(1)

# Create engine with appropriate backends
engine = SVOVerificationEngine(
    router=MoERouter(),
    lexical_store=SQLiteLexicalRetriever(config.sqlite_db_path),
    semantic_store=SQLiteSemanticRetriever(config.sqlite_db_path),
    graph_store=SQLiteGraphRetriever(config.sqlite_db_path),
    fusion_engine=WeightedFusionEngine(),
    chunk_store=SQLiteChunkStore(config.sqlite_db_path),
    validator=MinimalValidator(),
)

# Process documents
result = engine.validate_triples_batch(
    document_id="doc_001",
    raw_text="Your document text here...",
    triples=[
        # OntologyAssertion objects
    ],
    top_k=5,
)

print(f"Verification complete: {result}")
```

### 4.2 CLI Usage (Triple Validation)

Validate triples from the command line:

```bash
python scripts/validate_triples.py \
  --db-path data/svo_data.db \
  --document-id doc_001 \
  --text "Apple Inc. is a technology company headquartered in California." \
  --triple "Apple Inc.|is_a|company" \
  --triple "Apple Inc.|location|California"
```

### 4.3 Production HTTP Server (Optional)

To deploy as an HTTP service, wrap the engine in a web framework:

```python
# Example using Flask
from flask import Flask, request, jsonify
from src.config import load_config_from_env
from src.engine import SVOVerificationEngine
from src.integration import HealthCheckRunner, print_health_report

app = Flask(__name__)
config = load_config_from_env()
engine = create_engine(config)  # Your engine creation function

@app.route("/health", methods=["GET"])
def health():
    report = HealthCheckRunner.check_all(config)
    return jsonify(report.to_dict()), 200 if report.overall_status == "HEALTHY" else 503

@app.route("/verify", methods=["POST"])
def verify():
    data = request.json
    result = engine.validate_triples_batch(**data)
    return jsonify(result), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
```

---

## 5. Monitoring & Fallback Behavior

### 5.1 Backend Status During Execution

When the pipeline runs, it automatically handles backend failures:

1. **Preferred retrieval path**: Uses all available backends (Elasticsearch, Neo4j, Milvus)
2. **Partial failure**: If some backends are down, uses available ones
3. **Full fallback**: If all production backends are unavailable, SQLite is used
4. **Graceful degradation**: Results quality decreases but processing continues

### 5.2 Execution Logs

Monitor logs to track backend usage:

```bash
# Run with verbose logging
python scripts/validate_triples.py ... 2>&1 | grep -i backend

# Look for fallback messages:
# "Elasticsearch unreachable, using fallback"
# "Neo4j unavailable, skipping graph retrieval"
# "SQLite fallback: retrieving from local database"
```

### 5.3 Periodic Health Monitoring

#### Setup Cron Job (Linux/macOS)

Edit crontab to run health checks periodically:

```bash
crontab -e
```

Add a line to run health checks every hour and log results:

```cron
0 * * * * /usr/bin/python3 /path/to/scripts/health_check.py --all --export-json /var/log/health_reports/$(date +\%Y\%m\%d_\%H\%M\%S).json
```

#### Setup Systemd Timer (Linux)

Create `/etc/systemd/system/health-check.service`:

```ini
[Unit]
Description=SVO Pipeline Health Check
After=network-online.target

[Service]
Type=oneshot
User=pipeline
WorkingDirectory=/path/to/Ontovalidator
ExecStart=/usr/bin/python3 scripts/health_check.py --all --export-json /var/log/health_reports/%H_%M_%S.json
Environment="PATH=/usr/local/bin:/usr/bin"
```

Create `/etc/systemd/system/health-check.timer`:

```ini
[Unit]
Description=Run health checks every hour
Requires=health-check.service

[Timer]
OnBootSec=5min
OnUnitActiveSec=1h
AccuracySec=1min

[Install]
WantedBy=timers.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable health-check.timer
sudo systemctl start health-check.timer
```

### 5.4 Alerting on Backend Failures

Parse exported JSON reports to create alerts:

```python
import json
from datetime import datetime

def check_health_status(json_file):
    with open(json_file) as f:
        report = json.load(f)
    
    if report["overall_status"] == "FAILED":
        # Send alert (email, Slack, PagerDuty, etc.)
        send_alert(f"Pipeline health check FAILED at {report['timestamp']}")
        return False
    return True
```

---

## 6. Docker Deployment

### 6.1 Docker Compose Setup

Use the provided `docker-compose.yml` to start all backends:

```bash
docker-compose up -d
```

This starts:
- Elasticsearch 8.x on port 9200
- Neo4j 5.x on port 7687
- Milvus 2.x on port 19530

### 6.2 Verify Services are Running

```bash
# Check container status
docker-compose ps

# Expected output:
# NAME                 STATUS              PORTS
# elasticsearch        Up 2 minutes        0.0.0.0:9200->9200/tcp
# neo4j                Up 2 minutes        0.0.0.0:7687->7687/tcp
# milvus               Up 2 minutes        0.0.0.0:19530->19530/tcp
```

### 6.3 Wait for Services to be Ready

Services take time to initialize. Wait for all to be ready:

```bash
# Elasticsearch health check
until curl -s http://localhost:9200/_cluster/health | grep -q "green\|yellow"; do
  echo "Waiting for Elasticsearch..."
  sleep 2
done

# Neo4j health check
until curl -s http://localhost:7687 2>/dev/null; do
  echo "Waiting for Neo4j..."
  sleep 2
done

# Milvus health check (basic connectivity)
until python scripts/health_check.py --milvus 2>/dev/null | grep -q "HEALTHY"; do
  echo "Waiting for Milvus..."
  sleep 2
done

echo "All services ready!"
```

### 6.4 Override Environment in Docker

Set environment variables in `docker-compose.yml`:

```yaml
services:
  pipeline:
    build: .
    environment:
      - ELASTICSEARCH_ENABLED=true
      - ELASTICSEARCH_HOSTS=http://elasticsearch:9200
      - NEO4J_URI=bolt://neo4j:7687
      - NEO4J_PASSWORD=your_password
      - MILVUS_HOST=milvus
      - USE_PRODUCTION_BACKENDS=true
      - LOG_LEVEL=INFO
    depends_on:
      - elasticsearch
      - neo4j
      - milvus
```

### 6.5 Volume Mounts for Data Persistence

Configure volumes in `docker-compose.yml`:

```yaml
services:
  elasticsearch:
    volumes:
      - es_data:/usr/share/elasticsearch/data
  
  neo4j:
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
  
  milvus:
    volumes:
      - milvus_data:/var/lib/milvus

volumes:
  es_data:
  neo4j_data:
  neo4j_logs:
  milvus_data:
```

---

## 7. Troubleshooting

### 7.1 Common Connection Errors

#### "Connection refused" (port not open)

```
ERROR: Elasticsearch unavailable: [Errno 111] Connection refused
```

**Solution:**
1. Verify backend is running: `docker-compose ps`
2. Verify firewall allows traffic: `telnet localhost 9200`
3. Check backend logs: `docker-compose logs elasticsearch`

#### "Authentication failed"

```
ERROR: Elasticsearch unavailable: Failed to authenticate
```

**Solution:**
1. Verify credentials in `.env`
2. Check backend password settings
3. Try default credentials (for development):
   - Elasticsearch: elastic / changeme
   - Neo4j: neo4j / password
   - Milvus: no auth by default

#### "Timeout"

```
ERROR: Elasticsearch unavailable: Connection timeout after 5 seconds
```

**Solution:**
1. Increase timeout: `--timeout 30`
2. Check backend performance: `docker-compose stats`
3. Check network latency: `ping <backend_host>`

### 7.2 Port Conflicts

If ports are already in use:

```bash
# Find process using port 9200
lsof -i :9200

# Kill the process (if safe)
kill -9 <PID>

# Or change Docker port mapping
docker-compose.yml:
  elasticsearch:
    ports:
      - "9201:9200"  # external:internal
```

### 7.3 Database Initialization

#### SQLite Database Not Found

```
ERROR: SQLite unavailable at data/pipeline.db: No such file or directory
```

**Solution:**
```bash
# Create data directory
mkdir -p data

# Create empty database
python -c "import sqlite3; sqlite3.connect('data/pipeline.db')"
```

#### Neo4j Database Reset

```bash
# Stop Neo4j container
docker-compose stop neo4j

# Remove data volume
docker volume rm ontovalidator_neo4j_data

# Restart
docker-compose up -d neo4j
```

### 7.4 Inspect Service Logs

```bash
# View Elasticsearch logs
docker-compose logs -f elasticsearch

# View Neo4j logs
docker-compose logs -f neo4j

# View Milvus logs
docker-compose logs -f milvus

# All logs
docker-compose logs -f
```

### 7.5 Recovery Procedures

#### Temporary Backend Disable

If a backend is failing and affects operations, temporarily disable it:

```env
# In .env
ELASTICSEARCH_ENABLED=false
```

Restart pipeline and run health check:

```bash
python scripts/health_check.py --all
```

#### Clear All Data (Development Only)

```bash
# WARNING: This deletes all data
docker-compose down -v
docker-compose up -d
```

#### Restore from Backup

For production, implement backup/restore procedures for each backend.

---

## 8. Production Best Practices

### 8.1 Monitoring Backend Health

Implement continuous health monitoring:

1. **Run health checks hourly** (see Section 5.3)
2. **Monitor backend performance metrics**:
   - Query latency
   - Index size
   - Memory usage
   - Connection count
3. **Set up alerting** for:
   - Any backend becoming FAILED
   - Latency > 1000ms
   - Disk usage > 90%

### 8.2 Database Backups

Implement automated backups for each backend:

#### Elasticsearch Snapshots

```bash
# Create snapshot repository
curl -X PUT "localhost:9200/_snapshot/backup" -H 'Content-Type: application/json' -d '{
  "type": "fs",
  "settings": {
    "location": "/mnt/backups/elasticsearch"
  }
}'

# Create daily snapshot
# (Run via cron)
curl -X PUT "localhost:9200/_snapshot/backup/daily-$(date +%Y%m%d)" -H 'Content-Type: application/json' -d '{
  "indices": "*",
  "ignore_unavailable": true,
  "include_global_state": false
}'
```

#### Neo4j Backup

```bash
# Using neo4j-admin
docker exec neo4j_container neo4j-admin backup --backup-dir=/backups --database=neo4j
```

#### SQLite Backup

```bash
# Simple file copy
cp data/svo_data.db /mnt/backups/svo_data.db.$(date +%Y%m%d_%H%M%S)
```

### 8.3 Log Rotation

Configure log rotation to manage disk space:

```bash
# Create /etc/logrotate.d/pipeline
/var/log/svo-pipeline/*.log {
  daily
  missingok
  rotate 30
  compress
  delaycompress
  notifempty
  create 0640 pipeline pipeline
  sharedscripts
  postrotate
    systemctl reload pipeline || true
  endscript
}
```

### 8.4 Version Pinning

Lock dependency versions for reproducible deployments:

```bash
# Generate requirements.txt with exact versions
pip freeze > requirements.txt

# Install exact versions
pip install -r requirements.txt
```

### 8.5 Security Considerations

1. **Credentials Management**:
   - Store `.env` securely (not in git)
   - Use environment variables for all secrets
   - Rotate passwords regularly

2. **Network Security**:
   - Use VPN or private networks for backend access
   - Enable TLS/SSL for network traffic
   - Use API keys instead of passwords where possible

3. **Access Control**:
   - Run services as non-root user
   - Restrict file permissions on SQLite database
   - Implement role-based access for backends

4. **Audit Logging**:
   - Enable backend audit logs
   - Monitor access to verification results
   - Track configuration changes

### 8.6 Performance Tuning

#### Elasticsearch Tuning

```bash
# Increase bulk indexing speed
curl -X PUT "localhost:9200/my-index-000001/_settings" -H 'Content-Type: application/json' -d '{
  "index": {
    "number_of_replicas": 0,
    "refresh_interval": "30s"
  }
}'
```

#### Neo4j Tuning

```ini
# In neo4j.conf
dbms.memory.heap.initial_size=2G
dbms.memory.heap.max_size=4G
dbms.memory.pagecache.size=2G
```

#### Milvus Tuning

```yaml
# In milvus.yaml
cache:
  enabled: true
  cache_size: 4GB
```

### 8.7 Capacity Planning

Monitor growth and plan for scaling:

1. **Track metrics over time**:
   - Number of documents indexed
   - Database size per backend
   - Query latency trends

2. **Plan for growth**:
   - Add more Elasticsearch nodes
   - Shard Neo4j databases
   - Scale Milvus cluster

3. **Testing**:
   - Load testing with production data volume
   - Failover testing
   - Disaster recovery drills

---

## Support & Resources

- **README**: See [README.md](../README.md) for architecture overview
- **QUICKSTART**: See [QUICKSTART.md](./QUICKSTART.md) for development setup
- **Health Check CLI**: `python scripts/health_check.py --help`
- **Configuration**: See [src/config.py](../src/config.py) for all options

## Changelog

- **v1.0.0** (2024-07-10): Initial production deployment guide
