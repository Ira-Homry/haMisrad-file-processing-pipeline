import os
import time
import json
import pytest
import requests

# ─────────────────────────────────────────
# Integration tests for the File Processing Pipeline API
# These tests require all containers to be running:
#   docker compose -f docker-compose.ha_misrad.yml up
# ─────────────────────────────────────────

BASE_URL       = os.getenv("API_URL", "http://localhost:8000")
TEST_DATA_PATH = os.path.join(os.path.dirname(__file__), "../../test_data/sample.csv")

SIMPLE_PIPELINE = json.dumps([
    {"step": "validate", "params": {"expected_type": "csv"}}
])

FULL_PIPELINE = json.dumps([
    {"step": "validate", "params": {"expected_type": "csv"}},
    {"step": "transform", "params": {"select_columns": ["name", "email"], "apply": {"column": "name", "operation": "uppercase"}}},
    {"step": "convert", "params": {"output_format": "json"}},
    {"step": "compress", "params": {"algorithm": "gzip"}}
])

BROKEN_PIPELINE = json.dumps([
    {"step": "validate", "params": {"expected_type": "json"}}  # CSV file but expects JSON
])


def upload_file(pipeline=SIMPLE_PIPELINE):
    """Helper — upload sample.csv with given pipeline"""
    with open(TEST_DATA_PATH, "rb") as f:
        response = requests.post(
            f"{BASE_URL}/upload",
            files={"file": ("sample.csv", f, "text/csv")},
            data={"pipeline": pipeline}
        )
    return response


def wait_for_completion(job_id, timeout=60):
    """Helper — poll job status until completed or failed"""
    start = time.time()
    while time.time() - start < timeout:
        response = requests.get(f"{BASE_URL}/jobs/{job_id}")
        status = response.json()["status"]
        if status in ("COMPLETED", "FAILED"):
            return response.json()
        time.sleep(1)
    raise TimeoutError(f"Job {job_id} did not complete within {timeout} seconds")


# ── Test 1 — File upload and job creation ─

def test_upload_and_job_creation():
    """Upload a file and verify job ID is returned with PENDING status"""
    response = upload_file()

    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data
    assert data["status"] == "PENDING"
    assert len(data["job_id"]) > 0


# ── Test 2 — Pipeline execution end-to-end ─

def test_pipeline_execution_end_to_end():
    """Upload a file with full pipeline and verify it completes successfully"""
    response = upload_file(pipeline=FULL_PIPELINE)
    assert response.status_code == 200

    job_id = response.json()["job_id"]
    result = wait_for_completion(job_id)

    assert result["status"] == "COMPLETED"
    assert result["progress"] == 100
    assert result["current_step_index"] == 4
    assert result["output_file"] is not None


# ── Test 3 — Step failure handling ─────────

def test_step_failure_handling():
    """Upload a CSV file with pipeline expecting JSON — verify job fails"""
    response = upload_file(pipeline=BROKEN_PIPELINE)
    assert response.status_code == 200

    job_id = response.json()["job_id"]
    result = wait_for_completion(job_id)

    assert result["status"] == "FAILED"
    assert result["error"] is not None
    assert "mismatch" in result["error"].lower()


# ── Test 4 — Job status tracking ───────────

def test_job_status_tracking():
    """Verify status API returns all expected fields"""
    response = upload_file()
    assert response.status_code == 200

    job_id = response.json()["job_id"]
    wait_for_completion(job_id)

    status_response = requests.get(f"{BASE_URL}/jobs/{job_id}")
    assert status_response.status_code == 200

    data = status_response.json()
    assert "job_id" in data
    assert "status" in data
    assert "progress" in data
    assert "current_step_index" in data
    assert "created_at" in data
    assert "estimated_seconds" in data


# ── Test 5 — File retrieval ─────────────────

def test_file_retrieval():
    """Upload file, wait for completion and verify result can be downloaded"""
    response = upload_file(pipeline=FULL_PIPELINE)
    assert response.status_code == 200

    job_id = response.json()["job_id"]
    result = wait_for_completion(job_id)
    assert result["status"] == "COMPLETED"

    download_response = requests.get(f"{BASE_URL}/jobs/{job_id}/result")
    assert download_response.status_code == 200
    assert len(download_response.content) > 0


# ── Test 6 — Retry failed job ──────────────

def test_retry_failed_job():
    """Fail a job then retry it and verify it gets requeued"""
    # upload with broken pipeline to force failure
    response = upload_file(pipeline=BROKEN_PIPELINE)
    assert response.status_code == 200

    job_id = response.json()["job_id"]
    result = wait_for_completion(job_id)
    assert result["status"] == "FAILED"

    # retry the failed job
    retry_response = requests.post(f"{BASE_URL}/jobs/{job_id}/retry")
    assert retry_response.status_code == 200
    assert retry_response.json()["status"] == "PENDING"


# ── Test 7 — Invalid pipeline rejected ─────

def test_invalid_pipeline_rejected():
    """Upload a file with invalid JSON pipeline — verify API rejects it"""
    with open(TEST_DATA_PATH, "rb") as f:
        response = requests.post(
            f"{BASE_URL}/upload",
            files={"file": ("sample.csv", f, "text/csv")},
            data={"pipeline": "this is not json"}
        )

    assert response.status_code == 400
    assert "pipeline" in response.json()["detail"].lower()


# ── Test 8 — Job not found ──────────────────

def test_job_not_found():
    """Request status of non-existent job — verify 404 response"""
    response = requests.get(f"{BASE_URL}/jobs/non-existent-job-id")
    assert response.status_code == 404


# ── Test 9 — File size limit ───────────────

def test_file_size_limit():
    """Upload a file larger than 100MB — verify API rejects it"""
    # create a temporary file larger than 100MB
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
    tmp.write(b"name,email,age\n")
    # write enough data to exceed 100MB
    chunk = b"John,john@example.com,25\n" * 1000
    written = 0
    while written < 100 * 1024 * 1024:
        tmp.write(chunk)
        written += len(chunk)
    tmp.close()

    with open(tmp.name, "rb") as f:
        response = requests.post(
            f"{BASE_URL}/upload",
            files={"file": ("large.csv", f, "text/csv")},
            data={"pipeline": SIMPLE_PIPELINE}
        )

    os.unlink(tmp.name)
    assert response.status_code == 400
    assert "100MB" in response.json()["detail"]
