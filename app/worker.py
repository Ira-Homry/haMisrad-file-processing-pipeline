import os
import json
import time
import glob
import logging
import tempfile

import redis

from dbops import (
    init_db,
    get_job_details,
    update_job_status,
    update_job_progress,
    update_job_estimation,
    update_current_step_index,
    insert_step,
    update_step_status,
    update_step_progress,
    get_last_completed_step
)

from wrkr_steps import validate
from wrkr_steps import transform
from wrkr_steps import convert
from wrkr_steps import comp_decomp_ops
from wrkr_steps import notify_us


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
REDIS_URL                 = os.getenv("REDIS_URL")
STORAGE_PATH              = os.getenv("STORAGE_PATH", "/app/storage")
QUEUE_NAME                = "jobs"
MAX_RETRIES               = int(os.getenv("MAX_RETRIES", "3"))           # configurable via environment variable
PROC_TIME_EST_SAMPLE_ROWS = int(os.getenv("PROC_TIME_EST_SAMPLE_ROWS", "10"))  # rows to sample for time estimation
RETRY_DELAY               = 2       # seconds between retries
DB_RETRY_COUNT            = 5       # retries to find job in PostgreSQL after picking from Redis
DB_RETRY_DELAY            = 1       # seconds between DB retries


# ─────────────────────────────────────────
# Step registry
# maps step name from pipeline definition to the correct function
# to add a new step: add a new entry here
# ─────────────────────────────────────────
STEP_REGISTRY = {
    "validate":   validate.validate_file,
    "transform":  transform.transform_file,
    "convert":    convert.parse_and_convert,
    "compress":   comp_decomp_ops.compress_file,
    "decompress": comp_decomp_ops.decompress_file,
    "notify":     notify_us.notify_webhook,
}

# steps that support progress tracking via callback
STEPS_WITH_PROGRESS = {"transform", "convert"}


# ─────────────────────────────────────────
# Worker main loop
# runs forever — picks jobs from Redis and processes them
# ─────────────────────────────────────────
def main():
    init_db()  # ensure tables exist before starting
    log.info("Worker started — waiting for jobs")
    r = redis.from_url(REDIS_URL)

    while True:
        # block until a job ID arrives in the queue
        _, job_id = r.blpop(QUEUE_NAME)
        job_id = job_id.decode("utf-8")
        log.info(f"Picked up job: {job_id}")

        try:
            process_job(job_id)
        except Exception as e:
            log.error(f"Unexpected error processing job {job_id}: {e}")
            # update job status to FAILED so it's visible in the jobs table
            try:
                update_job_status(job_id, "FAILED", error=str(e))
            except Exception as db_error:
                log.error(f"Could not update job status to FAILED: {db_error}")


