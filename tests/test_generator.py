"""
Tests for engine/generator.py — prompt building and response cleaning.

Covers:
  - build_prompt: message construction with all context types
  - clean_response: markdown fence removal, control token stripping
  - parse_api_keys: single and multi-key parsing
  - call_api_with_fallback: fallback behavior (mocked)
"""

import sys
import textwrap
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE_DIR))

from generator import (
    build_prompt,
    clean_response,
    parse_api_keys,
    call_api_with_fallback,
    SYSTEM_PROMPT,
)


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def simple_func_info():
    """Minimal function info dict."""
    return {
        "name": "add",
        "args": [
            {"name": "a", "annotation": "int"},
            {"name": "b", "annotation": "int"},
        ],
        "return_type": "int",
        "docstring": "Add two numbers.",
        "body": "def add(a: int, b: int) -> int:\n    return a + b",
        "decorators": [],
        "is_async": False,
        "class_name": None,
        "class_source": None,
        "start_line": 1,
        "end_line": 2,
    }


@pytest.fixture
def async_func_info():
    """Async function info dict."""
    return {
        "name": "fetch",
        "args": [{"name": "url", "annotation": "str"}],
        "return_type": "dict",
        "docstring": "Fetch data.",
        "body": "async def fetch(url: str) -> dict:\n    pass",
        "decorators": [],
        "is_async": True,
        "class_name": None,
        "class_source": None,
        "start_line": 1,
        "end_line": 2,
    }


@pytest.fixture
def class_method_info():
    """Class method info dict."""
    return {
        "name": "multiply",
        "args": [
            {"name": "self", "annotation": None},
            {"name": "a", "annotation": "float"},
            {"name": "b", "annotation": "float"},
        ],
        "return_type": "float",
        "docstring": "Multiply two numbers.",
        "body": "def multiply(self, a: float, b: float) -> float:\n    return a * b",
        "decorators": [],
        "is_async": False,
        "class_name": "Calculator",
        "class_source": "class Calculator:\n    def multiply(self, a, b):\n        return a * b",
        "start_line": 3,
        "end_line": 4,
    }


# ── build_prompt ──────────────────────────────────────────────────


class TestBuildPrompt:
    """Tests for build_prompt()."""

    def test_returns_system_and_user_messages(self, simple_func_info):
        """Should return exactly 2 messages: system and user."""
        messages = build_prompt(simple_func_info, [], "test.py")
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_system_prompt_is_standard(self, simple_func_info):
        """System prompt should be the predefined SYSTEM_PROMPT."""
        messages = build_prompt(simple_func_info, [], "test.py")
        assert messages[0]["content"] == SYSTEM_PROMPT

    def test_user_message_includes_function_code(self, simple_func_info):
        """User message should contain the function source code."""
        messages = build_prompt(simple_func_info, [], "test.py")
        assert "def add" in messages[1]["content"]

    def test_includes_filename(self, simple_func_info):
        """Should mention the source filename."""
        messages = build_prompt(simple_func_info, [], "mymodule.py")
        assert "mymodule.py" in messages[1]["content"]

    def test_includes_imports(self, simple_func_info):
        """Should include file-level imports."""
        messages = build_prompt(
            simple_func_info, ["import os", "from pathlib import Path"], "test.py"
        )
        content = messages[1]["content"]
        assert "import os" in content
        assert "from pathlib import Path" in content

    def test_includes_file_context(self, simple_func_info):
        """Should include module docstring and constants."""
        context = {
            "module_docstring": "A utility module.",
            "constants": ["MAX_SIZE = 100"],
            "classes": [],
        }
        messages = build_prompt(
            simple_func_info, [], "test.py", file_context=context
        )
        content = messages[1]["content"]
        assert "A utility module." in content
        assert "MAX_SIZE" in content

    def test_includes_dependency_info(self, simple_func_info):
        """Should include cross-file dependency information."""
        deps = {
            "User": {
                "type": "class",
                "source_file": "models.py",
                "bases": [],
                "docstring": "A user model",
                "init_args": ["name", "age"],
                "methods": [{"name": "greet", "args": ["self"], "return_type": "str", "docstring": None}],
            }
        }
        messages = build_prompt(
            simple_func_info, [], "test.py", dependencies=deps
        )
        content = messages[1]["content"]
        assert "User" in content
        assert "models.py" in content

    def test_includes_framework_guidelines(self, simple_func_info):
        """Should add framework-specific instructions."""
        messages = build_prompt(
            simple_func_info, [], "test.py", frameworks=["fastapi", "sqlalchemy"]
        )
        content = messages[1]["content"]
        assert "FastAPI" in content
        assert "SQLAlchemy" in content

    def test_includes_fixture_info(self, simple_func_info):
        """Should reference existing workspace fixtures."""
        fixtures = [{"name": "db", "file": "conftest.py", "args": [], "docstring": "DB fixture"}]
        messages = build_prompt(
            simple_func_info, [], "test.py", fixtures=fixtures
        )
        assert "db" in messages[1]["content"]

    def test_async_function_note(self, async_func_info):
        """Should add async note for async functions."""
        messages = build_prompt(async_func_info, [], "test.py")
        content = messages[1]["content"]
        assert "ASYNC" in content or "async" in content.lower()

    def test_class_method_includes_class_info(self, class_method_info):
        """Should include class name and source for methods."""
        messages = build_prompt(class_method_info, [], "test.py")
        content = messages[1]["content"]
        assert "Calculator" in content

    def test_includes_docstring(self, simple_func_info):
        """Should include function docstring."""
        messages = build_prompt(simple_func_info, [], "test.py")
        assert "Add two numbers." in messages[1]["content"]


