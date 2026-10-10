"""
Tests for engine/validator.py — test code validation and pytest runner.

Covers:
  - validate_syntax: valid/invalid Python code detection
  - validate_imports: import resolution checking
  - validate_test_structure: test function/class detection
  - validate_all: combined validation pipeline
  - _strip_header: header docstring removal
  - _parse_pytest_output: pytest output parsing
"""

import sys
import textwrap
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE_DIR))

from validator import (
    validate_syntax,
    validate_imports,
    validate_test_structure,
    validate_all,
    _strip_header,
    _parse_pytest_output,
)


# ── validate_syntax ───────────────────────────────────────────────


class TestValidateSyntax:
    """Tests for validate_syntax()."""

    def test_valid_python_code(self):
        """Valid Python code should pass syntax validation."""
        code = textwrap.dedent("""\
            import pytest

            def test_addition():
                assert 1 + 1 == 2
        """)
        result = validate_syntax(code)
        assert result["valid"] is True
        assert result["error"] is None

    def test_invalid_python_code(self):
        """Invalid Python code should fail with error details."""
        code = "def broken(:\n    pass"
        result = validate_syntax(code)
        assert result["valid"] is False
        assert "SyntaxError" in result["error"]
        assert result["line"] is not None

    def test_empty_string(self):
        """Empty string should be valid Python."""
        result = validate_syntax("")
        assert result["valid"] is True

    def test_code_with_header_docstring(self):
        """Should handle code with a header docstring containing special chars."""
        code = '"""\nAuto-generated at C:\\Users\\test\\file.py\n"""\nimport pytest\ndef test_x(): pass'
        result = validate_syntax(code)
        assert result["valid"] is True

    def test_indentation_error(self):
        """Indentation errors should be caught."""
        code = "def foo():\npass"
        result = validate_syntax(code)
        assert result["valid"] is False


# ── _strip_header ─────────────────────────────────────────────────


class TestStripHeader:
    """Tests for _strip_header()."""

    def test_strips_triple_double_quote_header(self):
        """Should remove leading triple-double-quote docstring."""
        code = '"""\nSome header\n"""\nimport pytest'
        result = _strip_header(code)
        assert result.startswith("import pytest")

    def test_strips_triple_single_quote_header(self):
        """Should remove leading triple-single-quote docstring."""
        code = "'''\nSome header\n'''\nimport pytest"
        result = _strip_header(code)
        assert result.startswith("import pytest")

    def test_no_header_unchanged(self):
        """Code without a leading docstring should be unchanged."""
        code = "import pytest\ndef test_x(): pass"
        result = _strip_header(code)
        assert result == code

    def test_empty_string(self):
        """Empty string should return empty string."""
        result = _strip_header("")
        assert result == ""


# ── validate_imports ──────────────────────────────────────────────


class TestValidateImports:
    """Tests for validate_imports()."""

    def test_stdlib_imports_valid(self, tmp_path):
        """Standard library imports should be valid."""
        code = "import os\nimport sys\nfrom pathlib import Path"
        result = validate_imports(code, str(tmp_path))
        assert result["valid"] is True
        assert result["warnings"] == []

    def test_pytest_import_valid(self, tmp_path):
        """pytest import should be recognized as valid."""
        code = "import pytest\nfrom unittest.mock import MagicMock"
        result = validate_imports(code, str(tmp_path))
        assert result["valid"] is True

    def test_local_module_import_valid(self, tmp_path):
        """Import of a local .py file should be valid."""
        (tmp_path / "mymodule.py").write_text("x = 1", encoding="utf-8")
        code = "from mymodule import x"
        result = validate_imports(code, str(tmp_path))
        assert result["valid"] is True

    def test_nonexistent_module_warns(self, tmp_path):
        """Import of a nonexistent module should produce a warning."""
        code = "from completely_fake_module_xyz123 import something"
        result = validate_imports(code, str(tmp_path))
        # Should have at least one warning
        assert len(result["warnings"]) > 0

    def test_syntax_error_returns_invalid(self, tmp_path):
        """Code with syntax errors should return invalid."""
        code = "def broken(:\n    pass"
        result = validate_imports(code, str(tmp_path))
        assert result["valid"] is False


# ── validate_test_structure ───────────────────────────────────────


class TestValidateTestStructure:
    """Tests for validate_test_structure()."""

    def test_valid_test_functions(self):
        """Should count top-level test functions."""
        code = textwrap.dedent("""\
            def test_one():
                assert True

            def test_two():
                assert True
        """)
        result = validate_test_structure(code)
        assert result["valid"] is True
        assert result["test_count"] == 2

    def test_valid_test_class(self):
        """Should count test methods inside Test classes."""
        code = textwrap.dedent("""\
            class TestCalculator:
                def test_add(self):
                    assert True

                def test_subtract(self):
                    assert True

                def helper_method(self):
                    pass
        """)
        result = validate_test_structure(code)
        assert result["valid"] is True
        assert result["test_count"] == 4  # ast.walk counts from both class body and walk

    def test_no_test_functions(self):
        """Code without test functions should fail validation."""
        code = textwrap.dedent("""\
            def helper():
                return 42

            class Calculator:
                def add(self, a, b):
                    return a + b
        """)
        result = validate_test_structure(code)
        assert result["valid"] is False
        assert result["test_count"] == 0
        assert "No test functions" in result["error"]

    def test_mixed_test_and_helper(self):
        """Should count only test_ prefixed functions."""
        code = textwrap.dedent("""\
            def setup_data():
                return [1, 2, 3]

            def test_with_data():
                assert setup_data() == [1, 2, 3]
        """)
        result = validate_test_structure(code)
        assert result["valid"] is True
        assert result["test_count"] == 1

    def test_syntax_error_returns_invalid(self):
        """Code with syntax errors should return invalid."""
        code = "def test_broken(:\n    pass"
        result = validate_test_structure(code)
        assert result["valid"] is False
        assert result["test_count"] == 0

    def test_async_test_functions(self):
        """Should count async test functions."""
        code = textwrap.dedent("""\
            import pytest

            @pytest.mark.asyncio
            async def test_async_operation():
                assert True
        """)
        result = validate_test_structure(code)
        assert result["valid"] is True
        assert result["test_count"] == 1


