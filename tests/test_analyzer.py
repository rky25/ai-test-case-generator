"""
Tests for engine/analyzer.py — AST-based Python source code analysis.

Covers:
  - extract_functions: top-level, class methods, async, filtering by name
  - extract_imports: import and from-import extraction
  - extract_file_context: module docstring, classes, constants
  - extract_cross_file_dependencies: local import resolution
  - detect_frameworks: framework detection from imports
  - discover_workspace_fixtures: fixture scanning
"""

import sys
import textwrap
from pathlib import Path

import pytest

# Ensure engine is importable
ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE_DIR))

from analyzer import (
    extract_functions,
    extract_imports,
    extract_file_context,
    extract_cross_file_dependencies,
    detect_frameworks,
    discover_workspace_fixtures,
)


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def sample_file(tmp_path):
    """Create a simple Python file for testing."""
    code = textwrap.dedent("""\
        \"\"\"Module docstring.\"\"\"

        import os
        from pathlib import Path

        MAX_RETRIES = 3
        BASE_URL = "https://example.com"

        def greet(name: str) -> str:
            \"\"\"Return a greeting.\"\"\"
            return f"Hello, {name}!"

        def add(a: int, b: int) -> int:
            return a + b

        async def fetch_data(url: str) -> dict:
            \"\"\"Fetch data asynchronously.\"\"\"
            pass

        class Calculator:
            \"\"\"A simple calculator.\"\"\"

            def multiply(self, a: float, b: float) -> float:
                return a * b

            def divide(self, a: float, b: float) -> float:
                \"\"\"Divide a by b.\"\"\"
                if b == 0:
                    raise ZeroDivisionError("Cannot divide by zero")
                return a / b

            def _private_method(self):
                pass
    """)
    filepath = tmp_path / "sample.py"
    filepath.write_text(code, encoding="utf-8")
    return filepath


@pytest.fixture
def sample_with_decorators(tmp_path):
    """Create a file with decorated functions."""
    code = textwrap.dedent("""\
        import functools

        def my_decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                return func(*args, **kwargs)
            return wrapper

        @my_decorator
        def decorated_func(x: int) -> int:
            return x * 2
    """)
    filepath = tmp_path / "decorated.py"
    filepath.write_text(code, encoding="utf-8")
    return filepath


@pytest.fixture
def empty_file(tmp_path):
    """Create an empty Python file."""
    filepath = tmp_path / "empty.py"
    filepath.write_text("", encoding="utf-8")
    return filepath


@pytest.fixture
def framework_file(tmp_path):
    """Create a file with framework imports."""
    code = textwrap.dedent("""\
        from fastapi import FastAPI
        from sqlalchemy import create_engine
        import redis
        from pydantic import BaseModel

        app = FastAPI()

        class Item(BaseModel):
            name: str
    """)
    filepath = tmp_path / "app.py"
    filepath.write_text(code, encoding="utf-8")
    return filepath


# ── extract_functions ─────────────────────────────────────────────


