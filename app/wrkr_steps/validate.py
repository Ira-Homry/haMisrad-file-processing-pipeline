import os
import csv
import ijson


# ─────────────────────────────────────────
# Validate step
# ─────────────────────────────────────────
# Check 1: File exists on disk
# Check 2: File is not empty
# Check 3: File extension matches expected type
# Check 4: Content validation — streams through file
#          CSV: checks consistent columns row by row
#          JSON: checks valid JSON structure chunk by chunk via ijson
# Returns metadata as output: size, type, row count
# row_count is used by subsequent steps for progress tracking
# ─────────────────────────────────────────

def validate_file(file_path, params):
    expected_type = params.get("expected_type", "").lower()

    # Check 1 — file exists
    if not os.path.exists(file_path):
        raise ValueError(f"File not found: {file_path}")

    # Check 2 — file not empty
    file_size = os.path.getsize(file_path)
    if file_size == 0:
        raise ValueError(f"File is empty: {file_path}")

    # Check 3 — extension matches expected type
    file_extension = os.path.splitext(file_path)[1].lower().strip(".")
    if expected_type and file_extension != expected_type:
        raise ValueError(
            f"File type mismatch: expected {expected_type}, got {file_extension}"
        )

    # Check 4 — content validation (streamed)
    row_count = None
    if file_extension == "csv":
        row_count = _validate_csv(file_path)
    elif file_extension == "json":
        row_count = _validate_json(file_path)

    # Return metadata collected as byproduct of checks
    return {
        "file_size": file_size,
        "file_type": file_extension,
        "row_count": row_count
    }


def _validate_csv(file_path):
    row_count = 0
    with open(file_path, "r") as f:
        reader = csv.reader(f)
        # read header row
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError("CSV file has no header row")
        num_columns = len(header)
        # stream through rows checking consistent columns
        for row in reader:
            if len(row) != num_columns:
                raise ValueError(
                    f"Inconsistent columns at row {row_count + 2}: "
                    f"expected {num_columns}, got {len(row)}"
                )
            row_count += 1
    return row_count


def _validate_json(file_path):
    row_count = 0
    # ijson streams chunk by chunk — no full load into memory
    # works for both simple and nested JSON
    with open(file_path, "rb") as f:
        try:
            for _ in ijson.items(f, "item"):
                row_count += 1
        except ijson.JSONError as e:
            raise ValueError(f"Invalid JSON structure: {e}")
    return row_count
