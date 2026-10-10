"""
Tests for engine/main.py — CLI entry-point and generation orchestration.

Covers:
  - _make_test_filename: test file naming convention
  - _build_header: generated file header creation
  - _build_conftest: conftest.py creation and idempotence
  - run: file existence checks, function filtering, pipeline execution with mock generator
  - CLI execution via subprocess
"""

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from engine.main import (
    _make_test_filename,
    _build_header,
    _build_conftest,
    run,
)


class TestHelpers:
    """Tests for main.py helper functions."""

    def test_make_test_filename(self):
        assert _make_test_filename("utils.py", "calculate_tax") == "test_utils_calculate_tax.py"
        assert _make_test_filename("path/to/models.py", "User") == "test_models_User.py"

    def test_build_header(self):
        header = _build_header("src/utils.py", "my_func")
        assert "Auto-generated test cases" in header
        assert "src/utils.py" in header
        assert "my_func" in header
        assert header.endswith("\n\n")

    def test_build_conftest_creates_file(self, tmp_path):
        out_dir = tmp_path / "generated_tests"
        out_dir.mkdir()
        _build_conftest(out_dir, tmp_path)

        conftest = out_dir / "conftest.py"
        assert conftest.exists()
        content = conftest.read_text(encoding="utf-8")
        assert "PROJECT_ROOT" in content
        assert "sys.path.insert" in content

    def test_build_conftest_does_not_overwrite(self, tmp_path):
        out_dir = tmp_path / "generated_tests"
        out_dir.mkdir()
        conftest = out_dir / "conftest.py"
        conftest.write_text("# custom conftest", encoding="utf-8")

        _build_conftest(out_dir, tmp_path)
        assert conftest.read_text(encoding="utf-8") == "# custom conftest"


class TestRunPipeline:
    """Tests for run() pipeline orchestration."""

    def test_nonexistent_source_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            run(str(tmp_path / "missing.py"), api_key="fake-key")

    def test_no_functions_raises(self, tmp_path):
        source = tmp_path / "empty.py"
        source.write_text("x = 10\ny = 20\n", encoding="utf-8")
        with pytest.raises(ValueError, match="No functions found"):
            run(str(source), api_key="fake-key")

    def test_named_function_not_found_raises(self, tmp_path):
        source = tmp_path / "sample.py"
        source.write_text("def hello(): pass\n", encoding="utf-8")
        with pytest.raises(ValueError, match="No function 'goodbye' found"):
            run(str(source), api_key="fake-key", function_name="goodbye")

    @patch("engine.main.generate_tests")
    def test_run_success_with_validation(self, mock_gen, tmp_path):
        source = tmp_path / "calc.py"
        source.write_text(
            "def add(a, b):\n    return a + b\n",
            encoding="utf-8",
        )
        mock_gen.return_value = textwrap.dedent("""\
            import pytest

            def test_add_positive():
                assert add(1, 2) == 3
        """)

        out_dir = tmp_path / "tests_out"
        result = run(
            file_path=str(source),
            api_key="test-key",
            output_dir=str(out_dir),
            validate=True,
        )

        assert result["total"] == 1
        assert result["success"] == 1
        assert result["failed"] == 0
        assert len(result["results"]) == 1
        assert result["results"][0]["status"] == "ok"
        assert result["results"][0]["test_count"] == 1

        test_file = Path(result["results"][0]["file"])
        assert test_file.exists()
        content = test_file.read_text(encoding="utf-8")
        assert "def test_add_positive" in content

    @patch("engine.main.generate_tests")
    def test_run_success_without_validation(self, mock_gen, tmp_path):
        """Verifies the bug fix: validate=False doesn't crash on validation scoping."""
        source = tmp_path / "calc.py"
        source.write_text(
            "def add(a, b):\n    return a + b\n",
            encoding="utf-8",
        )
        mock_gen.return_value = "def test_raw(): assert True\n"

        out_dir = tmp_path / "tests_out"
        result = run(
            file_path=str(source),
            api_key="test-key",
            output_dir=str(out_dir),
            validate=False,
        )

        assert result["success"] == 1
        assert result["results"][0]["test_count"] is None
        assert Path(result["results"][0]["file"]).exists()

    @patch("engine.main.generate_tests")
    def test_run_validation_retry_and_eventual_failure(self, mock_gen, tmp_path):
        source = tmp_path / "calc.py"
        source.write_text("def add(a, b): return a + b\n", encoding="utf-8")
        # Generates invalid syntax every time
        mock_gen.return_value = "def broken(:\n"

        out_dir = tmp_path / "tests_out"
        result = run(
            file_path=str(source),
            api_key="test-key",
            output_dir=str(out_dir),
            validate=True,
            max_retries=2,
        )

        assert result["success"] == 0
        assert result["failed"] == 1
        assert result["results"][0]["status"] == "error"
        assert mock_gen.call_count == 2


class TestMainCLI:
    """Tests for main.py command-line interface."""

    def test_cli_help(self):
        cmd = [sys.executable, "engine/main.py", "--help"]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        assert proc.returncode == 0
        assert "--file" in proc.stdout
        assert "--api-key" in proc.stdout

    def test_cli_missing_file_arg(self):
        cmd = [sys.executable, "engine/main.py"]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        assert proc.returncode != 0
        assert "required: --file" in proc.stderr or "the following arguments are required: --file" in proc.stderr
