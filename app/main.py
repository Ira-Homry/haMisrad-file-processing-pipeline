import os
import json
import uuid
import logging

import redis
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse

from dbops import (
    init_db,
    create_job_details,
    get_job_details,
    update_job_status
)


# ─────────────────────────────────────────
# Logging setup
# ─────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────
REDIS_URL     = os.getenv("REDIS_URL")
STORAGE_PATH  = os.getenv("STORAGE_PATH", "/app/storage")
QUEUE_NAME    = "jobs"
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB in bytes


# ─────────────────────────────────────────
# FastAPI app
# ─────────────────────────────────────────
app = FastAPI(
    title="File Processing Pipeline",
    description="Upload files and process them through configurable pipelines"
)


# ─────────────────────────────────────────
# Startup — create tables and connect to Redis
# ─────────────────────────────────────────
@app.on_event("startup")
def startup():
    init_db()
    log.info("Database tables initialized")


# ─────────────────────────────────────────
# Redis connection
# ─────────────────────────────────────────
def get_redis():
    return redis.from_url(REDIS_URL)


# ─────────────────────────────────────────
# Endpoint 1 — Upload file
# POST /upload
# receives file + pipeline definition
# saves file to storage, creates job in PostgreSQL, puts job ID in Redis
# returns job ID immediately
# ─────────────────────────────────────────
@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    pipeline: str = Form(...)
):
    # validate pipeline definition is valid JSON
    try:
        json.loads(pipeline)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="pipeline must be valid JSON")

    # validate file size — stream chunk by chunk to avoid loading full file in memory
    file_size  = 0
    chunk_size = 8192
    file_path  = os.path.join(STORAGE_PATH, f"{uuid.uuid4()}_{file.filename}")

    os.makedirs(STORAGE_PATH, exist_ok=True)

    with open(file_path, "wb") as out_file:
        while chunk := await file.read(chunk_size):
            file_size += len(chunk)
            if file_size > MAX_FILE_SIZE:
                os.remove(file_path)
                raise HTTPException(status_code=400, detail="File exceeds 100MB limit")
            out_file.write(chunk)

    log.info(f"File saved: {file_path} ({file_size} bytes)")

    # create job record in PostgreSQL first
    job_id = create_job_details(
        file_name=file_path,
        pipeline_definition=pipeline
    )
    log.info(f"Job created in PostgreSQL: {job_id}")

    # then put job ID in Redis queue
    r = get_redis()
    r.rpush(QUEUE_NAME, job_id)
    log.info(f"Job {job_id} added to Redis queue")

    return {"job_id": job_id, "status": "PENDING"}


# ─────────────────────────────────────────
# Endpoint 2 — Get job status
# GET /jobs/{job_id}
# returns job status, progress and step details from PostgreSQL
# ─────────────────────────────────────────
@app.get("/jobs/{job_id}")
def get_job_status(job_id):
    job = get_job_details(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id":              job["job_id"],
        "status":              job["status"],
        "progress":            job["progress"],
        "estimated_seconds":   job["estimated_seconds"],
        "estimated_at":        str(job["estimated_at"]) if job["estimated_at"] else None,
        "current_step_index":  job["current_step_index"],
        "file_name":           job["file_name"],
        "output_file":         job["output_file"],
        "created_at":          str(job["created_at"]),
        "started_at":          str(job["started_at"]) if job["started_at"] else None,
        "completed_at":        str(job["completed_at"]) if job["completed_at"] else None,
        "error":               job["error"]
    }


# ─────────────────────────────────────────
# Endpoint 3 — Download result file
# GET /jobs/{job_id}/result
# returns the output file for download
# ─────────────────────────────────────────
@app.get("/jobs/{job_id}/result")
def download_result(job_id):
    job = get_job_details(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != "COMPLETED":
        raise HTTPException(status_code=400, detail=f"Job is not completed yet — current status: {job['status']}")

    if not job["output_file"] or not os.path.exists(job["output_file"]):
        raise HTTPException(status_code=404, detail="Output file not found")

    return FileResponse(
        job["output_file"],
        filename=os.path.basename(job["output_file"])
    )


# ─────────────────────────────────────────
# Endpoint 4 — Retry failed job
# POST /jobs/{job_id}/retry
# puts failed job back in Redis queue
# worker resumes from last successful step
# ─────────────────────────────────────────
@app.post("/jobs/{job_id}/retry")
def retry_job(job_id):
    job = get_job_details(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != "FAILED":
        raise HTTPException(status_code=400, detail=f"Job is not in a failed state — current status: {job['status']}")

    # reset job status to PENDING
    update_job_status(job_id, "PENDING")

    # put job ID back in Redis queue
    r = get_redis()
    r.rpush(QUEUE_NAME, job_id)
    log.info(f"Job {job_id} requeued for retry")

    return {"job_id": job_id, "status": "PENDING", "message": "Job requeued for retry"}
