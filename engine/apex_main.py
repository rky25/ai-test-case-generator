"""
CLI entry-point for Salesforce Apex test case generation.

Usage (called by the VS Code extension, or manually):

    python apex_main.py --file path/to/MyClass.cls              \\
                        --api-key YOUR_KEY                       \\
                        --output  generated_tests                \\
                        [--method myMethod]                      \\
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

from apex_analyzer import (
    extract_classes,
    extract_methods,
    extract_file_context,
    detect_apex_patterns,
    extract_apex_imports,
)
from apex_generator import generate_apex_tests
from apex_validator import validate_apex_all


# ── Helpers ───────────────────────────────────────────────────────

def _make_test_filename(source_name: str, class_name: str) -> str:
    """
    Generate test file name from source:
        AccountService.cls → AccountServiceTest.cls
    """
    stem = Path(source_name).stem
    return f"{stem}Test.cls"


def _make_test_filename_per_method(
    source_name: str, method_name: str
) -> str:
    """
    One test file per method:
        AccountService.cls + createAccount → AccountService_createAccountTest.cls
    """
    stem = Path(source_name).stem
    return f"{stem}_{method_name}Test.cls"


def _build_header(source_path: str, method_name: str) -> str:
    """Comment block at the top of every generated Apex test file."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clean_path = Path(source_path).as_posix()
    return (
        f"// ====================================================================\n"
        f"// Auto-generated test cases by AI Test Case Generator\n"
        f"// Source  : {clean_path}\n"
        f"// Method  : {method_name}\n"
        f"// Generated: {now}\n"
        f"// ====================================================================\n\n"
    )


# ── Main logic ────────────────────────────────────────────────────

def run_apex(
    file_path: str,
    api_key: str,
    output_dir: str = "generated_tests",
    method_name: str | None = None,
    base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai",
    model: str = "gemini-2.5-flash",
    as_json: bool = False,
    validate: bool = True,
    max_retries: int = 2,
    per_method: bool = False,
) -> dict:
    """
    Core Apex pipeline:
      1. Parse the .cls source file (regex-based)
      2. For each target method, call the AI
      3. Save the test file(s)

    Args:
        per_method: If True, generate one test file per method.
                    If False, generate one test file per class (default).

    Returns a result dict.
    """
    source = Path(file_path).resolve()

    if not source.exists():
        raise FileNotFoundError(f"Source file not found: {source}")

    if source.suffix.lower() not in (".cls", ".trigger", ".apex"):
        raise ValueError(
            f"Expected an Apex file (.cls, .trigger), got: {source.suffix}"
        )

    # ── Parse ─────────────────────────────────────────────────
    classes = extract_classes(str(source))
    methods = extract_methods(str(source), method_name)
    context = extract_file_context(str(source))
    patterns = detect_apex_patterns(str(source))
    references = extract_apex_imports(str(source))

    # Filter out test methods — we don't generate tests for tests
    methods = [m for m in methods if not m.get("is_test")]

    if not methods:
        msg = (
            f"No method '{method_name}' found in {source.name}"
            if method_name
            else f"No methods found in {source.name}"
        )
        raise ValueError(msg)

    # Use first class info as the primary class context
    class_info = classes[0] if classes else {
        "name": source.stem,
        "access": "",
        "modifiers": "",
        "extends": None,
        "implements": [],
        "annotations": [],
    }

    # ── Output directory ──────────────────────────────────────
    out = Path(output_dir)
    if not out.is_absolute():
        out = source.parent / out
    out.mkdir(parents=True, exist_ok=True)

    # ── Generate ──────────────────────────────────────────────
    results = []

    if per_method:
        # Generate one test file per method
        for method in methods:
            name = method["name"]
            if not as_json:
                print(f"[*] Generating Apex tests for: {name} ...")

            result = _generate_single_method(
                method=method,
                class_info=class_info,
                context=context,
                patterns=patterns,
                references=references,
                source=source,
                out=out,
                api_key=api_key,
                base_url=base_url,
                model=model,
                as_json=as_json,
                validate=validate,
                max_retries=max_retries,
            )
            results.append(result)
    else:
        # Generate one test file for the entire class
        if not as_json:
            class_name = class_info.get("name", source.stem)
            print(f"[*] Generating Apex tests for class: {class_name} ...")

        # Use the first method as the target but pass full source
        # so the AI generates a complete test class
        result = _generate_class_tests(
            methods=methods,
            class_info=class_info,
            context=context,
            patterns=patterns,
            references=references,
            source=source,
            out=out,
            api_key=api_key,
            base_url=base_url,
            model=model,
            as_json=as_json,
            validate=validate,
            max_retries=max_retries,
        )
        results.append(result)

    success_count = sum(1 for r in results if r["status"] == "ok")
    error_count = sum(1 for r in results if r["status"] == "error")

    return {
        "source": str(source),
        "language": "apex",
        "output_dir": str(out),
        "total": len(results),
        "success": success_count,
        "failed": error_count,
        "results": results,
    }


