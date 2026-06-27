# Design Decisions

## 1. Large File Handling

**Approach chosen:** Streaming processing — each step reads and writes the file chunk by chunk or row by row without loading the entire file into memory.

**Why:** 100MB files with multiple concurrent jobs could fill RAM quickly. Memory safety is more predictable and scalable than speed. A pipeline handling unknown file sizes should never assume it has enough RAM.

**Memory usage:** At any given moment only one row (CSV) or one chunk (binary) is held in memory regardless of file size.

**Streaming mechanism per file type:**
- CSV → line by line using Python's built-in `csv.reader`
- JSON → chunk by chunk using `ijson` library for validation; `ijson` targeted streaming when schema is provided for nested JSON to CSV conversion
- Binary files (gzip, zip) → `f.read(8192)` chunk by chunk

**Non-streamable cases:**
- Nested JSON to CSV conversion without schema → full file load unavoidable. The "streaming processing where possible" clause in the requirements directly justifies this exception. A `json_schema` parameter can be provided to enable streaming even for nested JSON.
- Zip extraction → requires reading the full zip central directory first

**Side effect of streaming:** The file is read independently by each step — meaning in total the file is streamed through several times through the pipeline, but never as one full load into memory at once.

---

## 2. Step Failure Strategy

**Approach chosen:** Retry each step up to `MAX_RETRIES` times (configurable via environment variable, default 3) before declaring the step and job as FAILED.

**Why:** Some failures are temporary (network issues, disk contention) and may succeed on retry. Permanent failures (wrong file type, corrupt data) will still fail after all retries.

**Configurable retry logic:**
```yaml
# docker-compose.ha_misrad.yml
worker:
  environment:
    - MAX_RETRIES=3
```

**Partial progress:** We use an append-only strategy — failed step attempts are never overwritten. Each retry inserts a new record with an incremented `attempt_number`. This gives a full history of every attempt.

**Resume from last successful step:** When a failed job is retried via `POST /jobs/{job_id}/retry`, the worker reads `current_step_index` from the jobs table and resumes from the next step — skipping steps that already completed successfully.

---

## 3. File Cleanup Strategy

**Approach chosen:** Files are currently retained indefinitely during the development phase. A retention mechanism is planned but not implemented.

**Input files:** Saved to `storage/{job_id}/` on upload. Retained after processing.

**Intermediate files:** Each step writes its output to `storage/{job_id}/step{N}.{ext}`. Retained after processing.

**Output files:** The final step output is recorded in the jobs table as `output_file`. Retained until manually cleaned.

**One thing I would do differently with more time:** Implement a background cleanup job that deletes job storage folders after a configurable retention period (e.g. 24 hours) as the assignment suggests.

---

## 4. Progress Tracking

**Approach chosen:** Two levels of progress tracking:
1. **Job level** → percentage of steps completed (`current_step_index / total_steps * 100`) stored in `jobs.progress`
2. **Step level** → percentage of rows processed stored in `steps.progress`, updated via callback as each row is processed

**Granularity:** Progress is updated after every row for transform and convert steps. Validate and compress report 0% until complete then 100%.

**Trade-offs:** Frequent PostgreSQL updates (one per row) add overhead. For 1000 rows this means 1000 UPDATE queries per step. For very large files this could be optimized by updating every N rows instead of every row.

---

## 5. Processing Time Estimation

**Approach chosen:** Post-validation sampling — after the validate step completes, a sample of `PROC_TIME_EST_SAMPLE_ROWS` rows (default 10, configurable) is run through all non-compress steps to measure processing speed. The result is extrapolated to the full file.

**Formula:** `estimated_seconds = (sample_time / PROC_TIME_EST_SAMPLE_ROWS) * total_rows`

**Configurable sample size:**
```yaml
worker:
  environment:
    - PROC_TIME_EST_SAMPLE_ROWS=10
```

**Why after validation:** We need `total_rows` from validation to extrapolate. No point estimating on a corrupt or invalid file.

**Known limitations:** The estimation assumes all rows take similar processing time — not always true for complex nested JSON. For small files the overhead of starting each step dominates over actual processing time, making the estimate inaccurate. The estimation improves for larger files where processing time dominates.

**Timestamps stored:**
- `estimated_at` → when the estimation was calculated
- `estimated_seconds` → estimated total processing time

---

## 6. Webhook Reliability

**Approach chosen:** Retry up to `MAX_RETRIES` times with the same retry logic as other steps. If all retries fail the notify step is marked FAILED and the job is marked FAILED.

**Why:** A failed webhook means the downstream system was not notified — the job result may be lost from their perspective. Treating it as a failure ensures the user is aware and can retry.

**Duplicate notifications:** Since we retry on failure, a webhook could be called multiple times if it succeeds on a later attempt after a transient failure. This is documented as a known limitation — implementing idempotency keys would require coordination with the webhook receiver.

---

## 7. Parallel Processing

**Approach chosen:** Parallel processing at the job level — multiple workers process different jobs simultaneously. Parallel step execution within a single job was not implemented.

**Why no parallel step execution:** All pipeline steps are sequential and dependent on each other's output. There are no independent steps that could safely run in parallel.

**How to scale workers:**
```bash
docker compose -f docker-compose.ha_misrad.yml up --scale worker=3
```

**Note:** The `container_name` was removed from the worker service to allow scaling. Docker automatically names workers `file-pipeline-worker-1`, `file-pipeline-worker-2`, etc.

---

## 8. Storage Organization

**Approach chosen:** Each job gets its own subfolder in storage: `storage/{job_id}/`

**Why:** Makes it easy to find all files related to a specific job, clean up files when a job expires, and debug issues by looking at intermediate files.

**File naming:** Each step output is named `step{N}.{ext}` where N is the step position and ext is the appropriate file extension for that step's output format.

---

## 9. One Thing I Would Do Differently With More Time

Implement proper file cleanup with configurable retention periods. Currently all files are retained indefinitely. A background cleanup job that removes `storage/{job_id}/` folders after a configurable period (e.g. 24 hours) would prevent disk space from filling up in production. This would also handle cleanup if the service crashes — a startup check could identify and clean up orphaned files from jobs that never completed.
