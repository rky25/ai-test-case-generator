"""
Test Execution, Defect & Mismatch Reporting Engine.

Runs pytest on a target test file, captures detailed pass/fail metrics,
extracts assertion mismatches (expected vs actual), and produces:
  1. Structured JSON for extension consumption and Webview rendering
  2. Standalone, responsive HTML quality reports with modern aesthetics
"""

import argparse
import datetime
import html
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def run_test_and_report(
    test_file_path: str,
    python_path: Optional[str] = None,
    output_html_path: Optional[str] = None,
    timeout: int = 60,
) -> Dict[str, Any]:
    """
    Execute pytest on test_file_path, parse results into a structured dict,
    and optionally generate an interactive HTML report.
    """
    test_path = Path(test_file_path).resolve()
    if not test_path.exists():
        raise FileNotFoundError(f"Test file not found: {test_path}")

    if not python_path or python_path == "python":
        python_path = sys.executable or "python"

    # Ensure parent folder is in cwd or sys.path so imports work
    test_dir = test_path.parent
    project_root = test_dir.parent if test_dir.name in ("generated_tests", "tests") else test_dir

    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{str(project_root)}{os.pathsep}{existing_pythonpath}"
        if existing_pythonpath
        else str(project_root)
    )

    cmd = [
        python_path,
        "-m",
        "pytest",
        str(test_path),
        "-v",
        "--tb=short",
        "--no-header",
    ]

    start_time = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(project_root),
            env=env,
        )
        elapsed = round(time.time() - start_time, 3)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        raw_output = stdout + ("\n" + stderr if stderr else "")
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        elapsed = round(time.time() - start_time, 3)
        return {
            "success": False,
            "error": f"Test execution timed out after {timeout} seconds",
            "test_file": str(test_path),
            "summary": {"total": 0, "passed": 0, "failed": 0, "errors": 1, "pass_rate": 0.0},
            "duration": elapsed,
            "tests": [],
            "html_report": None,
        }
    except Exception as exc:
        elapsed = round(time.time() - start_time, 3)
        return {
            "success": False,
            "error": f"Failed to execute pytest: {str(exc)}",
            "test_file": str(test_path),
            "summary": {"total": 0, "passed": 0, "failed": 0, "errors": 1, "pass_rate": 0.0},
            "duration": elapsed,
            "tests": [],
            "html_report": None,
        }

    # Parse pytest output
    report_data = _parse_pytest_detailed_output(
        raw_output=raw_output,
        exit_code=exit_code,
        test_path=test_path,
        duration=elapsed,
    )

    # Determine default HTML output path if requested
    if output_html_path is True or output_html_path is None:
        html_filename = f"{test_path.stem}_report.html"
        output_html_path = str(test_path.parent / html_filename)

    if output_html_path and isinstance(output_html_path, str):
        generate_html_report(report_data, output_html_path)
        report_data["html_report"] = output_html_path

    return report_data


