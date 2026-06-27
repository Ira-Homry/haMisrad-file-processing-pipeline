import requests


# ─────────────────────────────────────────
# Notify step
# ─────────────────────────────────────────
# Sends a webhook callback when the pipeline completes
# Supported params:
#   webhook_url: "https://..."  → the URL to send the notification to
#
# The webhook receives:
#   job_id     → the job that completed
#   status     → COMPLETED or FAILED
#   output_file → location of the result file (if completed)
#   error      → error message (if failed)
#
# Retry logic:
#   retries up to 3 times if the webhook call fails
#   if all retries fail — job is marked as FAILED
# ─────────────────────────────────────────

MAX_RETRIES = 3


def notify_webhook(file_path, params, job_details):
    webhook_url = params.get("webhook_url")

    if not webhook_url:
        raise ValueError("notify step requires a webhook_url param")

    payload = {
        "job_id":      job_details.get("job_id"),
        "status":      job_details.get("status"),
        "output_file": job_details.get("output_file"),
        "error":       job_details.get("error")
    }

    # retry up to MAX_RETRIES times
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(webhook_url, json=payload, timeout=10)
            if response.status_code == 200:
                return {"webhook_url": webhook_url, "status": "sent"}
            else:
                last_error = f"Webhook returned status {response.status_code}"
        except requests.exceptions.RequestException as e:
            last_error = str(e)

    # all retries failed
    raise ValueError(
        f"Webhook failed after {MAX_RETRIES} attempts: {last_error}"
    )
