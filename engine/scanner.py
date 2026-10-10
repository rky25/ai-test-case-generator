"""
Project-wide test generation scanner.

Recursively scans a Python project, identifies all functions/methods,
determines which already have tests, and generates missing tests.

Features:
  - Configurable include/exclude patterns
  - Skips private/dunder methods
  - Detects existing test coverage
  - Rate-limiting to avoid API quota issues
  - Progress reporting (JSON or human-readable)
"""

import glob
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))

from analyzer import (
    extract_functions,
    extract_imports,
    extract_file_context,
    extract_cross_file_dependencies,
    detect_frameworks,
    discover_workspace_fixtures,
)
from generator import generate_tests
from validator import validate_all


def load_config(project_root: str) -> dict:
    """
    Load project configuration from .testgenrc.json if it exists.
    Falls back to sensible defaults.
    """
    defaults = {
        "include": ["**/*.py"],
        "exclude": [
            "**/tests/**",
            "**/test_*.py",
            "**/*_test.py",
            "**/generated_tests/**",
            "**/node_modules/**",
            "**/__pycache__/**",
            "**/venv/**",
            "**/.venv/**",
            "**/migrations/**",
            "**/setup.py",
            "**/conftest.py",
        ],
        "testFramework": "pytest",
        "outputDir": "generated_tests",
        "model": "gemini-2.5-flash",
        "baseUrl": "https://generativelanguage.googleapis.com/v1beta/openai",
        "maxTestsPerFunction": 15,
        "skipPrivate": True,
        "skipDunder": True,
        "rateLimitDelay": 2,
        "maxRetries": 2,
        "validateBeforeSave": True,
        "runAfterGenerate": False,
        "coverageThreshold": 0,
        "style": {
            "useFixtures": True,
            "useParametrize": True,
            "docstrings": True,
            "namingConvention": "test_<what>",
        },
    }

    config_path = Path(project_root) / ".testgenrc.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            # Merge user config into defaults (shallow merge)
            for key, value in user_config.items():
                if isinstance(value, dict) and key in defaults and isinstance(defaults[key], dict):
                    defaults[key].update(value)
                else:
                    defaults[key] = value
        except (json.JSONDecodeError, IOError) as exc:
            print(f"Warning: Could not parse .testgenrc.json: {exc}", file=sys.stderr)

    return defaults


def discover_python_files(
    project_root: str,
    include_patterns: list[str],
    exclude_patterns: list[str],
) -> list[str]:
    """
    Find all Python files matching include patterns, excluding excluded ones.
    """
    root = Path(project_root).resolve()
    included = set()

    for pattern in include_patterns:
        for match in root.glob(pattern):
            if match.is_file():
                included.add(str(match.resolve()))

    excluded = set()
    for pattern in exclude_patterns:
        for match in root.glob(pattern):
            if match.is_file():
                excluded.add(str(match.resolve()))

    # Also exclude files inside the engine directory itself
    engine_dir = str(Path(__file__).resolve().parent)
    result = []
    for f in sorted(included - excluded):
        if not f.startswith(engine_dir):
            result.append(f)

    return result


def find_existing_tests(output_dir: str) -> set:
    """
    Scan the output directory to find which functions already have test files.
    Returns a set of (source_stem, function_name) tuples.
    """
    existing = set()
    out = Path(output_dir)
    if not out.exists():
        return existing

    for test_file in out.glob("test_*.py"):
        name = test_file.stem  # e.g. test_sample_calculate_discount
        parts = name.split("_", 2)  # ['test', 'sample', 'calculate_discount']
        if len(parts) >= 3:
            source_stem = parts[1]
            func_name = parts[2]
            existing.add((source_stem, func_name))

    return existing