def _parse_pytest_detailed_output(
    raw_output: str,
    exit_code: int,
    test_path: Path,
    duration: float,
) -> Dict[str, Any]:
    """
    Parse verbose pytest output into structured test cases and failure details.
    """
    tests: List[Dict[str, Any]] = []
    lines = raw_output.splitlines()

    # Step 1: Extract individual test lines (e.g., "test_file.py::TestClass::test_method PASSED [ 25%]")
    # Pattern: filename::[Class::]?method (PASSED|FAILED|ERROR|SKIPPED)
    test_line_regex = re.compile(
        r"^(?P<target>.*::(?P<name>[a-zA-Z0-9_]+(?:\[.*?\])?))\s+(?P<status>PASSED|FAILED|ERROR|SKIPPED)",
        re.MULTILINE,
    )

    for line in lines:
        match = test_line_regex.search(line.strip())
        if match:
            target = match.group("target")
            name = match.group("name")
            status = match.group("status")

            # Extract class name if present
            parts = target.split("::")
            class_name = parts[1] if len(parts) >= 3 else None

            tests.append({
                "id": target,
                "name": name,
                "class_name": class_name,
                "status": status,
                "mismatch": None,
                "error_type": None,
                "error_message": None,
                "traceback": None,
                "location": None,
            })

    # Step 2: Extract failure details from the "=== FAILURES ===" section
    failures_by_name = _extract_failure_blocks(raw_output)

    # Attach failure information to matching test records
    for test in tests:
        name_key = test["name"]
        # Try exact match or base name without parametrization brackets
        failure_info = failures_by_name.get(name_key)
        if not failure_info:
            base_name = name_key.split("[")[0]
            failure_info = failures_by_name.get(base_name)

        if failure_info and test["status"] in ("FAILED", "ERROR"):
            test["error_type"] = failure_info.get("error_type")
            test["error_message"] = failure_info.get("error_message")
            test["mismatch"] = failure_info.get("mismatch")
            test["traceback"] = failure_info.get("traceback")
            test["location"] = failure_info.get("location")

    # Step 3: Compute summary metrics
    passed_count = sum(1 for t in tests if t["status"] == "PASSED")
    failed_count = sum(1 for t in tests if t["status"] == "FAILED")
    error_count = sum(1 for t in tests if t["status"] == "ERROR")
    skipped_count = sum(1 for t in tests if t["status"] == "SKIPPED")
    total_count = len(tests)

    # Fallback to summary line if test count was 0 from line parsing
    if total_count == 0:
        for line in reversed(lines):
            line_clean = line.lower().strip()
            if "passed" in line_clean or "failed" in line_clean or "error" in line_clean:
                p = re.search(r"(\d+)\s+passed", line_clean)
                f = re.search(r"(\d+)\s+failed", line_clean)
                e = re.search(r"(\d+)\s+error", line_clean)
                s = re.search(r"(\d+)\s+skipped", line_clean)
                passed_count = int(p.group(1)) if p else 0
                failed_count = int(f.group(1)) if f else 0
                error_count = int(e.group(1)) if e else 0
                skipped_count = int(s.group(1)) if s else 0
                total_count = passed_count + failed_count + error_count + skipped_count
                break

    pass_rate = round((passed_count / total_count * 100), 1) if total_count > 0 else 0.0

    return {
        "success": exit_code == 0 and failed_count == 0 and error_count == 0,
        "test_file": str(test_path),
        "test_file_name": test_path.name,
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "duration": duration,
        "summary": {
            "total": total_count,
            "passed": passed_count,
            "failed": failed_count,
            "errors": error_count,
            "skipped": skipped_count,
            "pass_rate": pass_rate,
        },
        "tests": tests,
        "raw_output": raw_output,
        "html_report": None,
    }


def _extract_failure_blocks(raw_output: str) -> Dict[str, Dict[str, Any]]:
    """
    Parse the FAILURES block from pytest output to extract error types,
    assertion mismatches, and code locations.
    """
    failures: Dict[str, Dict[str, Any]] = {}
    if "=== FAILURES ===" not in raw_output and "=== ERRORS ===" not in raw_output:
        return failures

    # Split into failure blocks separated by "_ [ClassName.]test_name _"
    header_pattern = re.compile(r"^_{1,}\s+(?P<header_text>[\w<>\[\]\.:\+-]+)\s+_{1,}$", re.MULTILINE)
    matches = list(header_pattern.finditer(raw_output))

    for idx, match in enumerate(matches):
        header_text = match.group("header_text").strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(raw_output)

        block = raw_output[start:end]
        # Trim off summary lines at the end
        if "=== short test summary info ===" in block:
            block = block.split("=== short test summary info ===")[0]
        if "=== FAILURES ===" in block:
            block = block.split("=== FAILURES ===")[0]

        parsed = _analyze_failure_block(block)

        # Store by full header text
        failures[header_text] = parsed

        # If header_text is Class.method[params], also extract method[params]
        if "." in header_text:
            method_with_params = header_text.split(".", 1)[1]
            failures[method_with_params] = parsed
            # Also base method name without params
            base_method = method_with_params.split("[")[0]
            failures[base_method] = parsed

        # Also store base name without [params]
        base_header = header_text.split("[")[0]
        failures[base_header] = parsed

    return failures


