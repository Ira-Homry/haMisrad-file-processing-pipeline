# File Processing Pipeline

A robust file processing pipeline built with Python, FastAPI, Redis and PostgreSQL.
Upload files, process them through configurable pipeline steps, and retrieve results.

---

## Architecture

```
User → FastAPI (Upload/Status API) → Redis (Queue) → Workers → Storage
                                           ↕
                                       PostgreSQL (Job Tracking)
```

**Components:**
- **FastAPI** → Upload API + Status API (port 8000)
- **Workers** → Execute pipeline steps (scalable)
- **Redis** → Job queue
- **PostgreSQL** → Job and step tracking
- **pgAdmin** → PostgreSQL UI (port 9090)
- **RedisInsight** → Redis queue UI (port 5540)

---

## How to Run the Project

### Prerequisites
- Docker
- Docker Compose

### Start the project

```bash
# Single worker
docker compose -f docker-compose.ha_misrad.yml up

# Multiple workers (parallel processing)
docker compose -f docker-compose.ha_misrad.yml up --scale worker=2
```

### Access the services
- **Swagger UI** → http://localhost:8000/docs
- **pgAdmin** → http://localhost:9090 (email: admin@pipeline.com, password: admin1234!)
- **RedisInsight** → http://localhost:5540

---

## How to Run Tests

### Unit tests (no containers required)
```bash
docker exec -it pipeline-api pytest /app/tests/unit/ -v
```

### Integration tests (containers must be running)
```bash
docker exec -it pipeline-api pytest /app/tests/integration/ -v
```

### Run all tests
```bash
docker exec -it pipeline-api pytest /app/tests/ -v
```

---

## Example API Calls

You can use either the **Swagger UI** in your browser or **curl** commands in the terminal.

### 1. Upload a file and start a pipeline

**Via Swagger UI:**
- Open http://localhost:8000/docs
- Click `POST /upload` → Try it out
- Select a file and paste the pipeline definition
- Click Execute

**Via curl:**
```bash
curl -X POST http://localhost:8000/upload \
  -F "file=@test_data/sample.csv" \
  -F 'pipeline=[{"step": "validate", "params": {"expected_type": "csv"}}, {"step": "transform", "params": {"select_columns": ["name", "email"], "apply": {"column": "name", "operation": "uppercase"}}}, {"step": "convert", "params": {"output_format": "json"}}, {"step": "compress", "params": {"algorithm": "gzip"}}]'
```

### 2. Check job status

**Via Swagger UI:**
- Click `GET /jobs/{job_id}` → Try it out → paste job_id → Execute

**Via curl:**
```bash
curl http://localhost:8000/jobs/{job_id}
```

**Response includes:**
- `status` → PENDING, PROCESSING, COMPLETED, FAILED
- `progress` → 0-100 percentage
- `estimated_seconds` → estimated processing time
- `current_step_index` → which step is running
- `error` → error message if failed

### 3. Download result file

**Via Swagger UI:**
- Click `GET /jobs/{job_id}/result` → Try it out → paste job_id → Execute → Download

**Via curl (recommended for binary files like .gz):**
```bash
curl -o result.json.gz http://localhost:8000/jobs/{job_id}/result
```

> **Note:** Swagger UI may not preserve the correct file extension for compressed files.
> Use curl to download with the correct extension.

### 4. Retry a failed job

**Via Swagger UI:**
- Click `POST /jobs/{job_id}/retry` → Try it out → paste job_id → Execute

**Via curl:**
```bash
curl -X POST http://localhost:8000/jobs/{job_id}/retry
```

---

## Pipeline Definition Examples

### Validate only
```json
[
  {"step": "validate", "params": {"expected_type": "csv"}}
]
```

### Full pipeline (CSV → transform → JSON → compress)
```json
[
  {"step": "validate", "params": {"expected_type": "csv"}},
  {"step": "transform", "params": {
    "select_columns": ["name", "email"],
    "filter": {"column": "age", "gt": 18},
    "apply": {"column": "name", "operation": "uppercase"}
  }},
  {"step": "convert", "params": {"output_format": "json"}},
  {"step": "compress", "params": {"algorithm": "gzip"}},
  {"step": "notify", "params": {"webhook_url": "https://your-webhook-url.com"}}
]
```

### JSON to CSV with schema (streaming)
```json
[
  {"step": "validate", "params": {"expected_type": "json"}},
  {"step": "convert", "params": {
    "output_format": "csv",
    "json_schema": {
      "name": "string",
      "address.city": "string"
    }
  }}
]
```

### Extract from zip then process
```json
[
  {"step": "decompress", "params": {"algorithm": "zip"}},
  {"step": "validate", "params": {"expected_type": "csv"}},
  {"step": "transform", "params": {"select_columns": ["name", "email"]}}
]
```

---

## Processing Steps Implemented

| Step | Description |
|---|---|
| **validate** | Checks file exists, not empty, correct type, valid content. Returns metadata (size, type, row count) |
| **transform** | Filter rows, select columns, apply string operations (uppercase, lowercase, trim) — CSV and JSON |
| **convert** | CSV to JSON, JSON to CSV. Supports schema-based streaming for nested JSON |
| **compress** | Gzip compression (chunk by chunk streaming) |
| **decompress** | Zip extraction |
| **notify** | Webhook callback with job status and result location. Retries up to MAX_RETRIES times |

---

## Configuration

Environment variables (set in docker-compose.ha_misrad.yml):

| Variable | Default | Description |
|---|---|---|
| `MAX_RETRIES` | 3 | Number of retry attempts per step before declaring failure |
| `PROC_TIME_EST_SAMPLE_ROWS` | 10 | Number of rows to sample for processing time estimation |
| `STORAGE_PATH` | /app/storage | Where uploaded and processed files are stored |

---

## Test Data

Sample files are provided in the `test_data/` folder:
- `sample.csv` → small CSV with 4 rows (name, email, age)
- `large_sample.csv` → larger CSV with 1000 rows for performance testing
