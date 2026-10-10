"""
Tests for engine/apex_main.py — CLI entry-point and generation orchestration for Apex.

Covers:
  - _make_test_filename and _make_test_filename_per_method
  - _build_header
  - run_apex: file validation, method filtering, mocked generation
"""

import sys
import textwrap
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

# Ensure engine is importable
ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE_DIR))

from apex_main import (
    _make_test_filename,
    _make_test_filename_per_method,
    _build_header,
    run_apex,
)


def test_make_test_filename():
    assert _make_test_filename("AccountService.cls", "AccountService") == "AccountServiceTest.cls"
    assert _make_test_filename("path/to/PaymentGateway.cls", "PaymentGateway") == "PaymentGatewayTest.cls"


def test_make_test_filename_per_method():
    assert (
        _make_test_filename_per_method("AccountService.cls", "createAccount")
        == "AccountService_createAccountTest.cls"
    )


def test_build_header():
    header = _build_header("force-app/main/default/classes/AccountService.cls", "createAccount")
    assert "Auto-generated test cases" in header
    assert "AccountService.cls" in header
    assert "createAccount" in header


@pytest.fixture
def sample_cls_file(tmp_path):
    code = textwrap.dedent("""\
        public with sharing class LeadService {
            public static Lead createLead(String lastName, String company) {
                Lead l = new Lead(LastName = lastName, Company = company);
                insert l;
                return l;
            }
        }
    """)
    p = tmp_path / "LeadService.cls"
    p.write_text(code, encoding="utf-8")
    return str(p)


def test_run_apex_file_not_found():
    with pytest.raises(FileNotFoundError):
        run_apex("non_existent.cls", api_key="test-key")


def test_run_apex_invalid_extension(tmp_path):
    p = tmp_path / "invalid.txt"
    p.write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError, match="Expected an Apex file"):
        run_apex(str(p), api_key="test-key")


@patch("apex_main.generate_apex_tests")
def test_run_apex_success(mock_generate, sample_cls_file, tmp_path):
    mock_generate.return_value = """\
@isTest
private class LeadServiceTest {
    @isTest
    static void testCreateLead() {
        Test.startTest();
        Lead l = LeadService.createLead('Smith', 'Acme');
        Test.stopTest();
        System.assertNotEquals(null, l.Id);
    }
}
"""
    out_dir = str(tmp_path / "tests")
    res = run_apex(
        file_path=sample_cls_file,
        api_key="test-key",
        output_dir=out_dir,
        validate=False,
    )

    assert "results" in res
    assert len(res["results"]) >= 1
    assert res["results"][0]["status"] == "ok"
    generated_file = Path(res["results"][0]["file"])
    assert generated_file.exists()
    content = generated_file.read_text(encoding="utf-8")
    assert "LeadServiceTest" in content
    assert "testCreateLead" in content