# ─────────────────────────────────────────
# Process a single job
# ─────────────────────────────────────────
def process_job(job_id):

    # 1. fetch job details from PostgreSQL
    # retry a few times in case main.py is still writing to PostgreSQL
    job = None
    for attempt in range(DB_RETRY_COUNT):
        job = get_job_details(job_id)
        if job:
            break
        log.warning(f"Job {job_id} not found in DB — retrying ({attempt + 1}/{DB_RETRY_COUNT})")
        time.sleep(DB_RETRY_DELAY)

    if not job:
        log.error(f"Job {job_id} not found in DB after {DB_RETRY_COUNT} retries — skipping")
        return

    # 2. update job status to PROCESSING
    update_job_status(job_id, "PROCESSING")
    log.info(f"Job {job_id} — status: PROCESSING")

    # 3. read pipeline definition and current step index
    pipeline    = json.loads(job["pipeline_definition"])
    start_from  = job["current_step_index"]  # resume from last successful step
    total_steps = len(pipeline)

    # 4. find the correct starting file
    # if resuming — find the output file of the last completed step
    # if fresh job — use the original uploaded file
    job_storage = os.path.join(STORAGE_PATH, job_id)
    os.makedirs(job_storage, exist_ok=True)

    if start_from > 0:
        # resuming — find the output file of the last completed step
        pattern = os.path.join(job_storage, f"step{start_from}.*")
        matching_files = glob.glob(pattern)
        if matching_files:
            last_output_file = matching_files[0]
            log.info(f"Job {job_id} — resuming from step {start_from + 1}, using file: {last_output_file}")
        else:
            error = f"Cannot find intermediate file for step {start_from}"
            log.error(f"Job {job_id} — {error}")
            update_job_status(job_id, "FAILED", error=error)
            return
    else:
        # fresh job — use the original uploaded file
        last_output_file = job["file_name"]

    # 5. track row count from validate for progress and estimation
    row_count = None

    # 6. loop through each step starting from current_step_index
    for step_position, step_def in enumerate(pipeline, start=1):

        # skip already completed steps
        if step_position <= start_from:
            log.info(f"Job {job_id} — skipping step {step_position} (already completed)")
            continue

        step_name   = step_def["step"]
        step_params = step_def.get("params", {})

        # pass row_count to steps that need it for progress tracking
        if row_count:
            step_params["row_count"] = row_count

        log.info(f"Job {job_id} — starting step {step_position}: {step_name}")

        # 7. insert step record in PostgreSQL
        attempt_number = insert_step(job_id, step_position, step_name)

        # 8. build output file path for this step with correct extension
        output_ext  = _get_output_extension(step_name, step_params, last_output_file)
        output_file = os.path.join(job_storage, f"step{step_position}{output_ext}")

        # 9. build progress callback for steps that support it
        def make_progress_callback(jid, sid, anum):
            def progress_callback(processed, total):
                if total > 0:
                    pct = int((processed / total) * 100)
                    update_step_progress(jid, sid, anum, pct)
            return progress_callback

        # 10. run the step with retry logic
        step_function = STEP_REGISTRY.get(step_name)
        if not step_function:
            error = f"Unknown step: {step_name}"
            update_step_status(job_id, step_position, attempt_number, "FAILED", error=error)
            update_job_status(job_id, "FAILED", error=error)
            log.error(f"Job {job_id} — {error}")
            return

        success    = False
        last_error = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                if step_name == "notify":
                    # notify step receives job details instead of output path
                    step_function(last_output_file, step_params, dict(job))

                elif step_name == "validate":
                    # validate step only reads the file — no output path needed
                    result = step_function(last_output_file, step_params)
                    # save row_count for progress tracking in subsequent steps
                    if result and "row_count" in result:
                        row_count = result["row_count"]
                        # run estimation after validation
                        _estimate_processing_time(job_id, last_output_file, pipeline, step_params, row_count)

                elif step_name in STEPS_WITH_PROGRESS:
                    # steps that support progress tracking
                    callback = make_progress_callback(job_id, step_position, attempt_number)
                    step_function(last_output_file, step_params, output_file, callback)

                else:
                    step_function(last_output_file, step_params, output_file)

                success = True
                break
            except Exception as e:
                last_error = str(e)
                log.warning(f"Job {job_id} — step {step_name} attempt {attempt} failed: {last_error}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)

        # 11. update step and job status based on success or failure
        if success:
            update_step_status(job_id, step_position, attempt_number, "COMPLETED")
            update_step_progress(job_id, step_position, attempt_number, 100)
            update_current_step_index(job_id, step_position)

            # update job level progress
            job_progress = int((step_position / total_steps) * 100)
            update_job_progress(job_id, job_progress)

            # validate doesn't produce an output file — keep the original file
            if step_name != "validate":
                last_output_file = output_file

            log.info(f"Job {job_id} — step {step_position} {step_name}: COMPLETED ({job_progress}%)")
        else:
            update_step_status(job_id, step_position, attempt_number, "FAILED", error=last_error)
            update_job_status(job_id, "FAILED", error=last_error)
            log.error(f"Job {job_id} — step {step_position} {step_name}: FAILED — {last_error}")
            return

    # 12. all steps completed — update job status to COMPLETED
    update_job_status(job_id, "COMPLETED", output_file=last_output_file)
    update_job_progress(job_id, 100)
    log.info(f"Job {job_id} — COMPLETED — output: {last_output_file}")


# ─────────────────────────────────────────
# Processing time estimation
# runs after validation — samples PROC_TIME_EST_SAMPLE_ROWS rows
# through all non-compress steps to estimate total processing time
# documented in DECISIONS.md and INTERVIEW_NOTES.md
# ─────────────────────────────────────────
def _estimate_processing_time(job_id, file_path, pipeline, validate_params, total_rows):
    if not total_rows or total_rows == 0:
        return

    try:
        sample_params = {"row_count": PROC_TIME_EST_SAMPLE_ROWS}

        # get non-compress, non-validate, non-notify steps for estimation
        estimation_steps = [
            s for s in pipeline
            if s["step"] not in ("validate", "compress", "decompress", "notify")
        ]

        if not estimation_steps:
            return

        start_time   = time.time()
        current_file = file_path

        for step_def in estimation_steps:
            step_name   = step_def["step"]
            step_params = {**step_def.get("params", {}), **sample_params}
            step_function = STEP_REGISTRY.get(step_name)

            if not step_function:
                continue

            # use a temp file for estimation output
            output_ext  = _get_output_extension(step_name, step_params, current_file)
            with tempfile.NamedTemporaryFile(suffix=output_ext, delete=False) as tmp:
                tmp_path = tmp.name

            step_function(current_file, step_params, tmp_path)
            current_file = tmp_path

        sample_time = time.time() - start_time

        # extrapolate to full file
        if PROC_TIME_EST_SAMPLE_ROWS > 0:
            estimated_seconds = int((sample_time / PROC_TIME_EST_SAMPLE_ROWS) * total_rows)
            update_job_estimation(job_id, estimated_seconds)
            log.info(f"Job {job_id} — estimated processing time: {estimated_seconds}s (based on {PROC_TIME_EST_SAMPLE_ROWS} sample rows)")

    except Exception as e:
        log.warning(f"Job {job_id} — estimation failed (non-critical): {e}")


# ─────────────────────────────────────────
# Helper — determine output file extension based on step
# ─────────────────────────────────────────
def _get_output_extension(step_name, step_params, input_file):
    input_ext = os.path.splitext(input_file)[1]  # e.g. .csv

    if step_name == "convert":
        output_format = step_params.get("output_format", "").lower()
        return f".{output_format}"  # .json or .csv

    elif step_name == "compress":
        algorithm = step_params.get("algorithm", "").lower()
        if algorithm == "gzip":
            return input_ext + ".gz"  # e.g. .json.gz

    elif step_name == "decompress":
        # remove the compression extension
        return os.path.splitext(input_ext)[1]  # e.g. .csv from .csv.gz

    # transform and others keep the same extension as input
    return input_ext


# ─────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────
if __name__ == "__main__":
    main()