# ── clean_response ────────────────────────────────────────────────


class TestCleanResponse:
    """Tests for clean_response()."""

    def test_removes_python_code_fence(self):
        """Should strip ```python ... ``` wrapper."""
        raw = '```python\nimport pytest\ndef test_x(): pass\n```'
        result = clean_response(raw)
        assert result.startswith("import pytest")
        assert "```" not in result

    def test_removes_generic_code_fence(self):
        """Should strip ``` ... ``` wrapper without language."""
        raw = '```\nimport pytest\ndef test_x(): pass\n```'
        result = clean_response(raw)
        assert "```" not in result

    def test_strips_whitespace(self):
        """Should strip leading/trailing whitespace."""
        raw = "  \n\nimport pytest\n\n  "
        result = clean_response(raw)
        assert result == "import pytest"

    def test_removes_ctrl_tokens(self):
        """Should remove model control tokens like <ctrl63>."""
        raw = "<ctrl63>import pytest\ndef test_x(): pass<ctrl0>"
        result = clean_response(raw)
        assert "<ctrl" not in result
        assert "import pytest" in result

    def test_plain_code_unchanged(self):
        """Code without fences should pass through unchanged (after strip)."""
        raw = "import pytest\ndef test_x(): pass"
        result = clean_response(raw)
        assert result == raw


# ── parse_api_keys ────────────────────────────────────────────────


class TestParseApiKeys:
    """Tests for parse_api_keys()."""

    def test_single_key(self):
        """Should return a list with one key."""
        keys = parse_api_keys("sk-abc123")
        assert keys == ["sk-abc123"]

    def test_multiple_keys(self):
        """Should split comma-separated keys."""
        keys = parse_api_keys("key1,key2,key3")
        assert keys == ["key1", "key2", "key3"]

    def test_strips_whitespace(self):
        """Should strip whitespace from keys."""
        keys = parse_api_keys("  key1 , key2  ")
        assert keys == ["key1", "key2"]

    def test_ignores_empty_segments(self):
        """Should filter out empty segments."""
        keys = parse_api_keys("key1,,key2,")
        assert keys == ["key1", "key2"]

    def test_empty_string_raises(self):
        """Should raise ValueError for empty input."""
        with pytest.raises(ValueError, match="No valid API keys"):
            parse_api_keys("")

    def test_only_commas_raises(self):
        """Should raise ValueError for comma-only input."""
        with pytest.raises(ValueError, match="No valid API keys"):
            parse_api_keys(",,,")


# ── call_api_with_fallback ────────────────────────────────────────


class TestCallApiWithFallback:
    """Tests for call_api_with_fallback() with mocked HTTP calls."""

    @patch("generator.call_api")
    def test_first_key_succeeds(self, mock_call):
        """Should use the first key and not try the second."""
        mock_call.return_value = "test code"
        result = call_api_with_fallback(
            ["key1", "key2"], "http://api.test", "model-x", []
        )
        assert result == "test code"
        assert mock_call.call_count == 1

    @patch("generator.call_api")
    def test_falls_back_to_second_key(self, mock_call):
        """Should fall back to second key when first fails."""
        mock_call.side_effect = [
            RuntimeError("API returned HTTP 429"),
            RuntimeError("API returned HTTP 429"),
            "test code from fallback",
        ]
        result = call_api_with_fallback(
            ["key1", "key2"], "http://api.test", "model-x", []
        )
        assert result == "test code from fallback"

    @patch("generator.call_api")
    def test_all_keys_fail_raises(self, mock_call):
        """Should raise RuntimeError when all keys are exhausted."""
        mock_call.side_effect = RuntimeError("API error")
        with pytest.raises(RuntimeError, match="All 2 API key"):
            call_api_with_fallback(
                ["key1", "key2"], "http://api.test", "model-x", []
            )
