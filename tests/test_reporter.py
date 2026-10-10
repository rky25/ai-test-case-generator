"""
Unit tests for the Test Execution, Defect & Mismatch Reporting Engine (engine/reporter.py).
"""

import os
from pathlib import Path
import pytest
from engine.reporter import (
    run_test_and_report,
    generate_html_report,
    _parse_pytest_detailed_output,
    _extract_failure_blocks,
    _analyze_failure_block,
)


def test_parse_pytest_detailed_output_all_passed():
    mock_output = """
test_math.py::test_addition PASSED [ 50%]
test_math.py::test_subtraction PASSED [100%]

============================== 2 passed in 0.05s ==============================
"""
    result = _parse_pytest_detailed_output(
        raw_output=mock_output,
        exit_code=0,
        test_path=Path("test_math.py"),
        duration=0.05,
    )

    assert result["success"] is True
    assert result["summary"]["total"] == 2
    assert result["summary"]["passed"] == 2
    assert result["summary"]["failed"] == 0
    assert result["summary"]["pass_rate"] == 100.0
    assert len(result["tests"]) == 2
    assert result["tests"][0]["name"] == "test_addition"
    assert result["tests"][0]["status"] == "PASSED"


def test_parse_pytest_detailed_output_with_mismatch():
    mock_output = """
test_calc.py::TestCalc::test_add PASSED [ 50%]
test_calc.py::TestCalc::test_divide_by_zero FAILED [100%]

================================== FAILURES ===================================
_________________________ TestCalc.test_divide_by_zero _________________________
test_calc.py:15: in test_divide_by_zero
    assert divide(10, 0) == "Error"
E   assert 0 == 'Error'
=========================== short test summary info ===========================
FAILED test_calc.py::TestCalc::test_divide_by_zero - assert 0 == 'Error'
======================== 1 failed, 1 passed in 0.08s =========================
"""
    result = _parse_pytest_detailed_output(
        raw_output=mock_output,
        exit_code=1,
        test_path=Path("test_calc.py"),
        duration=0.08,
    )

    assert result["success"] is False
    assert result["summary"]["total"] == 2
    assert result["summary"]["passed"] == 1
    assert result["summary"]["failed"] == 1
    assert result["summary"]["pass_rate"] == 50.0

    failed_test = next(t for t in result["tests"] if t["status"] == "FAILED")
    assert failed_test["name"] == "test_divide_by_zero"
    assert failed_test["error_type"] == "AssertionError"
    assert failed_test["mismatch"] is not None
    assert failed_test["mismatch"]["actual"] == "0"
    assert failed_test["mismatch"]["expected"] == "'Error'"


def test_analyze_failure_block_with_exception():
    block = """
def test_null_check():
    obj = None
>   assert obj.name == "Test"
E   AttributeError: 'NoneType' object has no attribute 'name'
"""
    parsed = _analyze_failure_block(block)
    assert parsed["error_type"] == "AttributeError"
    assert "'NoneType' object has no attribute 'name'" in parsed["error_message"]


def test_generate_html_report_creates_valid_file(tmp_path):
    report_data = {
        "success": False,
        "test_file_name": "test_sample.py",
        "timestamp": "2026-10-10 20:00:00",
        "duration": 0.42,
        "summary": {
            "total": 5,
            "passed": 4,
            "failed": 1,
            "errors": 0,
            "skipped": 0,
            "pass_rate": 80.0,
        },
        "tests": [
            {"name": "test_one", "status": "PASSED"},
            {
                "name": "test_two",
                "status": "FAILED",
                "error_type": "AssertionError",
                "error_message": "assert 5 == 10",
                "location": "sample.py:12",
                "mismatch": {"expected": "10", "actual": "5"},
                "traceback": "assert 5 == 10",
            },
        ],
    }

    out_file = str(tmp_path / "test_report.html")
    generated = generate_html_report(report_data, out_file)

    assert Path(generated).exists()
    content = Path(generated).read_text(encoding="utf-8")
    assert "AI Test Quality & Mismatch Report" in content
    assert "test_sample.py" in content
    assert "80.0%" in content
    assert "test_two" in content
    assert "EXPECTED RESULT" in content
    assert "ACTUAL RESULT" in content


def test_run_test_and_report_file_not_found():
    with pytest.raises(FileNotFoundError):
        run_test_and_report("non_existent_test_file_123.py")


def test_run_test_and_report_live_demo(tmp_path):
    demo_test = Path("demo_app/generated_tests/test_payment_service_calculate_sales_tax.py")
    if not demo_test.exists():
        pytest.skip("Demo test file not generated yet")

    out_html = str(tmp_path / "report.html")
    report = run_test_and_report(str(demo_test), output_html_path=out_html)

    assert report["success"] is True
    assert report["summary"]["total"] >= 1
    assert report["summary"]["passed"] >= 1
    assert report["summary"]["failed"] == 0
    assert report["summary"]["pass_rate"] == 100.0
    assert Path(out_html).exists()
