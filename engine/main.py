"""
CLI entry-point for the AI Test Case Generator engine.

Usage (called by the VS Code extension, or manually):

    python main.py --file path/to/source.py                \\
                   --api-key sk-...                         \\
                   --output  generated_tests                \\
                   [--function my_func]                     \\
                   [--base-url https://api.openai.com/v1]   \\
                   [--model gpt-4o-mini]                    \\
                   [--json]

If --json is passed the output is a single JSON object on
stdout (for the extension to parse).  Otherwise human-readable
progress messages are printed.
"""

import argparse
import json
import os
import sys
import datetime
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Allow running from any directory
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


# ── Helpers ───────────────────────────────────────────────────────

def _make_test_filename(source_name: str, func_name: str) -> str:
    """
    One test file per function:
        utils.py  +  calculate_tax  ➜  test_utils_calculate_tax.py
    """
    stem = Path(source_name).stem
    return f"test_{stem}_{func_name}.py"


def _build_header(source_path: str, func_name: str) -> str:
    """Comment block at the top of every generated file."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clean_path = Path(source_path).as_posix()
    return (
        f"# ====================================================================\n"
        f"# Auto-generated test cases by AI Test Case Generator\n"
        f"# Source  : {clean_path}\n"
        f"# Function: {func_name}\n"
        f"# Generated: {now}\n"
        f"# ====================================================================\n\n"
    )


def _build_conftest(output_dir: Path, project_root: Path) -> None:
    """
    Write a conftest.py that adds the project root to sys.path
    so generated imports resolve correctly.
    """
    conftest = output_dir / "conftest.py"
    if conftest.exists():
        return

    content = (
        "# Auto-generated conftest.py\n"
        "# Adds the project root to sys.path so imports in\n"
        "# generated test files resolve correctly.\n\n"
        "import sys\n"
        "from pathlib import Path\n\n"
        "PROJECT_ROOT = Path(__file__).resolve().parent.parent\n"
        "sys.path.insert(0, str(PROJECT_ROOT))\n"
    )
    conftest.write_text(content, encoding="utf-8")


# ── Main logic ────────────────────────────────────────────────────

def run(
    file_path: str,
    api_key: str,
    output_dir: str = "generated_tests",
    function_name: str | None = None,
    base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai",
    model: str = "gemini-2.5-flash",
    as_json: bool = False,
    validate: bool = True,
    max_retries: int = 2,
) -> dict:
    """
    Core pipeline:
      1. Parse the source file (AST)
      2. For each target function call the AI
      3. Save the test file(s)

    Returns a result dict.
    """
    source = Path(file_path).resolve()

    if not source.exists():
        raise FileNotFoundError(f"Source file not found: {source}")

    # ── Parse ─────────────────────────────────────────────────
    functions = extract_functions(str(source), function_name)
    if not functions:
        msg = (
            f"No function '{function_name}' found in {source.name}"
            if function_name
            else f"No functions found in {source.name}"
        )
        raise ValueError(msg)

    imports = extract_imports(str(source))
    context = extract_file_context(str(source))
    dependencies = extract_cross_file_dependencies(str(source), str(source.parent))
    frameworks = detect_frameworks(str(source), str(source.parent))
    fixtures = discover_workspace_fixtures(str(source.parent))

    # ── Output directory ──────────────────────────────────────
    out = Path(output_dir)
    if not out.is_absolute():
        out = source.parent / out
    out.mkdir(parents=True, exist_ok=True)

    # conftest.py for import resolution
    _build_conftest(out, source.parent)

    # ── Generate ──────────────────────────────────────────────
    results = []

    for func in functions:
        name = func["name"]

        if not as_json:
            print(f"[*] Generating tests for: {name} ...")

        generated = False
        last_error = None

        for attempt in range(max_retries):
            try:
                test_code = generate_tests(
                    func_info=func,
                    imports=imports,
                    filename=source.name,
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    file_context=context,
                    dependencies=dependencies,
                    frameworks=frameworks,
                    fixtures=fixtures,
                )
            except Exception as exc:
                last_error = str(exc)
                if attempt < max_retries - 1:
                    if not as_json:
                        print(f"  [!] Retry {attempt + 1}: {exc}")
                    continue
                break

            # Validate generated code
            validation = None
            if validate:
                validation = validate_all(test_code, str(source.parent))
                if not validation["valid"]:
                    error_msg = (
                        validation.get("syntax", {}).get("error")
                        or validation.get("structure", {}).get("error")
                        or "Validation failed"
                    )
                    last_error = error_msg
                    if attempt < max_retries - 1:
                        if not as_json:
                            print(f"  [!] Validation failed, retrying: {error_msg}")
                        continue
                    break

            generated = True
            break

        if not generated:
            results.append(
                {
                    "function": name,
                    "status": "error",
                    "error": last_error,
                    "file": None,
                    "test_results": None,
                }
            )
            if not as_json:
                print(f"  [-] Error: {last_error}")
            continue

        # Write the file
        test_filename = _make_test_filename(source.name, name)
        test_path = out / test_filename
        header = _build_header(str(source), name)
        test_path.write_text(header + test_code + "\n", encoding="utf-8")

        test_count = (
            validation["structure"]["test_count"]
            if validate and validation
            else None
        )

        if not as_json:
            display_count = test_count if test_count is not None else "?"
            print(f"  [+] Saved -> {test_path} ({display_count} tests)")

        results.append(
            {
                "function": name,
                "status": "ok",
                "error": None,
                "file": str(test_path),
                "test_count": test_count,
            }
        )

    return {
        "source": str(source),
        "output_dir": str(out),
        "total": len(functions),
        "success": sum(1 for r in results if r["status"] == "ok"),
        "failed": sum(1 for r in results if r["status"] == "error"),
        "results": results,
    }


# ── CLI ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="AI Test Case Generator - generate pytest tests for Python functions"
    )
    parser.add_argument("--file", required=True, help="Path to the Python source file")
    parser.add_argument("--function", default=None, help="Generate for a specific function only")
    parser.add_argument("--output", default="generated_tests", help="Output folder for test files")
    parser.add_argument(
        "--api-key", default=None,
        help="AI API key(s), comma-separated for fallback (or set TESTGEN_API_KEY env var)"
    )
    parser.add_argument(
        "--fallback-key", default=None,
        help="Secondary API key used if the primary fails (or set TESTGEN_FALLBACK_KEY env var)"
    )
    parser.add_argument(
        "--base-url",
        default="https://generativelanguage.googleapis.com/v1beta/openai",
        help="API base URL (default: Gemini)"
    )
    parser.add_argument("--model", default="gemini-2.5-flash", help="Model name (default: gemini-2.5-flash)")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Output result as JSON")
    parser.add_argument("--no-validate", action="store_true", help="Skip test code validation")
    parser.add_argument("--scan", action="store_true", help="Scan entire project for untested functions")

    args = parser.parse_args()

    # ── Resolve API keys (primary + optional fallback) ────────
    primary = args.api_key or os.environ.get("TESTGEN_API_KEY", "")
    fallback = args.fallback_key or os.environ.get("TESTGEN_FALLBACK_KEY", "")

    # Combine into comma-separated string
    all_keys = primary
    if fallback:
        all_keys = f"{primary},{fallback}" if primary else fallback

    if not all_keys:
        print(
            "Error: No API key provided.\n"
            "  Use --api-key or set the TESTGEN_API_KEY environment variable.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Project-wide scan mode
    if args.scan:
        from scanner import scan_project
        result = scan_project(
            project_root=os.path.dirname(os.path.abspath(args.file)),
            api_key=all_keys,
            as_json=args.as_json,
        )
        if args.as_json:
            print(json.dumps(result, indent=2))
        return

    try:
        result = run(
            file_path=args.file,
            api_key=all_keys,
            output_dir=args.output,
            function_name=args.function,
            base_url=args.base_url,
            model=args.model,
            as_json=args.as_json,
            validate=not args.no_validate,
        )
    except (FileNotFoundError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.as_json:
        print(json.dumps(result, indent=2))
    else:
        print(
            f"\n{'-' * 40}\n"
            f"Done!  {result['success']}/{result['total']} functions generated.\n"
            f"Tests saved to: {result['output_dir']}"
        )


if __name__ == "__main__":
    main()