def _analyze_failure_block(block: str) -> Dict[str, Any]:
    """
    Analyze a single failure block to extract error type, message,
    location, and expected vs actual mismatch.
    """
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    error_type = "Failure"
    error_message = "Test assertion or execution failed"
    location = None
    expected = None
    actual = None
    mismatch_desc = None

    # Search for lines starting with 'E   '
    error_lines = [l for l in lines if l.startswith("E   ")]
    if error_lines:
        first_err = error_lines[0][4:].strip()

        if first_err.startswith("assert "):
            error_type = "AssertionError"
            error_message = first_err
            assert_match = re.search(r"^assert\s+(?P<actual>.+?)\s*==\s*(?P<expected>.+)", first_err)
            if assert_match:
                actual = assert_match.group("actual").strip()
                expected = assert_match.group("expected").strip()
                mismatch_desc = f"Expected: {expected} | Actual: {actual}"
            else:
                mismatch_desc = first_err
        elif first_err.startswith("Failed:"):
            error_type = "AssertionError"
            error_message = first_err
            mismatch_desc = first_err
        else:
            # Pattern: ExceptionType: message (e.g. "TypeError: unsupported operand...")
            type_match = re.match(r"^([a-zA-Z0-9_]+(?:Error|Exception)):\s*(.*)$", first_err)
            if type_match:
                error_type = type_match.group(1)
                error_message = type_match.group(2) or error_type
            else:
                error_message = first_err
            mismatch_desc = error_message

    # Search for code location: line starting with "file.py:line:"
    for line in lines:
        loc_match = re.search(r"([\w_\\/\.-]+\.py):(\d+):", line)
        if loc_match:
            location = f"{Path(loc_match.group(1)).name}:{loc_match.group(2)}"
            break

    # Build clean traceback snippet
    tb_snippet = "\n".join(lines[:14]) if lines else block.strip()

    return {
        "error_type": error_type,
        "error_message": error_message,
        "location": location,
        "mismatch": {
            "description": mismatch_desc or error_message,
            "expected": expected,
            "actual": actual,
        } if mismatch_desc else None,
        "traceback": tb_snippet,
    }


