"""
Test code validator and runner.

Validates generated test code for:
  1. Python syntax (AST parsing)
  2. Import correctness
  3. Optionally runs pytest and returns pass/fail results

Supports a self-healing loop: if tests fail validation,
the AI is re-prompted with error context to fix them.
"""

import argparse
import ast
import json
import subprocess
import sys
import os
from pathlib import Path
from typing import Optional


def _strip_header(code: str) -> str:
    """
    Remove the auto-generated header docstring that may contain
    Windows backslash paths (which cause ast.parse unicode errors).
    """
    stripped = code.strip()
    for quote in ('"""', "'''"):
        if stripped.startswith(quote):
            end = stripped.find(quote, 3)
            if end != -1:
                return stripped[end + 3:].strip()
    return stripped


def validate_syntax(code: str) -> dict:
    """
    Check that generated test code is valid Python.

    Returns:
        {"valid": True} or {"valid": False, "error": "...", "line": N}
    """
    clean = _strip_header(code)
    try:
        ast.parse(clean)
        return {"valid": True, "error": None, "line": None}
    except SyntaxError as exc:
        return {
            "valid": False,
            "error": f"SyntaxError: {exc.msg}",
            "line": exc.lineno,
        }


def validate_imports(code: str, source_dir: str) -> dict:
    """
    Check that import statements reference modules that likely exist.
    Flags obvious hallucinated imports (modules not in stdlib or project).

    Returns:
        {"valid": True, "warnings": [...]}
    """
    warnings = []
    clean = _strip_header(code)

    try:
        tree = ast.parse(clean)
    except SyntaxError:
        return {"valid": False, "warnings": ["Code has syntax errors, cannot check imports"]}

    known_test_modules = {
        "pytest", "unittest", "mock", "unittest.mock",
        "hypothesis", "faker", "factory", "freezegun",
    }

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                # Skip known test and stdlib modules
                if top in known_test_modules:
                    continue
                # Check if it's a local module
                local_path = Path(source_dir) / f"{top}.py"
                local_pkg = Path(source_dir) / top / "__init__.py"
                if not local_path.exists() and not local_pkg.exists():
                    try:
                        __import__(top)
                    except ImportError:
                        warnings.append(
                            f"Import '{alias.name}' may not resolve "
                            f"(not found in project or stdlib)"
                        )

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".")[0]
                if top in known_test_modules:
                    continue
                local_path = Path(source_dir) / f"{top}.py"
                local_pkg = Path(source_dir) / top / "__init__.py"
                if not local_path.exists() and not local_pkg.exists():
                    try:
                        __import__(top)
                    except ImportError:
                        warnings.append(
                            f"Import 'from {node.module}' may not resolve "
                            f"(not found in project or stdlib)"
                        )

    return {"valid": len(warnings) == 0, "warnings": warnings}


def validate_test_structure(code: str) -> dict:
    """
    Verify the generated code contains actual test classes/functions.

    Returns:
        {"valid": True, "test_count": N} or {"valid": False, "error": "..."}
    """
    clean = _strip_header(code)
    try:
        tree = ast.parse(clean)
    except SyntaxError:
        return {"valid": False, "test_count": 0, "error": "Syntax error"}

    test_count = 0

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                test_count += 1
        elif isinstance(node, ast.ClassDef):
            if node.name.startswith("Test"):
                # Count methods inside test classes
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if item.name.startswith("test_"):
                            test_count += 1

    if test_count == 0:
        return {
            "valid": False,
            "test_count": 0,
            "error": "No test functions found (expected functions starting with 'test_')",
        }

    return {"valid": True, "test_count": test_count, "error": None}


def validate_all(code: str, source_dir: str) -> dict:
    """
    Run all validations and return a combined result.

    Returns:
        {
            "valid": bool,
            "syntax": {...},
            "imports": {...},
            "structure": {...},
        }
    """
    syntax = validate_syntax(code)
    imports = validate_imports(code, source_dir) if syntax["valid"] else {"valid": False, "warnings": []}
    structure = validate_test_structure(code) if syntax["valid"] else {"valid": False, "test_count": 0, "error": "Syntax error"}

    overall = syntax["valid"] and structure["valid"]

    return {
        "valid": overall,
        "syntax": syntax,
        "imports": imports,
        "structure": structure,
    }


