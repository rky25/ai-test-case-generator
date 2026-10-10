"""
Tests for engine/apex_generator.py — Apex prompt building, response cleaning, and generation logic.

Covers:
  - build_apex_prompt: class info, file context, patterns, method details
  - clean_apex_response: fence stripping, control tokens
  - generate_apex_tests: mocked API interaction and fallback
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

# Ensure engine is importable
ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE_DIR))

from apex_generator import (
    build_apex_prompt,
    clean_apex_response,
    generate_apex_tests,
    APEX_SYSTEM_PROMPT,
)


def test_build_apex_prompt_structure():
    method_info = {
        "name": "calculateTax",
        "body": "public static Decimal calculateTax(Decimal amount) { return amount * 0.1; }",
        "annotations": [],
        "soql_queries": [],
        "dml_operations": [],
        "is_static": True,
    }
    class_info = {
        "name": "TaxCalculator",
        "extends": None,
        "implements": [],
        "annotations": [],
    }
    file_context = {
        "sharing_model": "with sharing",
        "sobject_refs": ["Opportunity"],
        "dml_operations": ["insert"],
        "source": "public with sharing class TaxCalculator { ... }",
    }
    patterns = ["soql", "dml", "bulk"]

    messages = build_apex_prompt(
        method_info=method_info,
        class_info=class_info,
        file_context=file_context,
        patterns=patterns,
        references=["Account"],
    )

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "Salesforce Apex" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    user_msg = messages[1]["content"]
    assert "TaxCalculator" in user_msg
    assert "calculateTax" in user_msg
    assert "with sharing" in user_msg
    assert "Opportunity" in user_msg


def test_clean_apex_response_markdown():
    raw = "```apex\n@isTest\nprivate class FooTest {}\n```"
    cleaned = clean_apex_response(raw)
    assert cleaned == "@isTest\nprivate class FooTest {}"

    raw_java = "```java\n@isTest\nprivate class FooTest {}\n```"
    assert clean_apex_response(raw_java) == "@isTest\nprivate class FooTest {}"


@patch("apex_generator.call_api_with_fallback")
def test_generate_apex_tests_mocked(mock_api):
    mock_api.return_value = "```apex\n@isTest\nprivate class MyTest {}\n```"
    res = generate_apex_tests(
        method_info={"name": "myMethod", "body": "void myMethod(){}"},
        class_info={"name": "MyClass"},
        file_context={},
        api_key="test-key",
    )
    assert res == "@isTest\nprivate class MyTest {}"
    mock_api.assert_called_once()
