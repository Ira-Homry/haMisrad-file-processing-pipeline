import os
import uuid
from datetime import datetime

import psycopg2
from psycopg2.extras import RealDictCursor


# ─────────────────────────────────────────
# Connection
# ─────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL")


def get_connection():
    return psycopg2.connect(DATABASE_URL)


# ─────────────────────────────────────────
# Create tables on startup
# ─────────────────────────────────────────

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            job_id              VARCHAR PRIMARY KEY,
            file_name           VARCHAR NOT NULL,
            pipeline_definition TEXT NOT NULL,
            status              VARCHAR NOT NULL DEFAULT 'PENDING',
            current_step_index  INTEGER NOT NULL DEFAULT 0,
            progress            INTEGER NOT NULL DEFAULT 0,
            estimated_seconds   INTEGER,
            estimated_at        TIMESTAMP,
            output_file         VARCHAR,
            user_api_key        VARCHAR,
            created_at          TIMESTAMP,
            started_at          TIMESTAMP,
            completed_at        TIMESTAMP,
            error               TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS steps (
            id               SERIAL PRIMARY KEY,
            job_id           VARCHAR NOT NULL,
            step_id          INTEGER NOT NULL,
            attempt_number   INTEGER NOT NULL DEFAULT 1,
            step_name        VARCHAR NOT NULL,
            status           VARCHAR NOT NULL DEFAULT 'PENDING',
            progress         INTEGER NOT NULL DEFAULT 0,
            started_at       TIMESTAMP,
            completed_at     TIMESTAMP,
            error            TEXT
        )
    """)

    conn.commit()
    cursor.close()
    conn.close()


# ─────────────────────────────────────────
# Job operations
# ─────────────────────────────────────────

def create_job_details(file_name, pipeline_definition, user_api_key=None):
    job_id = str(uuid.uuid4())
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO jobs (job_id, file_name, pipeline_definition, status, current_step_index, progress, user_api_key, created_at)
        VALUES (%s, %s, %s, 'PENDING', 0, 0, %s, %s)
    """, (job_id, file_name, pipeline_definition, user_api_key, datetime.utcnow()))

    conn.commit()
    cursor.close()
    conn.close()
    return job_id


def get_job_details(job_id):
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    cursor.execute("SELECT * FROM jobs WHERE job_id = %s", (job_id,))
    job = cursor.fetchone()

    cursor.close()
    conn.close()
    return job


def update_job_status(job_id, status, error=None, output_file=None):
    conn = get_connection()
    cursor = conn.cursor()

    if status == "PROCESSING":
        cursor.execute("""
            UPDATE jobs SET status = %s, started_at = %s WHERE job_id = %s AND started_at IS NULL
        """, (status, datetime.utcnow(), job_id))

    elif status in ("COMPLETED", "FAILED"):
        cursor.execute("""
            UPDATE jobs SET status = %s, completed_at = %s, error = %s, output_file = %s WHERE job_id = %s
        """, (status, datetime.utcnow(), error, output_file, job_id))

    else:
        cursor.execute("UPDATE jobs SET status = %s WHERE job_id = %s", (status, job_id))

    conn.commit()
    cursor.close()
    conn.close()


def update_job_progress(job_id, progress):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE jobs SET progress = %s WHERE job_id = %s
    """, (progress, job_id))

    conn.commit()
    cursor.close()
    conn.close()


def update_job_estimation(job_id, estimated_seconds):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE jobs SET estimated_seconds = %s, estimated_at = %s WHERE job_id = %s
    """, (estimated_seconds, datetime.utcnow(), job_id))

    conn.commit()
    cursor.close()
    conn.close()


def update_current_step_index(job_id, step_index):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE jobs SET current_step_index = %s WHERE job_id = %s
    """, (step_index, job_id))

    conn.commit()
    cursor.close()
    conn.close()


def get_last_completed_step(job_id):
    # returns the highest step_id that completed successfully for this job
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT MAX(step_id) FROM steps
        WHERE job_id = %s AND status = 'COMPLETED'
    """, (job_id,))

    result = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return result or 0


# ─────────────────────────────────────────
# Step operations
# ─────────────────────────────────────────

def get_next_attempt_number(job_id, step_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT MAX(attempt_number) FROM steps WHERE job_id = %s AND step_id = %s
    """, (job_id, step_id))

    result = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return (result + 1) if result else 1


def insert_step(job_id, step_id, step_name):
    attempt_number = get_next_attempt_number(job_id, step_id)
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO steps (job_id, step_id, attempt_number, step_name, status, progress, started_at)
        VALUES (%s, %s, %s, %s, 'RUNNING', 0, %s)
    """, (job_id, step_id, attempt_number, step_name, datetime.utcnow()))

    conn.commit()
    cursor.close()
    conn.close()
    return attempt_number


def update_step_status(job_id, step_id, attempt_number, status, error=None):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE steps SET status = %s, completed_at = %s, error = %s
        WHERE job_id = %s AND step_id = %s AND attempt_number = %s
    """, (status, datetime.utcnow(), error, job_id, step_id, attempt_number))

    conn.commit()
    cursor.close()
    conn.close()


def update_step_progress(job_id, step_id, attempt_number, progress):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE steps SET progress = %s
        WHERE job_id = %s AND step_id = %s AND attempt_number = %s
    """, (progress, job_id, step_id, attempt_number))

    conn.commit()
    cursor.close()
    conn.close()