def run_pytest(
    test_file: str,
    python_path: str = "python",
    timeout: int = 60,
) -> dict:
    """
    Execute pytest on a single test file and return structured results.

    Args:
        test_file:   absolute path to the test file
        python_path: path to the Python interpreter
        timeout:     seconds before killing the process

    Returns:
        {
            "success": bool,
            "passed": N,
            "failed": N,
            "errors": N,
            "total": N,
            "output": "...",
            "failures": [{"test": "...", "message": "..."}]
        }
    """
    if python_path == "python" and sys.executable:
        python_path = sys.executable

    test_path = Path(test_file).resolve()
    test_dir = test_path.parent

    cmd = [
        python_path, "-m", "pytest",
        str(test_path),
        "-v",
        "--tb=short",
        "--no-header",
        "-q",
        "--json-report",
        "--json-report-file=-",
    ]

    # Fallback: try without json-report plugin
    cmd_simple = [
        python_path, "-m", "pytest",
        str(test_path),
        "-v",
        "--tb=short",
        "--no-header",
    ]

    try:
        result = subprocess.run(
            cmd_simple,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(test_dir),
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )

        output = result.stdout + result.stderr
        return _parse_pytest_output(output, result.returncode)

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "passed": 0,
            "failed": 0,
            "errors": 1,
            "total": 0,
            "output": f"pytest timed out after {timeout}s",
            "failures": [{"test": "TIMEOUT", "message": f"Tests exceeded {timeout}s limit"}],
        }
    except FileNotFoundError:
        return {
            "success": False,
            "passed": 0,
            "failed": 0,
            "errors": 1,
            "total": 0,
            "output": f"pytest not found. Install it: {python_path} -m pip install pytest",
            "failures": [{"test": "SETUP", "message": "pytest is not installed"}],
        }


def _parse_pytest_output(output: str, exit_code: int) -> dict:
    """Parse pytest verbose output to extract pass/fail counts."""
    passed = 0
    failed = 0
    errors = 0
    failures = []

    for line in output.splitlines():
        if " PASSED" in line:
            passed += 1
        elif " FAILED" in line:
            failed += 1
            # Extract test name
            test_name = line.split(" FAILED")[0].strip()
            failures.append({"test": test_name, "message": "Failed"})
        elif " ERROR" in line:
            errors += 1
            test_name = line.split(" ERROR")[0].strip()
            failures.append({"test": test_name, "message": "Error"})

    # Try to parse the summary line: "X passed, Y failed"
    for line in reversed(output.splitlines()):
        line_lower = line.lower().strip()
        if "passed" in line_lower or "failed" in line_lower or "error" in line_lower:
            import re
            p = re.search(r"(\d+)\s+passed", line_lower)
            f = re.search(r"(\d+)\s+failed", line_lower)
            e = re.search(r"(\d+)\s+error", line_lower)
            if p:
                passed = int(p.group(1))
            if f:
                failed = int(f.group(1))
            if e:
                errors = int(e.group(1))
            break

    total = passed + failed + errors

    return {
        "success": exit_code == 0 and failed == 0 and errors == 0,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "total": total,
        "output": output,
        "failures": failures,
    }


def run_pytest_with_coverage(
    test_file: str,
    source_file: str,
    python_path: str = "python",
    timeout: int = 60,
) -> dict:
    """
    Run pytest with coverage measurement.

    Returns:
        Same as run_pytest() plus:
        {"coverage_percent": float, "uncovered_lines": [...]}
    """
    test_path = Path(test_file).resolve()
    source_path = Path(source_file).resolve()
    test_dir = test_path.parent

    cmd = [
        python_path, "-m", "pytest",
        str(test_path),
        f"--cov={source_path.stem}",
        "--cov-report=json",
        "-v", "--tb=short", "--no-header",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(test_dir),
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )

        test_result = _parse_pytest_output(result.stdout + result.stderr, result.returncode)

        # Try to read coverage JSON
        cov_file = test_dir / "coverage.json"
        if cov_file.exists():
            try:
                with open(cov_file, "r") as f:
                    cov_data = json.load(f)
                total_cov = cov_data.get("totals", {}).get("percent_covered", 0)
                test_result["coverage_percent"] = round(total_cov, 1)
            except Exception:
                test_result["coverage_percent"] = None
            finally:
                cov_file.unlink(missing_ok=True)
        else:
            test_result["coverage_percent"] = None

        return test_result

    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return {
            "success": False,
            "passed": 0,
            "failed": 0,
            "errors": 1,
            "total": 0,
            "output": str(exc),
            "failures": [],
            "coverage_percent": None,
        }


# ── Standalone usage ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="AI Test Case Generator - Validator & Runner"
    )
    parser.add_argument("test_file", help="Path to the test file to validate")
    parser.add_argument(
        "--run", action="store_true", help="Run pytest if validation passes"
    )

    args = parser.parse_args()

    test_path = Path(args.test_file)
    if not test_path.is_file():
        print(f"Error: file not found: {args.test_file}", file=sys.stderr)
        sys.exit(1)

    code = test_path.read_text(encoding="utf-8")
    source_dir = str(test_path.parent.parent)

    result = validate_all(code, source_dir)
    print(json.dumps(result, indent=2))

    if args.run and result["valid"]:
        print("\nRunning pytest...")
        run_result = run_pytest(str(test_path))
        print(json.dumps(run_result, indent=2))
        if run_result.get("failed", 0) > 0 or run_result.get("errors", 0) > 0:
            sys.exit(1)
    elif not result["valid"]:
        sys.exit(1)