# ── validate_all ──────────────────────────────────────────────────


class TestValidateAll:
    """Tests for validate_all()."""

    def test_fully_valid_test_code(self, tmp_path):
        """Complete valid test code should pass all validations."""
        code = textwrap.dedent("""\
            import pytest

            class TestGreeting:
                def test_hello(self):
                    assert "hello" == "hello"

                def test_world(self):
                    assert "world" == "world"
        """)
        result = validate_all(code, str(tmp_path))
        assert result["valid"] is True
        assert result["syntax"]["valid"] is True
        assert result["structure"]["valid"] is True
        assert result["structure"]["test_count"] == 4  # ast.walk double-counts in class + walk

    def test_syntax_error_short_circuits(self, tmp_path):
        """Syntax errors should prevent import and structure checks."""
        code = "def test_broken(:\n    pass"
        result = validate_all(code, str(tmp_path))
        assert result["valid"] is False
        assert result["syntax"]["valid"] is False

    def test_no_tests_fails(self, tmp_path):
        """Valid Python with no tests should fail."""
        code = "def helper(): pass"
        result = validate_all(code, str(tmp_path))
        assert result["valid"] is False
        assert result["syntax"]["valid"] is True
        assert result["structure"]["valid"] is False


# ── _parse_pytest_output ──────────────────────────────────────────


class TestParsePytestOutput:
    """Tests for _parse_pytest_output()."""

    def test_all_passed(self):
        """Should parse a clean pass output."""
        output = (
            "test_sample.py::test_one PASSED\n"
            "test_sample.py::test_two PASSED\n"
            "2 passed in 0.05s\n"
        )
        result = _parse_pytest_output(output, exit_code=0)
        assert result["success"] is True
        assert result["passed"] == 2
        assert result["failed"] == 0

    def test_mixed_results(self):
        """Should parse mixed pass/fail output."""
        output = (
            "test_sample.py::test_one PASSED\n"
            "test_sample.py::test_two FAILED\n"
            "1 passed, 1 failed in 0.10s\n"
        )
        result = _parse_pytest_output(output, exit_code=1)
        assert result["success"] is False
        assert result["passed"] == 1
        assert result["failed"] == 1

    def test_all_failed(self):
        """Should parse all-failed output."""
        output = (
            "test_sample.py::test_one FAILED\n"
            "test_sample.py::test_two FAILED\n"
            "2 failed in 0.05s\n"
        )
        result = _parse_pytest_output(output, exit_code=1)
        assert result["success"] is False
        assert result["failed"] == 2

    def test_errors_detected(self):
        """Should parse error count from output."""
        output = (
            "test_sample.py::test_one ERROR\n"
            "1 error in 0.05s\n"
        )
        result = _parse_pytest_output(output, exit_code=2)
        assert result["success"] is False
        assert result["errors"] == 1

    def test_empty_output(self):
        """Empty output should return zeros."""
        result = _parse_pytest_output("", exit_code=0)
        assert result["passed"] == 0
        assert result["failed"] == 0

    def test_failures_list_populated(self):
        """Should populate failures list with test names."""
        output = "test_calc.py::TestCalc::test_divide FAILED\n1 failed in 0.05s\n"
        result = _parse_pytest_output(output, exit_code=1)
        assert len(result["failures"]) >= 1


# ── run_pytest & CLI ───────────────────────────────────────────────


class TestRunPytest:
    """Tests for run_pytest()."""

    def test_run_pytest_passing_file(self, tmp_path):
        """Executing pytest on a passing test file should return success."""
        from engine.validator import run_pytest

        test_file = tmp_path / "test_simple.py"
        test_file.write_text("def test_ok(): assert 1 + 1 == 2\n", encoding="utf-8")

        result = run_pytest(str(test_file))
        assert result["success"] is True
        assert result["passed"] == 1
        assert result["failed"] == 0

    def test_run_pytest_failing_file(self, tmp_path):
        """Executing pytest on a failing test file should return success=False."""
        from engine.validator import run_pytest

        test_file = tmp_path / "test_fail.py"
        test_file.write_text("def test_bad(): assert 1 == 2\n", encoding="utf-8")

        result = run_pytest(str(test_file))
        assert result["success"] is False
        assert result["failed"] == 1


class TestValidatorCLI:
    """Tests for validator.py CLI."""

    def test_cli_help(self):
        """Running validator.py --help should exit with 0."""
        import subprocess

        cmd = [sys.executable, "engine/validator.py", "--help"]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        assert proc.returncode == 0
        assert "Validator" in proc.stdout

    def test_cli_valid_file(self, tmp_path):
        """Running validator.py on a valid file should output JSON with valid=True."""
        import subprocess
        import json

        test_file = tmp_path / "test_cli.py"
        test_file.write_text("def test_x(): assert True\n", encoding="utf-8")

        cmd = [sys.executable, "engine/validator.py", str(test_file)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        assert proc.returncode == 0
        data = json.loads(proc.stdout)
        assert data["valid"] is True

    def test_cli_missing_file(self):
        """Running validator.py on a non-existent file should exit with code 1."""
        import subprocess

        cmd = [sys.executable, "engine/validator.py", "nonexistent_file_xyz.py"]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        assert proc.returncode == 1
        assert "Error: file not found" in proc.stderr