class TestExtractFunctions:
    """Tests for extract_functions()."""

    def test_extracts_all_top_level_functions(self, sample_file):
        """Should find all top-level functions."""
        funcs = extract_functions(str(sample_file))
        names = [f["name"] for f in funcs]
        assert "greet" in names
        assert "add" in names
        assert "fetch_data" in names

    def test_extracts_class_methods(self, sample_file):
        """Should find methods inside classes."""
        funcs = extract_functions(str(sample_file))
        names = [f["name"] for f in funcs]
        assert "multiply" in names
        assert "divide" in names
        assert "_private_method" in names

    def test_filter_by_function_name(self, sample_file):
        """Should return only the named function."""
        funcs = extract_functions(str(sample_file), function_name="greet")
        assert len(funcs) == 1
        assert funcs[0]["name"] == "greet"

    def test_filter_nonexistent_function(self, sample_file):
        """Should return empty list for nonexistent function."""
        funcs = extract_functions(str(sample_file), function_name="nonexistent")
        assert funcs == []

    def test_detects_async_functions(self, sample_file):
        """Should mark async functions correctly."""
        funcs = extract_functions(str(sample_file), function_name="fetch_data")
        assert len(funcs) == 1
        assert funcs[0]["is_async"] is True

    def test_sync_functions_not_marked_async(self, sample_file):
        """Regular functions should have is_async=False."""
        funcs = extract_functions(str(sample_file), function_name="greet")
        assert funcs[0]["is_async"] is False

    def test_extracts_arguments(self, sample_file):
        """Should extract argument names and type annotations."""
        funcs = extract_functions(str(sample_file), function_name="greet")
        args = funcs[0]["args"]
        assert len(args) == 1
        assert args[0]["name"] == "name"
        assert args[0]["annotation"] == "str"

    def test_extracts_return_type(self, sample_file):
        """Should extract return type annotation."""
        funcs = extract_functions(str(sample_file), function_name="greet")
        assert funcs[0]["return_type"] == "str"

    def test_extracts_docstring(self, sample_file):
        """Should extract the function docstring."""
        funcs = extract_functions(str(sample_file), function_name="greet")
        assert funcs[0]["docstring"] == "Return a greeting."

    def test_no_docstring_returns_none(self, sample_file):
        """Functions without docstrings should have docstring=None."""
        funcs = extract_functions(str(sample_file), function_name="add")
        assert funcs[0]["docstring"] is None

    def test_extracts_class_name_for_methods(self, sample_file):
        """Methods should have their class_name set."""
        funcs = extract_functions(str(sample_file), function_name="multiply")
        assert funcs[0]["class_name"] == "Calculator"

    def test_top_level_functions_have_no_class(self, sample_file):
        """Top-level functions should have class_name=None."""
        funcs = extract_functions(str(sample_file), function_name="greet")
        assert funcs[0]["class_name"] is None

    def test_extracts_decorators(self, sample_with_decorators):
        """Should extract decorator names."""
        funcs = extract_functions(str(sample_with_decorators), function_name="decorated_func")
        assert len(funcs) == 1
        assert "my_decorator" in funcs[0]["decorators"]

    def test_empty_file_returns_empty(self, empty_file):
        """Empty file should return no functions."""
        funcs = extract_functions(str(empty_file))
        assert funcs == []

    def test_extracts_body_source(self, sample_file):
        """Should include the function body as source code."""
        funcs = extract_functions(str(sample_file), function_name="greet")
        assert "def greet" in funcs[0]["body"]
        assert "Hello" in funcs[0]["body"]

    def test_extracts_line_numbers(self, sample_file):
        """Should include start and end line numbers."""
        funcs = extract_functions(str(sample_file), function_name="greet")
        assert "start_line" in funcs[0]
        assert "end_line" in funcs[0]
        assert funcs[0]["start_line"] > 0
        assert funcs[0]["end_line"] >= funcs[0]["start_line"]


# ── extract_imports ───────────────────────────────────────────────


class TestExtractImports:
    """Tests for extract_imports()."""

    def test_extracts_import_statements(self, sample_file):
        """Should extract 'import os' style imports."""
        imports = extract_imports(str(sample_file))
        assert any("import os" in i for i in imports)

    def test_extracts_from_imports(self, sample_file):
        """Should extract 'from X import Y' style imports."""
        imports = extract_imports(str(sample_file))
        assert any("from pathlib import Path" in i for i in imports)

    def test_empty_file_returns_empty(self, empty_file):
        """Empty file should return no imports."""
        imports = extract_imports(str(empty_file))
        assert imports == []


# ── extract_file_context ──────────────────────────────────────────


class TestExtractFileContext:
    """Tests for extract_file_context()."""

    def test_extracts_module_docstring(self, sample_file):
        """Should extract the module-level docstring."""
        ctx = extract_file_context(str(sample_file))
        assert ctx["module_docstring"] == "Module docstring."

    def test_extracts_class_info(self, sample_file):
        """Should list classes with names and docstrings."""
        ctx = extract_file_context(str(sample_file))
        assert len(ctx["classes"]) >= 1
        assert ctx["classes"][0]["name"] == "Calculator"
        assert ctx["classes"][0]["docstring"] == "A simple calculator."

    def test_extracts_global_constants(self, sample_file):
        """Should extract UPPERCASE global assignments."""
        ctx = extract_file_context(str(sample_file))
        constant_names = [c.split(" = ")[0] for c in ctx["constants"]]
        assert "MAX_RETRIES" in constant_names
        assert "BASE_URL" in constant_names

    def test_empty_file_context(self, empty_file):
        """Empty file should return empty context."""
        ctx = extract_file_context(str(empty_file))
        assert ctx["module_docstring"] is None
        assert ctx["classes"] == []
        assert ctx["constants"] == []


# ── detect_frameworks ─────────────────────────────────────────────