def scan_project(
    project_root: str,
    api_key: str,
    config: Optional[dict] = None,
    as_json: bool = False,
    dry_run: bool = False,
) -> dict:
    """
    Scan the entire project and generate tests for all discovered functions.

    Args:
        project_root: Root directory of the project
        api_key:      AI API key (comma-separated for fallback)
        config:       Optional config dict (loaded from .testgenrc.json if None)
        as_json:      If True, output JSON instead of human-readable text
        dry_run:      If True, list functions but don't generate tests

    Returns:
        {
            "project_root": "...",
            "files_scanned": N,
            "functions_found": N,
            "functions_skipped": N,
            "tests_generated": N,
            "tests_failed": N,
            "results": [...]
        }
    """
    root = Path(project_root).resolve()

    if config is None:
        config = load_config(str(root))

    # Discover files
    files = discover_python_files(
        str(root),
        config["include"],
        config["exclude"],
    )

    if not as_json:
        print(f"🔍 Scanning project: {root}")
        print(f"   Found {len(files)} Python file(s)")
        print()

    output_base = config["outputDir"]
    skip_private = config.get("skipPrivate", True)
    skip_dunder = config.get("skipDunder", True)
    rate_limit = config.get("rateLimitDelay", 2)
    validate = config.get("validateBeforeSave", True)
    max_retries = config.get("maxRetries", 2)

    # Enterprise Context: discover reusable fixtures across workspace
    workspace_fixtures = discover_workspace_fixtures(project_root)

    all_results = []
    total_functions = 0
    total_skipped = 0
    total_generated = 0
    total_failed = 0

    for file_idx, filepath in enumerate(files, start=1):
        source = Path(filepath)
        relative = source.relative_to(root)

        if not as_json:
            print(f"📄 [{file_idx}/{len(files)}] {relative}")

        try:
            functions = extract_functions(filepath)
            imports = extract_imports(filepath)
            context = extract_file_context(filepath)
            dependencies = extract_cross_file_dependencies(filepath, project_root)
            frameworks = detect_frameworks(filepath, project_root)
        except Exception as exc:
            if not as_json:
                print(f"   ⚠ Could not parse: {exc}")
            continue

        if not functions:
            if not as_json:
                print(f"   (no functions found)")
            continue

        # Output directory relative to source file
        out_dir = source.parent / output_base
        out_dir.mkdir(parents=True, exist_ok=True)

        # Check existing tests
        existing = find_existing_tests(str(out_dir))

        for func in functions:
            name = func["name"]
            total_functions += 1

            # Skip private / dunder
            if skip_dunder and name.startswith("__") and name.endswith("__"):
                total_skipped += 1
                continue
            if skip_private and name.startswith("_") and not name.startswith("__"):
                total_skipped += 1
                continue

            # Skip if already has tests
            if (source.stem, name) in existing:
                total_skipped += 1
                if not as_json:
                    print(f"   ⏭ {name}() — already has tests")
                continue

            if dry_run:
                if not as_json:
                    print(f"   📋 {name}() — would generate tests")
                all_results.append({
                    "file": str(relative),
                    "function": name,
                    "status": "dry_run",
                })
                continue

            # Generate tests with retry
            if not as_json:
                print(f"   🧪 {name}() — generating...", end="", flush=True)

            success = False
            last_error = None

            for attempt in range(max_retries):
                try:
                    test_code = generate_tests(
                        func_info=func,
                        imports=imports,
                        filename=source.name,
                        api_key=api_key,
                        base_url=config["baseUrl"],
                        model=config["model"],
                        file_context=context,
                        dependencies=dependencies,
                        frameworks=frameworks,
                        fixtures=workspace_fixtures,
                    )

                    # Validate if enabled
                    if validate:
                        validation = validate_all(test_code, str(source.parent))
                        if not validation["valid"]:
                            error_msg = (
                                validation.get("syntax", {}).get("error")
                                or validation.get("structure", {}).get("error")
                                or "Unknown validation error"
                            )
                            if attempt < max_retries - 1:
                                if not as_json:
                                    print(f" (retry {attempt + 1})...", end="", flush=True)
                                time.sleep(rate_limit)
                                continue
                            else:
                                last_error = f"Validation failed: {error_msg}"
                                break

                    # Write the test file
                    import datetime
                    test_filename = f"test_{source.stem}_{name}.py"
                    test_path = out_dir / test_filename

                    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    clean_source = source.as_posix()
                    header = (
                        f"# ====================================================================\n"
                        f"# Auto-generated test cases by AI Test Case Generator\n"
                        f"# Source  : {clean_source}\n"
                        f"# Function: {name}\n"
                        f"# Generated: {now}\n"
                        f"# ====================================================================\n\n"
                    )

                    # Write conftest if needed
                    conftest = out_dir / "conftest.py"
                    if not conftest.exists():
                        conftest_content = (
                            "# Auto-generated conftest.py\n"
                            "# Adds the project root to sys.path so imports in\n"
                            "# generated test files resolve correctly.\n\n"
                            "import sys\n"
                            "from pathlib import Path\n\n"
                            "PROJECT_ROOT = Path(__file__).resolve().parent.parent\n"
                            "sys.path.insert(0, str(PROJECT_ROOT))\n"
                        )
                        conftest.write_text(conftest_content, encoding="utf-8")

                    test_path.write_text(header + test_code + "\n", encoding="utf-8")

                    success = True
                    total_generated += 1

                    if not as_json:
                        test_count = validation["structure"]["test_count"] if validate else "?"
                        print(f" ✅ ({test_count} tests)")

                    all_results.append({
                        "file": str(relative),
                        "function": name,
                        "status": "ok",
                        "test_file": str(test_path),
                        "test_count": validation["structure"]["test_count"] if validate else None,
                    })
                    break

                except Exception as exc:
                    last_error = str(exc)
                    if attempt < max_retries - 1:
                        time.sleep(rate_limit)
                        continue

            if not success:
                total_failed += 1
                if not as_json:
                    print(f" ❌ {last_error}")
                all_results.append({
                    "file": str(relative),
                    "function": name,
                    "status": "error",
                    "error": last_error,
                })

            # Rate limiting between functions
            time.sleep(rate_limit)

    summary = {
        "project_root": str(root),
        "files_scanned": len(files),
        "functions_found": total_functions,
        "functions_skipped": total_skipped,
        "tests_generated": total_generated,
        "tests_failed": total_failed,
        "results": all_results,
    }

    if not as_json:
        print()
        print("=" * 50)
        print(f"📊 Project Scan Summary")
        print(f"   Files scanned:      {len(files)}")
        print(f"   Functions found:    {total_functions}")
        print(f"   Skipped (existing): {total_skipped}")
        print(f"   Tests generated:    {total_generated}")
        print(f"   Errors:             {total_failed}")
        print("=" * 50)

    return summary


