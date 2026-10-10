"""
Tests for engine/scanner.py — project-wide test generation scanning.

Covers:
  - load_config: default config and .testgenrc.json merging
  - discover_python_files: include/exclude pattern matching
  - find_existing_tests: detection of already-generated test files
"""

import json
import sys
import textwrap
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE_DIR))

from scanner import (
    load_config,
    discover_python_files,
    find_existing_tests,
)


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def project_dir(tmp_path):
    """Create a mock project directory structure."""
    # Source files
    (tmp_path / "app.py").write_text("def main(): pass", encoding="utf-8")
    (tmp_path / "utils.py").write_text("def helper(): pass", encoding="utf-8")

    # Nested source
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "core.py").write_text("def process(): pass", encoding="utf-8")
    (tmp_path / "lib" / "__init__.py").write_text("", encoding="utf-8")

    # Files that should be excluded
    (tmp_path / "venv").mkdir()
    (tmp_path / "venv" / "pip.py").write_text("# pip", encoding="utf-8")

    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "app.cpython-311.pyc").write_text("", encoding="utf-8")

    (tmp_path / "test_app.py").write_text("def test_main(): pass", encoding="utf-8")

    (tmp_path / "generated_tests").mkdir()
    (tmp_path / "generated_tests" / "test_app_main.py").write_text(
        "def test_main(): pass", encoding="utf-8"
    )

    return tmp_path


# ── load_config ───────────────────────────────────────────────────


class TestLoadConfig:
    """Tests for load_config()."""

    def test_returns_defaults_without_config_file(self, tmp_path):
        """Should return sensible defaults when no .testgenrc.json exists."""
        config = load_config(str(tmp_path))
        assert config["testFramework"] == "pytest"
        assert config["model"] == "gemini-2.5-flash"
        assert config["maxTestsPerFunction"] == 15
        assert config["skipPrivate"] is True
        assert config["skipDunder"] is True
        assert config["validateBeforeSave"] is True
        assert isinstance(config["include"], list)
        assert isinstance(config["exclude"], list)

    def test_merges_user_config(self, tmp_path):
        """Should merge user config on top of defaults."""
        user_config = {
            "model": "gpt-4o",
            "maxTestsPerFunction": 25,
            "skipPrivate": False,
        }
        config_path = tmp_path / ".testgenrc.json"
        config_path.write_text(json.dumps(user_config), encoding="utf-8")

        config = load_config(str(tmp_path))
        assert config["model"] == "gpt-4o"
        assert config["maxTestsPerFunction"] == 25
        assert config["skipPrivate"] is False
        # Defaults should still be present for unset keys
        assert config["testFramework"] == "pytest"
        assert config["skipDunder"] is True

    def test_merges_nested_style_config(self, tmp_path):
        """Should shallow-merge nested objects like 'style'."""
        user_config = {
            "style": {
                "useFixtures": False,
            }
        }
        config_path = tmp_path / ".testgenrc.json"
        config_path.write_text(json.dumps(user_config), encoding="utf-8")

        config = load_config(str(tmp_path))
        assert config["style"]["useFixtures"] is False
        # Other style defaults should remain
        assert config["style"]["useParametrize"] is True

    def test_invalid_json_falls_back_to_defaults(self, tmp_path):
        """Should use defaults if .testgenrc.json is invalid JSON."""
        config_path = tmp_path / ".testgenrc.json"
        config_path.write_text("{invalid json", encoding="utf-8")

        config = load_config(str(tmp_path))
        assert config["testFramework"] == "pytest"
        assert config["model"] == "gemini-2.5-flash"


# ── discover_python_files ─────────────────────────────────────────


