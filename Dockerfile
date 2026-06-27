# ─────────────────────────────────────────
# Base image — shared by API and Worker
# ─────────────────────────────────────────
FROM python:3.11-slim AS base

# Set working directory inside the container
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ .

# ─────────────────────────────────────────
# API target — runs FastAPI
# ─────────────────────────────────────────
FROM base AS api

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

# ─────────────────────────────────────────
# Worker target — runs the pipeline worker
# ─────────────────────────────────────────
FROM base AS worker

CMD ["python", "-m", "worker"]