# ── CLI ───────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="AI Test Case Generator - Project-wide scanner"
    )
    parser.add_argument(
        "project_pos", nargs="?", default=None,
        help="Path to the project root directory (positional)"
    )
    parser.add_argument(
        "--project", default=None,
        help="Path to the project root directory"
    )
    parser.add_argument(
        "--api-key", default=None,
        help="AI API key(s), comma-separated for fallback"
    )
    parser.add_argument(
        "--base-url", default=None,
        help="API base URL (overrides .testgenrc.json)"
    )
    parser.add_argument(
        "--model", default=None,
        help="Model name (overrides .testgenrc.json)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List functions without generating tests"
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Output result as JSON"
    )

    args = parser.parse_args()

    project_root = args.project or args.project_pos or "."
    api_key = args.api_key or os.environ.get("TESTGEN_API_KEY", "")
    if not api_key and not args.dry_run:
        print("Error: No API key provided. Use --api-key or set TESTGEN_API_KEY.", file=sys.stderr)
        sys.exit(1)

    # Load config and apply CLI overrides
    config = load_config(project_root)
    if args.base_url:
        config["baseUrl"] = args.base_url
    if args.model:
        config["model"] = args.model

    result = scan_project(
        project_root=project_root,
        api_key=api_key,
        config=config,
        as_json=args.as_json,
        dry_run=args.dry_run,
    )

    if args.as_json:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