def generate_html_report(report_data: Dict[str, Any], output_path: str) -> str:
    """
    Generate an interactive, standalone HTML quality report with rich aesthetics.
    """
    summary = report_data.get("summary", {})
    total = summary.get("total", 0)
    passed = summary.get("passed", 0)
    failed = summary.get("failed", 0)
    errors = summary.get("errors", 0)
    skipped = summary.get("skipped", 0)
    pass_rate = summary.get("pass_rate", 0.0)
    duration = report_data.get("duration", 0.0)
    timestamp = report_data.get("timestamp", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    test_file_name = report_data.get("test_file_name", "Generated Tests")
    tests = report_data.get("tests", [])

    # Theme colors based on pass rate
    if pass_rate == 100.0:
        badge_color = "#10b981"
        badge_bg = "rgba(16, 185, 129, 0.15)"
        status_text = "100% ALL TESTS PASSED"
    elif pass_rate >= 80.0:
        badge_color = "#3b82f6"
        badge_bg = "rgba(59, 130, 246, 0.15)"
        status_text = f"{pass_rate}% PASSING (MINOR MISMATCHES)"
    else:
        badge_color = "#ef4444"
        badge_bg = "rgba(239, 68, 68, 0.15)"
        status_text = f"{pass_rate}% PASS RATE (ACTION REQUIRED)"

    # Build rows
    rows_html = []
    for idx, test in enumerate(tests, 1):
        status = test.get("status", "UNKNOWN")
        name = html.escape(test.get("name", f"test_{idx}"))
        class_name = html.escape(test.get("class_name") or "")

        if status == "PASSED":
            status_badge = '<span class="badge pass">PASSED</span>'
            row_class = "row-pass"
            details_html = ""
        else:
            status_badge = f'<span class="badge fail">{html.escape(status)}</span>'
            row_class = "row-fail"

            err_type = html.escape(test.get("error_type") or "Failure")
            err_msg = html.escape(test.get("error_message") or "")
            location = html.escape(test.get("location") or "Unknown")
            mismatch = test.get("mismatch")
            tb = html.escape(test.get("traceback") or "")

            mismatch_box = ""
            if mismatch and (mismatch.get("expected") or mismatch.get("actual")):
                exp = html.escape(str(mismatch.get("expected", "None")))
                act = html.escape(str(mismatch.get("actual", "None")))
                mismatch_box = f"""
                <div class="mismatch-box">
                    <div class="mismatch-item expected">
                        <span class="m-label">EXPECTED RESULT</span>
                        <code>{exp}</code>
                    </div>
                    <div class="mismatch-item actual">
                        <span class="m-label">ACTUAL RESULT / BEHAVIOR</span>
                        <code>{act}</code>
                    </div>
                </div>
                """

            details_html = f"""
            <div class="failure-drawer">
                <div class="failure-header">
                    <span class="err-type">⚠️ {err_type}</span>
                    <span class="err-loc">📍 Location: {location}</span>
                </div>
                <div class="err-msg">{err_msg}</div>
                {mismatch_box}
                <div class="traceback-wrapper">
                    <div class="tb-title">Stack Trace & Execution Context</div>
                    <pre class="traceback"><code>{tb}</code></pre>
                </div>
            </div>
            """

        row = f"""
        <div class="test-card {row_class}" data-status="{status}">
            <div class="test-summary" onclick="toggleDetails(this)">
                <div class="test-meta">
                    <span class="test-index">#{idx}</span>
                    <span class="test-title">{name}</span>
                    {f'<span class="class-tag">{class_name}</span>' if class_name else ''}
                </div>
                <div class="test-status-col">
                    {status_badge}
                    {f'<span class="chevron">▼</span>' if status != "PASSED" else ''}
                </div>
            </div>
            {details_html}
        </div>
        """
        rows_html.append(row)

    full_rows = "\n".join(rows_html)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Test Quality & Mismatch Report — {html.escape(test_file_name)}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-primary: #0f172a;
            --bg-secondary: #1e293b;
            --bg-tertiary: #334155;
            --border-color: rgba(255, 255, 255, 0.08);
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --text-muted: #64748b;
            --accent-green: #10b981;
            --accent-green-bg: rgba(16, 185, 129, 0.12);
            --accent-red: #ef4444;
            --accent-red-bg: rgba(239, 68, 68, 0.12);
            --accent-blue: #38bdf8;
            --accent-purple: #818cf8;
            --card-radius: 12px;
            --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            background-color: var(--bg-primary);
            color: var(--text-primary);
            font-family: var(--font-sans);
            padding: 2.5rem 1.5rem;
            line-height: 1.5;
            -webkit-font-smoothing: antialiased;
        }}

        .container {{
            max-width: 1040px;
            margin: 0 auto;
        }}

        /* Header */
        .report-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 2rem;
            padding-bottom: 1.5rem;
            border-bottom: 1px solid var(--border-color);
        }}

        .brand {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
            margin-bottom: 0.5rem;
        }}

        .brand-icon {{
            font-size: 1.75rem;
        }}

        .brand-name {{
            font-size: 1.5rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            background: linear-gradient(135deg, #f8fafc 0%, #cbd5e1 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}

        .report-subtitle {{
            color: var(--text-secondary);
            font-size: 0.9rem;
            display: flex;
            gap: 1rem;
            align-items: center;
        }}

        .file-pill {{
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            padding: 0.2rem 0.6rem;
            border-radius: 6px;
            font-family: var(--font-mono);
            font-size: 0.85rem;
            color: var(--accent-blue);
        }}

        .overall-badge {{
            background: {badge_bg};
            color: {badge_color};
            border: 1px solid {badge_color};
            padding: 0.4rem 0.9rem;
            border-radius: 9999px;
            font-size: 0.8rem;
            font-weight: 700;
            letter-spacing: 0.05em;
            text-transform: uppercase;
        }}

        /* Metrics Grid */
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }}

        .metric-card {{
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: var(--card-radius);
            padding: 1.25rem 1.5rem;
            transition: transform 0.15s ease, border-color 0.15s ease;
        }}

        .metric-card:hover {{
            transform: translateY(-2px);
            border-color: rgba(255, 255, 255, 0.15);
        }}

        .metric-label {{
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: var(--text-muted);
            margin-bottom: 0.35rem;
            font-weight: 600;
        }}

        .metric-value {{
            font-size: 2rem;
            font-weight: 700;
            letter-spacing: -0.03em;
        }}

        .metric-card.pass .metric-value {{ color: var(--accent-green); }}
        .metric-card.fail .metric-value {{ color: var(--accent-red); }}
        .metric-card.rate .metric-value {{ color: var(--accent-blue); }}
        .metric-card.time .metric-value {{ color: var(--accent-purple); font-size: 1.7rem; }}

        /* Progress Bar */
        .progress-bar-container {{
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 0.5rem;
            margin-bottom: 2rem;
            display: flex;
            height: 18px;
            gap: 4px;
            overflow: hidden;
        }}

        .bar-segment {{
            height: 100%;
            border-radius: 4px;
            transition: width 0.3s ease;
        }}

        .bar-pass {{ background: var(--accent-green); }}
        .bar-fail {{ background: var(--accent-red); }}

        /* Filters */
        .filter-bar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.25rem;
            gap: 1rem;
            flex-wrap: wrap;
        }}

        .filter-buttons {{
            display: flex;
            gap: 0.5rem;
        }}

        .filter-btn {{
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            color: var(--text-secondary);
            padding: 0.45rem 0.9rem;
            border-radius: 8px;
            font-size: 0.85rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.15s ease;
        }}

        .filter-btn.active {{
            background: var(--bg-tertiary);
            color: var(--text-primary);
            border-color: rgba(255, 255, 255, 0.2);
        }}

        .search-box {{
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            color: var(--text-primary);
            padding: 0.45rem 0.9rem;
            border-radius: 8px;
            font-size: 0.85rem;
            outline: none;
            width: 240px;
        }}

        .search-box:focus {{
            border-color: var(--accent-blue);
        }}

        /* Test Cards */
        .test-list {{
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
        }}

        .test-card {{
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: var(--card-radius);
            overflow: hidden;
            transition: border-color 0.15s ease;
        }}

        .test-card.row-fail {{
            border-color: rgba(239, 68, 68, 0.3);
        }}

        .test-summary {{
            padding: 1rem 1.25rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
            user-select: none;
        }}

        .test-meta {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
            flex-wrap: wrap;
        }}

        .test-index {{
            color: var(--text-muted);
            font-family: var(--font-mono);
            font-size: 0.8rem;
        }}

        .test-title {{
            font-weight: 600;
            font-size: 0.95rem;
            font-family: var(--font-mono);
            color: var(--text-primary);
        }}

        .class-tag {{
            background: rgba(255, 255, 255, 0.05);
            color: var(--text-secondary);
            padding: 0.15rem 0.45rem;
            border-radius: 4px;
            font-size: 0.75rem;
        }}

        .test-status-col {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }}

        .badge {{
            font-size: 0.75rem;
            font-weight: 700;
            padding: 0.2rem 0.55rem;
            border-radius: 6px;
            letter-spacing: 0.04em;
        }}

        .badge.pass {{
            background: var(--accent-green-bg);
            color: var(--accent-green);
            border: 1px solid rgba(16, 185, 129, 0.3);
        }}

        .badge.fail {{
            background: var(--accent-red-bg);
            color: var(--accent-red);
            border: 1px solid rgba(239, 68, 68, 0.3);
        }}

        .chevron {{
            color: var(--text-muted);
            font-size: 0.75rem;
            transition: transform 0.2s ease;
        }}

        .test-card.open .chevron {{
            transform: rotate(180deg);
        }}

        /* Failure Drawer */
        .failure-drawer {{
            display: none;
            padding: 1.25rem;
            background: rgba(15, 23, 42, 0.6);
            border-top: 1px solid var(--border-color);
        }}

        .test-card.open .failure-drawer {{
            display: block;
        }}

        .failure-header {{
            display: flex;
            justify-content: space-between;
            margin-bottom: 0.75rem;
            font-size: 0.85rem;
        }}

        .err-type {{
            color: var(--accent-red);
            font-weight: 700;
        }}

        .err-loc {{
            color: var(--text-secondary);
            font-family: var(--font-mono);
            font-size: 0.8rem;
        }}

        .err-msg {{
            background: rgba(239, 68, 68, 0.08);
            border-left: 3px solid var(--accent-red);
            padding: 0.75rem 1rem;
            border-radius: 0 6px 6px 0;
            color: #fca5a5;
            font-family: var(--font-mono);
            font-size: 0.85rem;
            margin-bottom: 1rem;
            word-break: break-word;
        }}

        .mismatch-box {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1rem;
            margin-bottom: 1rem;
        }}

        @media (max-width: 640px) {{
            .mismatch-box {{ grid-template-columns: 1fr; }}
        }}

        .mismatch-item {{
            padding: 0.75rem 1rem;
            border-radius: 8px;
            font-size: 0.85rem;
        }}

        .mismatch-item.expected {{
            background: rgba(16, 185, 129, 0.08);
            border: 1px solid rgba(16, 185, 129, 0.2);
        }}

        .mismatch-item.actual {{
            background: rgba(239, 68, 68, 0.08);
            border: 1px solid rgba(239, 68, 68, 0.2);
        }}

        .m-label {{
            display: block;
            font-size: 0.7rem;
            font-weight: 700;
            letter-spacing: 0.05em;
            margin-bottom: 0.35rem;
        }}

        .mismatch-item.expected .m-label {{ color: var(--accent-green); }}
        .mismatch-item.actual .m-label {{ color: var(--accent-red); }}

        .mismatch-item code {{
            font-family: var(--font-mono);
            word-break: break-word;
            font-size: 0.85rem;
        }}

        .traceback-wrapper {{
            margin-top: 0.75rem;
        }}

        .tb-title {{
            font-size: 0.75rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.35rem;
            font-weight: 600;
        }}

        pre.traceback {{
            background: #090d16;
            padding: 0.85rem 1rem;
            border-radius: 8px;
            border: 1px solid var(--border-color);
            overflow-x: auto;
            color: #cbd5e1;
            font-family: var(--font-mono);
            font-size: 0.78rem;
            line-height: 1.5;
            max-height: 240px;
        }}

        .footer {{
            margin-top: 3rem;
            text-align: center;
            color: var(--text-muted);
            font-size: 0.8rem;
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <header class="report-header">
            <div>
                <div class="brand">
                    <span class="brand-icon">🧪</span>
                    <h1 class="brand-name">AI Test Quality & Mismatch Report</h1>
                </div>
                <div class="report-subtitle">
                    <span class="file-pill">📄 {html.escape(test_file_name)}</span>
                    <span>🕒 {html.escape(timestamp)}</span>
                </div>
            </div>
            <div>
                <span class="overall-badge">{status_text}</span>
            </div>
        </header>

        <!-- KPI Metrics -->
        <section class="metrics-grid">
            <div class="metric-card">
                <div class="metric-label">Total Test Cases</div>
                <div class="metric-value">{total}</div>
            </div>
            <div class="metric-card pass">
                <div class="metric-label">Passed Tests</div>
                <div class="metric-value">{passed}</div>
            </div>
            <div class="metric-card fail">
                <div class="metric-label">Mismatched / Failed</div>
                <div class="metric-value">{failed + errors}</div>
            </div>
            <div class="metric-card rate">
                <div class="metric-label">Quality Score</div>
                <div class="metric-value">{pass_rate}%</div>
            </div>
            <div class="metric-card time">
                <div class="metric-label">Execution Time</div>
                <div class="metric-value">{duration}s</div>
            </div>
        </section>

        <!-- Progress Bar -->
        <div class="progress-bar-container">
            <div class="bar-segment bar-pass" style="width: {pass_rate}%;"></div>
            <div class="bar-segment bar-fail" style="width: {100.0 - pass_rate}%;"></div>
        </div>

        <!-- Filter Controls -->
        <div class="filter-bar">
            <div class="filter-buttons">
                <button class="filter-btn active" onclick="setFilter('ALL', this)">All Tests ({total})</button>
                <button class="filter-btn" onclick="setFilter('PASSED', this)">✅ Passed ({passed})</button>
                <button class="filter-btn" onclick="setFilter('FAILED', this)">❌ Mismatches ({failed + errors})</button>
            </div>
            <input type="text" class="search-box" placeholder="Filter by test name..." onkeyup="filterSearch(this.value)">
        </div>

        <!-- Test List -->
        <section class="test-list" id="testList">
            {full_rows}
        </section>

        <footer class="footer">
            Generated autonomously by <strong>AI Test Case Generator</strong> • VS Code Enterprise Edition
        </footer>
    </div>

    <script>
        let currentFilter = 'ALL';
        let searchQuery = '';

        function toggleDetails(header) {{
            const card = header.parentElement;
            if (card.classList.contains('row-fail')) {{
                card.classList.toggle('open');
            }}
        }}

        // Auto-open all failed cards on initial load for immediate developer visibility
        document.addEventListener('DOMContentLoaded', () => {{
            document.querySelectorAll('.test-card.row-fail').forEach(card => {{
                card.classList.add('open');
            }});
        }});

        function setFilter(filterType, btn) {{
            currentFilter = filterType;
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            applyFilters();
        }}

        function filterSearch(val) {{
            searchQuery = val.toLowerCase().trim();
            applyFilters();
        }}

        function applyFilters() {{
            const cards = document.querySelectorAll('.test-card');
            cards.forEach(card => {{
                const status = card.getAttribute('data-status');
                const title = card.querySelector('.test-title').innerText.toLowerCase();

                let matchesFilter = (currentFilter === 'ALL') ||
                    (currentFilter === 'PASSED' && status === 'PASSED') ||
                    (currentFilter === 'FAILED' && (status === 'FAILED' || status === 'ERROR'));

                let matchesSearch = !searchQuery || title.includes(searchQuery);

                if (matchesFilter && matchesSearch) {{
                    card.style.display = 'block';
                }} else {{
                    card.style.display = 'none';
                }}
            }});
        }}
    </script>
</body>
</html>"""

    dest = Path(output_path).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(html_content, encoding="utf-8")
    return str(dest)


def main():
    parser = argparse.ArgumentParser(
        description="Run pytest on a generated test file and produce a quality & mismatch report."
    )
    parser.add_argument("--file", required=True, help="Path to test file (e.g. test_sample_discount.py)")
    parser.add_argument("--python", default="python", help="Python interpreter path")
    parser.add_argument("--html", action="store_true", help="Generate standalone HTML report")
    parser.add_argument("--html-output", default=None, help="Custom output path for HTML report")
    parser.add_argument("--json", action="store_true", help="Print structured JSON to stdout")

    args = parser.parse_args()

    html_dest = args.html_output if args.html_output else (True if args.html else False)

    try:
        report = run_test_and_report(
            test_file_path=args.file,
            python_path=args.python,
            output_html_path=html_dest,
        )

        if args.json:
            print(json.dumps(report, indent=2))
        else:
            summary = report.get("summary", {})
            print("\n=======================================================")
            print(f"  🧪 TEST QUALITY & MISMATCH REPORT: {report.get('test_file_name')}")
            print("=======================================================")
            print(f"  • Total Tests:     {summary.get('total')}")
            print(f"  • Passed:          {summary.get('passed')} (✅)")
            print(f"  • Failed / Errors: {summary.get('failed') + summary.get('errors')} (❌)")
            print(f"  • Quality Score:   {summary.get('pass_rate')}%")
            print(f"  • Duration:        {report.get('duration')}s")
            if report.get("html_report"):
                print(f"  • HTML Report:     {report.get('html_report')}")
            print("=======================================================\n")

            # Print failure summary if any
            failed_tests = [t for t in report.get("tests", []) if t.get("status") in ("FAILED", "ERROR")]
            if failed_tests:
                print("🚨 MISMATCH & DEFECT DETAILS:")
                for ft in failed_tests:
                    print(f"  ❌ {ft.get('name')}: {ft.get('error_type')} - {ft.get('error_message')}")
                    if ft.get("mismatch"):
                        m = ft.get("mismatch")
                        print(f"     Expected: {m.get('expected')}")
                        print(f"     Actual:   {m.get('actual')}")
                print()

    except Exception as exc:
        if args.json:
            print(json.dumps({"success": False, "error": str(exc)}))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
