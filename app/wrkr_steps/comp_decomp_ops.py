import os
import gzip
import zipfile
import shutil


# ─────────────────────────────────────────
# Compress step
# ─────────────────────────────────────────
# Supported params:
#   algorithm: "gzip"   → compress the input file using gzip
#
# Streams chunk by chunk — no full load into memory
# Writes compressed output to a new file on disk
# Returns the path of the output file
# ─────────────────────────────────────────

def compress_file(file_path, params, output_path):
    algorithm = params.get("algorithm", "").lower()

    compressor = COMPRESSORS.get(algorithm)

    if not compressor:
        raise ValueError(
            f"Unsupported compression algorithm: {algorithm}"
        )

    compressor(file_path, output_path)
    return {"output_file": output_path}


# ─────────────────────────────────────────
# Decompress step
# ─────────────────────────────────────────
# Supported params:
#   algorithm: "zip"    → extract contents of a zip file
#
# Note: zip extraction requires reading the full zip structure first
# This is documented in DECISIONS.md and INTERVIEW_NOTES.md
# Returns the path of the extracted file
# ─────────────────────────────────────────

def decompress_file(file_path, params, output_path):
    algorithm = params.get("algorithm", "").lower()

    decompressor = DECOMPRESSORS.get(algorithm)

    if not decompressor:
        raise ValueError(
            f"Unsupported decompression algorithm: {algorithm}"
        )

    decompressor(file_path, output_path)
    return {"output_file": output_path}


# ─────────────────────────────────────────
# Gzip compression — streams chunk by chunk
# ─────────────────────────────────────────

def _gzip_compress(file_path, output_path):
    chunk_size = 8192
    with open(file_path, "rb") as infile, gzip.open(output_path, "wb") as outfile:
        while chunk := infile.read(chunk_size):
            outfile.write(chunk)


# ─────────────────────────────────────────
# Zip extraction — requires full zip structure
# not streamable — zip format stores index at end of file
# ─────────────────────────────────────────

def _zip_extract(file_path, output_path):
    output_dir = os.path.dirname(output_path)
    with zipfile.ZipFile(file_path, "r") as zip_ref:
        # get the first file in the zip
        names = zip_ref.namelist()
        if not names:
            raise ValueError("Zip file is empty")
        # extract the first file to the output path
        extracted = zip_ref.extract(names[0], output_dir)
        # rename to our expected output path
        shutil.move(extracted, output_path)


# ─────────────────────────────────────────
# Compressors registry
# To add a new algorithm: add a function above and register it here
# ─────────────────────────────────────────

COMPRESSORS = {
    "gzip": _gzip_compress,
}

# ─────────────────────────────────────────
# Decompressors registry
# To add a new algorithm: add a function above and register it here
# ─────────────────────────────────────────

DECOMPRESSORS = {
    "zip": _zip_extract,
}