def _generate_single_method(
    method: dict,
    class_info: dict,
    context: dict,
    patterns: list,
    references: list,
    source: Path,
    out: Path,
    api_key: str,
    base_url: str,
    model: str,
    as_json: bool,
    validate: bool,
    max_retries: int,
) -> dict:
    """Generate tests for a single Apex method."""
    name = method["name"]
    generated = False
    last_error = None

    for attempt in range(max_retries):
        try:
            test_code = generate_apex_tests(
                method_info=method,
                class_info=class_info,
                file_context=context,
                api_key=api_key,
                base_url=base_url,
                model=model,
                patterns=patterns,
                references=references,
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
            validation = validate_apex_all(test_code)
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
        if not as_json:
            print(f"  [-] Error: {last_error}")
        return {
            "function": name,
            "status": "error",
            "error": last_error,
            "file": None,
        }

    # Write the file
    test_filename = _make_test_filename_per_method(source.name, name)
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

    return {
        "function": name,
        "status": "ok",
        "error": None,
        "file": str(test_path),
        "test_count": test_count,
    }


def _generate_class_tests(
    methods: list,
    class_info: dict,
    context: dict,
    patterns: list,
    references: list,
    source: Path,
    out: Path,
    api_key: str,
    base_url: str,
    model: str,
    as_json: bool,
    validate: bool,
    max_retries: int,
) -> dict:
    """Generate a single test class covering all methods."""
    class_name = class_info.get("name", source.stem)
    generated = False
    last_error = None

    # Build a combined method info that references all methods
    combined_method = {
        "name": "ALL_METHODS",
        "body": context.get("source", ""),
        "annotations": [],
        "soql_queries": [],
        "dml_operations": [],
        "is_static": False,
    }

    for attempt in range(max_retries):
        try:
            test_code = generate_apex_tests(
                method_info=combined_method,
                class_info=class_info,
                file_context=context,
                api_key=api_key,
                base_url=base_url,
                model=model,
                patterns=patterns,
                references=references,
            )
        except Exception as exc:
            last_error = str(exc)
            if attempt < max_retries - 1:
                if not as_json:
                    print(f"  [!] Retry {attempt + 1}: {exc}")
                continue
            break

        # Validate
        validation = None
        if validate:
            validation = validate_apex_all(test_code)
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
        if not as_json:
            print(f"  [-] Error: {last_error}")
        return {
            "function": class_name,
            "status": "error",
            "error": last_error,
            "file": None,
        }

    # Write the file
    test_filename = _make_test_filename(source.name, class_name)
    test_path = out / test_filename
    header = _build_header(str(source), f"class {class_name}")
    test_path.write_text(header + test_code + "\n", encoding="utf-8")

    test_count = (
        validation["structure"]["test_count"]
        if validate and validation
        else None
    )

    if not as_json:
        display_count = test_count if test_count is not None else "?"
        print(f"  [+] Saved -> {test_path} ({display_count} tests)")

    return {
        "function": class_name,
        "status": "ok",
        "error": None,
        "file": str(test_path),
        "test_count": test_count,
    }


# ── CLI ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="AI Test Case Generator - generate Apex test classes for Salesforce"
    )
    parser.add_argument(
        "--file", required=True,
        help="Path to the Apex source file (.cls or .trigger)"
    )
    parser.add_argument(
        "--method", default=None,
        help="Generate tests for a specific method only"
    )
    parser.add_argument(
        "--output", default="generated_tests",
        help="Output folder for test files"
    )
    parser.add_argument(
        "--api-key", default=None,
        help="AI API key(s), comma-separated for fallback"
    )
    parser.add_argument(
        "--fallback-key", default=None,
        help="Secondary API key used if the primary fails"
    )
    parser.add_argument(
        "--base-url",
        default="https://generativelanguage.googleapis.com/v1beta/openai",
        help="API base URL (default: Gemini)"
    )
    parser.add_argument(
        "--model", default="gemini-2.5-flash",
        help="Model name (default: gemini-2.5-flash)"
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Output result as JSON"
    )
    parser.add_argument(
        "--no-validate", action="store_true",
        help="Skip test code validation"
    )
    parser.add_argument(
        "--per-method", action="store_true",
        help="Generate one test file per method instead of one per class"
    )

    args = parser.parse_args()

    # ── Resolve API keys ──────────────────────────────────────
    primary = args.api_key or os.environ.get("TESTGEN_API_KEY", "")
    fallback = args.fallback_key or os.environ.get("TESTGEN_FALLBACK_KEY", "")

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

    try:
        result = run_apex(
            file_path=args.file,
            api_key=all_keys,
            output_dir=args.output,
            method_name=args.method,
            base_url=args.base_url,
            model=args.model,
            as_json=args.as_json,
            validate=not args.no_validate,
            per_method=args.per_method,
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
            f"Done!  {result['success']}/{result['total']} generated.\n"
            f"Tests saved to: {result['output_dir']}"
        )


if __name__ == "__main__":
    main()