class TestDetectFrameworks:
    """Tests for detect_frameworks()."""

    def test_detects_fastapi(self, framework_file):
        """Should detect FastAPI from imports."""
        frameworks = detect_frameworks(str(framework_file))
        assert "fastapi" in frameworks

    def test_detects_sqlalchemy(self, framework_file):
        """Should detect SQLAlchemy from imports."""
        frameworks = detect_frameworks(str(framework_file))
        assert "sqlalchemy" in frameworks

    def test_detects_redis(self, framework_file):
        """Should detect Redis from imports."""
        frameworks = detect_frameworks(str(framework_file))
        assert "redis" in frameworks

    def test_detects_pydantic(self, framework_file):
        """Should detect Pydantic from imports."""
        frameworks = detect_frameworks(str(framework_file))
        assert "pydantic" in frameworks

    def test_no_frameworks_in_simple_file(self, sample_file):
        """File without framework imports should return empty list."""
        frameworks = detect_frameworks(str(sample_file))
        assert frameworks == []

    def test_returns_sorted_list(self, framework_file):
        """Frameworks should be returned in sorted order."""
        frameworks = detect_frameworks(str(framework_file))
        assert frameworks == sorted(frameworks)


# ── extract_cross_file_dependencies ───────────────────────────────


class TestExtractCrossFileDependencies:
    """Tests for extract_cross_file_dependencies()."""

    def test_resolves_local_function_import(self, tmp_path):
        """Should resolve a from-import of a function from a local file."""
        helper = tmp_path / "helpers.py"
        helper.write_text(
            textwrap.dedent("""\
                def compute(x: int) -> int:
                    \"\"\"Compute something.\"\"\"
                    return x * 2
            """),
            encoding="utf-8",
        )
        main_file = tmp_path / "main.py"
        main_file.write_text("from helpers import compute\n", encoding="utf-8")

        deps = extract_cross_file_dependencies(str(main_file), str(tmp_path))
        assert "compute" in deps
        assert deps["compute"]["type"] == "function"
        assert deps["compute"]["docstring"] == "Compute something."

    def test_resolves_local_class_import(self, tmp_path):
        """Should resolve class import with methods and init_args."""
        models = tmp_path / "models.py"
        models.write_text(
            textwrap.dedent("""\
                class User:
                    \"\"\"A user model.\"\"\"
                    def __init__(self, name: str, age: int):
                        self.name = name
                        self.age = age

                    def greet(self) -> str:
                        return f"Hi, {self.name}"
            """),
            encoding="utf-8",
        )
        main_file = tmp_path / "app.py"
        main_file.write_text("from models import User\n", encoding="utf-8")

        deps = extract_cross_file_dependencies(str(main_file), str(tmp_path))
        assert "User" in deps
        assert deps["User"]["type"] == "class"
        assert "name" in deps["User"]["init_args"]
        assert "age" in deps["User"]["init_args"]

    def test_ignores_stdlib_imports(self, sample_file, tmp_path):
        """Should not include stdlib modules as dependencies."""
        deps = extract_cross_file_dependencies(str(sample_file), str(tmp_path))
        assert "os" not in deps
        assert "pathlib" not in deps

    def test_empty_file_returns_empty(self, empty_file, tmp_path):
        """Empty file should return no dependencies."""
        deps = extract_cross_file_dependencies(str(empty_file), str(tmp_path))
        assert deps == {}


# ── discover_workspace_fixtures ───────────────────────────────────


class TestDiscoverWorkspaceFixtures:
    """Tests for discover_workspace_fixtures()."""

    def test_discovers_conftest_fixtures(self, tmp_path):
        """Should find @pytest.fixture functions in conftest.py."""
        conftest = tmp_path / "conftest.py"
        conftest.write_text(
            textwrap.dedent("""\
                import pytest

                @pytest.fixture
                def db_session():
                    \"\"\"Provide a test database session.\"\"\"
                    pass
            """),
            encoding="utf-8",
        )

        fixtures = discover_workspace_fixtures(str(tmp_path))
        assert len(fixtures) >= 1
        assert fixtures[0]["name"] == "db_session"
        assert fixtures[0]["docstring"] == "Provide a test database session."

    def test_empty_project_returns_empty(self, tmp_path):
        """Project with no conftest should return empty list."""
        fixtures = discover_workspace_fixtures(str(tmp_path))
        assert fixtures == []
