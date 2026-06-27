import os
import csv
import json
import ijson


# ─────────────────────────────────────────
# Transform step
# ─────────────────────────────────────────
# Supported params:
#   select_columns: ["name", "email"]       → keep only these columns
#   filter: {"column": "age", "gt": 18}     → keep rows where age > 18
#   apply: {"column": "name", "operation": "uppercase" | "lowercase" | "trim"}
#
# Streams through the file row by row — no full load into memory
# Writes transformed rows to a new output file on disk
# Reports progress via progress_callback if provided
# Returns the path of the output file
# ─────────────────────────────────────────

def transform_file(file_path, params, output_file, progress_callback=None):
    file_extension = os.path.splitext(file_path)[1].lower().strip(".")

    if file_extension == "csv":
        _transform_csv(file_path, params, output_file, progress_callback)
    elif file_extension == "json":
        _transform_json(file_path, params, output_file, progress_callback)
    else:
        raise ValueError(f"Transform step does not support file type: {file_extension}")

    return {"output_file": output_file}


# ─────────────────────────────────────────
# CSV transform — streams row by row
# ─────────────────────────────────────────

def _transform_csv(file_path, params, output_file, progress_callback):
    select_columns = params.get("select_columns")
    filter_param   = params.get("filter")
    apply_param    = params.get("apply")

    with open(file_path, "r") as infile, open(output_file, "w", newline="") as outfile:
        reader = csv.DictReader(infile)

        # determine output columns
        out_columns = select_columns if select_columns else reader.fieldnames
        writer = csv.DictWriter(outfile, fieldnames=out_columns)
        writer.writeheader()

        total_rows = params.get("row_count", 0)
        processed  = 0

        for row in reader:
            # apply filter
            if filter_param and not _apply_filter(row, filter_param):
                continue

            # select columns
            if select_columns:
                row = {col: row[col] for col in select_columns if col in row}

            # apply transformation
            if apply_param:
                row = _apply_transformation(row, apply_param)

            writer.writerow(row)
            processed += 1

            # report progress
            if progress_callback and total_rows > 0:
                progress_callback(processed, total_rows)


# ─────────────────────────────────────────
# JSON transform — streams item by item via ijson
# ─────────────────────────────────────────

def _transform_json(file_path, params, output_file, progress_callback):
    select_columns = params.get("select_columns")
    filter_param   = params.get("filter")
    apply_param    = params.get("apply")

    total_rows = params.get("row_count", 0)
    processed  = 0

    with open(file_path, "rb") as infile, open(output_file, "w") as outfile:
        outfile.write("[\n")
        first = True

        for item in ijson.items(infile, "item"):
            # apply filter
            if filter_param and not _apply_filter(item, filter_param):
                continue

            # select columns
            if select_columns:
                item = {col: item[col] for col in select_columns if col in item}

            # apply transformation
            if apply_param:
                item = _apply_transformation(item, apply_param)

            if not first:
                outfile.write(",\n")
            outfile.write(json.dumps(item))
            first = False

            processed += 1

            # report progress
            if progress_callback and total_rows > 0:
                progress_callback(processed, total_rows)

        outfile.write("\n]")


# ─────────────────────────────────────────
# Helper — apply filter condition
# ─────────────────────────────────────────

def _apply_filter(row, filter_param):
    column = filter_param.get("column")
    value  = str(row.get(column, ""))

    if "gt" in filter_param:
        return float(value) > float(filter_param["gt"])
    if "lt" in filter_param:
        return float(value) < float(filter_param["lt"])
    if "eq" in filter_param:
        return value == str(filter_param["eq"])
    if "contains" in filter_param:
        return filter_param["contains"] in value

    return True


# ─────────────────────────────────────────
# Helper — apply string transformation
# ─────────────────────────────────────────

def _apply_transformation(row, apply_param):
    column    = apply_param.get("column")
    operation = apply_param.get("operation", "").lower()

    if column not in row:
        return row

    value = str(row[column])

    if operation == "uppercase":
        row[column] = value.upper()
    elif operation == "lowercase":
        row[column] = value.lower()
    elif operation == "trim":
        row[column] = value.strip()

    return row
