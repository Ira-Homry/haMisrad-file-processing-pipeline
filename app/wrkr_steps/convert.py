import os
import csv
import json
import ijson


# ─────────────────────────────────────────
# Convert step
# ─────────────────────────────────────────
# Supported params:
#   output_format: "json" | "csv"
#   json_schema: {"name": "string", "address.city": "string"}  → optional
#                if provided: streams nested JSON using ijson
#                if not provided: full read of JSON into memory
#
# Reports progress via progress_callback if provided
# To add a new format conversion in the future:
#   just add a new function and register it in the CONVERTERS dictionary below
# ─────────────────────────────────────────

def parse_and_convert(file_path, params, output_file, progress_callback=None):
    output_format  = params.get("output_format", "").lower()
    file_extension = os.path.splitext(file_path)[1].lower().strip(".")

    # look up the converter function for this format pair
    converter = CONVERTERS.get((file_extension, output_format))

    if not converter:
        raise ValueError(
            f"Unsupported conversion: {file_extension} to {output_format}"
        )

    converter(file_path, output_file, params, progress_callback)
    return {"output_file": output_file}


# ─────────────────────────────────────────
# CSV to JSON — streams row by row
# ─────────────────────────────────────────

def _csv_to_json(file_path, output_file, params, progress_callback):
    total_rows = params.get("row_count", 0)
    processed  = 0

    with open(file_path, "r") as infile, open(output_file, "w") as outfile:
        reader = csv.DictReader(infile)
        outfile.write("[\n")
        first = True
        for row in reader:
            if not first:
                outfile.write(",\n")
            outfile.write(json.dumps(row))
            first = False
            processed += 1
            if progress_callback and total_rows > 0:
                progress_callback(processed, total_rows)
        outfile.write("\n]")


# ─────────────────────────────────────────
# JSON to CSV
# streamed if schema provided, full read if not
# ─────────────────────────────────────────

def _json_to_csv(file_path, output_file, params, progress_callback):
    json_schema = params.get("json_schema")
    if json_schema:
        _json_to_csv_streamed(file_path, output_file, params, json_schema, progress_callback)
    else:
        _json_to_csv_full_read(file_path, output_file, params, progress_callback)


def _json_to_csv_streamed(file_path, output_file, params, json_schema, progress_callback):
    # json_schema keys define which fields to extract
    # supports dot notation for nested fields e.g. "address.city"
    fields     = list(json_schema.keys())
    total_rows = params.get("row_count", 0)
    processed  = 0

    with open(file_path, "rb") as infile, open(output_file, "w", newline="") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=fields)
        writer.writeheader()

        for item in ijson.items(infile, "item"):
            row = {}
            for field in fields:
                keys = field.split(".")
                value = item
                for key in keys:
                    if isinstance(value, dict):
                        value = value.get(key, "")
                    else:
                        value = ""
                row[field] = value
            writer.writerow(row)
            processed += 1
            if progress_callback and total_rows > 0:
                progress_callback(processed, total_rows)


def _json_to_csv_full_read(file_path, output_file, params, progress_callback):
    # full read is unavoidable for unknown nested JSON structure
    # documented in DECISIONS.md and INTERVIEW_NOTES.md
    with open(file_path, "r") as infile:
        data = json.load(infile)

    if not isinstance(data, list):
        data = [data]

    if not data:
        raise ValueError("JSON file is empty")

    flat_data  = [_flatten(item) for item in data]
    fields     = list(flat_data[0].keys())
    total_rows = len(flat_data)
    processed  = 0

    with open(output_file, "w", newline="") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=fields)
        writer.writeheader()
        for row in flat_data:
            writer.writerow(row)
            processed += 1
            if progress_callback and total_rows > 0:
                progress_callback(processed, total_rows)


# ─────────────────────────────────────────
# Helper — flatten nested JSON into flat dict
# ─────────────────────────────────────────

def _flatten(item, parent_key="", sep="."):
    flat = {}
    for key, value in item.items():
        new_key = f"{parent_key}{sep}{key}" if parent_key else key
        if isinstance(value, dict):
            flat.update(_flatten(value, new_key, sep))
        else:
            flat[new_key] = value
    return flat


# ─────────────────────────────────────────
# Converters registry
# To add a new format: add a new function above and register it here
# ─────────────────────────────────────────

CONVERTERS = {
    ("csv", "json"): _csv_to_json,
    ("json", "csv"): _json_to_csv,
}