class TestDiscoverPythonFiles:
    """Tests for discover_python_files()."""

    def test_finds_python_files(self, project_dir):
        """Should find .py files matching include patterns."""
        files = discover_python_files(
            str(project_dir),
            include_patterns=["**/*.py"],
            exclude_patterns=[],
        )
        basenames = [Path(f).name for f in files]
        assert "app.py" in basenames
        assert "utils.py" in basenames
        assert "core.py" in basenames

    def test_excludes_venv(self, project_dir):
        """Should exclude venv/ files."""
        files = discover_python_files(
            str(project_dir),
            include_patterns=["**/*.py"],
            exclude_patterns=["**/venv/**"],
        )
        # Check that no file is under the project's venv directory
        venv_dir = str(project_dir / "venv")
        for f in files:
            assert not f.startswith(venv_dir), f"Expected {f} to be excluded (venv)"

    def test_excludes_test_files(self, project_dir):
        """Should exclude test_*.py files."""
        files = discover_python_files(
            str(project_dir),
            include_patterns=["**/*.py"],
            exclude_patterns=["**/test_*.py"],
        )
        basenames = [Path(f).name for f in files]
        assert "test_app.py" not in basenames

    def test_excludes_generated_tests(self, project_dir):
        """Should exclude generated_tests/ directory."""
        files = discover_python_files(
            str(project_dir),
            include_patterns=["**/*.py"],
            exclude_patterns=["**/generated_tests/**"],
        )
        gen_dir = str(project_dir / "generated_tests")
        for f in files:
            assert not f.startswith(gen_dir), f"Expected {f} to be excluded (generated_tests)"

    def test_excludes_pycache(self, project_dir):
        """Should exclude __pycache__/ directory."""
        files = discover_python_files(
            str(project_dir),
            include_patterns=["**/*.py"],
            exclude_patterns=["**/__pycache__/**"],
        )
        for f in files:
            assert "__pycache__" not in f

    def test_multiple_exclude_patterns(self, project_dir):
        """Should apply all exclude patterns."""
        files = discover_python_files(
            str(project_dir),
            include_patterns=["**/*.py"],
            exclude_patterns=[
                "**/venv/**",
                "**/test_*.py",
                "**/generated_tests/**",
                "**/__pycache__/**",
            ],
        )
        for f in files:
            assert "venv" not in f
            assert "generated_tests" not in f
            assert "__pycache__" not in f
        basenames = [Path(f).name for f in files]
        assert "test_app.py" not in basenames

    def test_empty_directory_returns_empty(self, tmp_path):
        """Empty directory should return no files."""
        files = discover_python_files(
            str(tmp_path),
            include_patterns=["**/*.py"],
            exclude_patterns=[],
        )
        assert files == []


# ── find_existing_tests ───────────────────────────────────────────


class TestFindExistingTests:
    """Tests for find_existing_tests()."""

    def test_finds_existing_test_files(self, tmp_path):
        """Should identify (source_stem, function_name) pairs from test files."""
        test_dir = tmp_path / "generated_tests"
        test_dir.mkdir()
        (test_dir / "test_app_main.py").write_text("def test_main(): pass", encoding="utf-8")
        (test_dir / "test_utils_helper.py").write_text("def test_helper(): pass", encoding="utf-8")

        existing = find_existing_tests(str(test_dir))
        assert ("app", "main") in existing
        assert ("utils", "helper") in existing

    def test_nonexistent_directory_returns_empty(self, tmp_path):
        """Non-existent directory should return empty set."""
        existing = find_existing_tests(str(tmp_path / "nonexistent"))
        assert existing == set()

    def test_empty_directory_returns_empty(self, tmp_path):
        """Empty directory should return empty set."""
        test_dir = tmp_path / "generated_tests"
        test_dir.mkdir()
        existing = find_existing_tests(str(test_dir))
        assert existing == set()

    def test_ignores_non_test_files(self, tmp_path):
        """Should ignore files that don't match test_*.py pattern."""
        test_dir = tmp_path / "generated_tests"
        test_dir.mkdir()
        (test_dir / "conftest.py").write_text("# conftest", encoding="utf-8")
        (test_dir / "helper.py").write_text("# helper", encoding="utf-8")

        existing = find_existing_tests(str(test_dir))
        assert existing == set()
