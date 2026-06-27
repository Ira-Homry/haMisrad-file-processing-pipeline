import os
import csv
import json
import pytest
import tempfile

# ─────────────────────────────────────────
# Unit tests for pipeline step functions
# These tests do not require any running containers
# They test each step function in isolation using temporary files
# ─────────────────────────────────────────

# ── Helpers ──────────────────────────────

def create_temp_csv(rows, header=None):
    """Create a temporary CSV file with given rows and return its path"""
    if header is None:
        header = ["name", "email", "age"]
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
    writer = csv.DictWriter(tmp, fieldnames=header)
    writer.writeheader()
    writer.writerows(rows)
    tmp.close()
    return tmp.name


def create_temp_json(data):
    """Create a temporary JSON file with given data and return its path"""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, tmp)
    tmp.close()
    return tmp.name


# ── Test 1 — Validate step ───────────────

class TestValidateStep:

    def test_validate_valid_csv(self):
        """validate_file should return metadata for a valid CSV"""
        from app.wrkr_steps.validate import validate_file

        file_path = create_temp_csv([
            {"name": "John", "email": "john@example.com", "age": "25"},
            {"name": "Jane", "email": "jane@example.com", "age": "30"},
        ])

        result = validate_file(file_path, {"expected_type": "csv"})

        assert result["file_type"] == "csv"
        assert result["row_count"] == 2
        assert result["file_size"] > 0

        os.unlink(file_path)

    def test_validate_wrong_type(self):
        """validate_file should raise ValueError if file type doesn't match expected"""
        from app.wrkr_steps.validate import validate_file

        file_path = create_temp_csv([
            {"name": "John", "email": "john@example.com", "age": "25"},
        ])

        with pytest.raises(ValueError, match="File type mismatch"):
            validate_file(file_path, {"expected_type": "json"})

        os.unlink(file_path)

    def test_validate_empty_file(self):
        """validate_file should raise ValueError for empty file"""
        from app.wrkr_steps.validate import validate_file

        tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        tmp.close()

        with pytest.raises(ValueError, match="File is empty"):
            validate_file(tmp.name, {"expected_type": "csv"})

        os.unlink(tmp.name)

    def test_validate_file_not_found(self):
        """validate_file should raise ValueError if file doesn't exist"""
        from app.wrkr_steps.validate import validate_file

        with pytest.raises(ValueError, match="File not found"):
            validate_file("/nonexistent/path/file.csv", {"expected_type": "csv"})


# ── Test 2 — Transform step ──────────────

class TestTransformStep:

    def test_transform_select_columns(self):
        """transform_file should keep only selected columns"""
        from app.wrkr_steps.transform import transform_file

        file_path = create_temp_csv([
            {"name": "John", "email": "john@example.com", "age": "25"},
            {"name": "Jane", "email": "jane@example.com", "age": "30"},
        ])
        output = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        output.close()

        transform_file(file_path, {"select_columns": ["name", "email"]}, output.name)

        with open(output.name) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert "name" in rows[0]
            assert "email" in rows[0]
            assert "age" not in rows[0]

        os.unlink(file_path)
        os.unlink(output.name)

    def test_transform_uppercase(self):
        """transform_file should uppercase specified column"""
        from app.wrkr_steps.transform import transform_file

        file_path = create_temp_csv([
            {"name": "john", "email": "john@example.com", "age": "25"},
        ])
        output = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        output.close()

        transform_file(file_path, {"apply": {"column": "name", "operation": "uppercase"}}, output.name)

        with open(output.name) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert rows[0]["name"] == "JOHN"

        os.unlink(file_path)
        os.unlink(output.name)

    def test_transform_filter(self):
        """transform_file should filter rows based on criteria"""
        from app.wrkr_steps.transform import transform_file

        file_path = create_temp_csv([
            {"name": "John", "email": "john@example.com", "age": "25"},
            {"name": "Jane", "email": "jane@example.com", "age": "17"},
        ])
        output = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        output.close()

        transform_file(file_path, {"filter": {"column": "age", "gt": 18}}, output.name)

        with open(output.name) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) == 1
            assert rows[0]["name"] == "John"

        os.unlink(file_path)
        os.unlink(output.name)


# ── Test 3 — Convert step ────────────────

class TestConvertStep:

    def test_convert_csv_to_json(self):
        """parse_and_convert should convert CSV to JSON correctly"""
        from app.wrkr_steps.convert import parse_and_convert

        file_path = create_temp_csv([
            {"name": "John", "email": "john@example.com", "age": "25"},
        ])
        output = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        output.close()

        parse_and_convert(file_path, {"output_format": "json"}, output.name)

        with open(output.name) as f:
            data = json.load(f)
            assert isinstance(data, list)
            assert len(data) == 1
            assert data[0]["name"] == "John"

        os.unlink(file_path)
        os.unlink(output.name)

    def test_convert_unsupported_format(self):
        """parse_and_convert should raise ValueError for unsupported format"""
        from app.wrkr_steps.convert import parse_and_convert

        file_path = create_temp_csv([
            {"name": "John", "email": "john@example.com", "age": "25"},
        ])
        output = tempfile.NamedTemporaryFile(suffix=".xml", delete=False)
        output.close()

        with pytest.raises(ValueError, match="Unsupported conversion"):
            parse_and_convert(file_path, {"output_format": "xml"}, output.name)

        os.unlink(file_path)
        os.unlink(output.name)


# ── Test 4 — Compress step ───────────────

class TestCompressStep:

    def test_compress_gzip(self):
        """compress_file should create a valid gzip file"""
        from app.wrkr_steps.comp_decomp_ops import compress_file
        import gzip

        file_path = create_temp_csv([
            {"name": "John", "email": "john@example.com", "age": "25"},
        ])
        output = tempfile.NamedTemporaryFile(suffix=".csv.gz", delete=False)
        output.close()

        compress_file(file_path, {"algorithm": "gzip"}, output.name)

        # verify the output is a valid gzip file
        with gzip.open(output.name, "rb") as f:
            content = f.read()
            assert len(content) > 0

        os.unlink(file_path)
        os.unlink(output.name)

    def test_compress_unsupported_algorithm(self):
        """compress_file should raise ValueError for unsupported algorithm"""
        from app.wrkr_steps.comp_decomp_ops import compress_file

        file_path = create_temp_csv([
            {"name": "John", "email": "john@example.com", "age": "25"},
        ])
        output = tempfile.NamedTemporaryFile(suffix=".bz2", delete=False)
        output.close()

        with pytest.raises(ValueError, match="Unsupported compression algorithm"):
            compress_file(file_path, {"algorithm": "bzip2"}, output.name)

        os.unlink(file_path)
        os.unlink(output.name)
