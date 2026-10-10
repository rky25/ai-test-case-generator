"""
Tests for engine/apex_validator.py — Apex test code validation.

Covers:
  - validate_apex_syntax: brace/paren/bracket balancing, string and comment handling
  - validate_apex_test_structure: @isTest annotation, test method detection
  - validate_apex_best_practices: Test.startTest/stopTest, assertions, SeeAllData checks
  - validate_apex_all: comprehensive end-to-end validator
"""

import sys
from pathlib import Path
import pytest

# Ensure engine is importable
ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE_DIR))

from apex_validator import (
    validate_apex_syntax,
    validate_apex_test_structure,
    validate_apex_best_practices,
    validate_apex_all,
)


VALID_APEX_TEST = """\
@isTest
private class AccountServiceTest {

    @testSetup
    static void setup() {
        Account testAcc = new Account(Name = 'Test Corp');
        insert testAcc;
    }

    @isTest
    static void testGetAccount_Success() {
        Test.startTest();
        Account acc = AccountService.getAccount('Test Corp');
        Test.stopTest();

        System.assertNotEquals(null, acc, 'Account should be found');
        System.assertEquals('Test Corp', acc.Name, 'Account name should match');
    }

    @isTest
    static void testCreateAccount_Bulk() {
        List<Account> accounts = new List<Account>();
        for (Integer i = 0; i < 200; i++) {
            accounts.add(new Account(Name = 'Bulk ' + i));
        }

        Test.startTest();
        insert accounts;
        Test.stopTest();

        System.assertEquals(200, [SELECT count() FROM Account WHERE Name LIKE 'Bulk %']);
    }
}
"""


def test_syntax_valid():
    res = validate_apex_syntax(VALID_APEX_TEST)
    assert res["valid"] is True
    assert res["error"] is None


def test_syntax_unbalanced_braces():
    bad_code = "@isTest class MyTest { static void t() { "
    res = validate_apex_syntax(bad_code)
    assert res["valid"] is False
    assert "brace" in res["error"].lower()


def test_syntax_unmatched_closing_brace():
    bad_code = "@isTest class MyTest { static void t() {} } }"
    res = validate_apex_syntax(bad_code)
    assert res["valid"] is False
    assert "Unmatched closing brace" in res["error"]


def test_syntax_unbalanced_parentheses():
    bad_code = "@isTest class MyTest { static void t() { System.assert(true; } }"
    res = validate_apex_syntax(bad_code)
    assert res["valid"] is False


def test_syntax_string_with_braces():
    code_with_braces_in_string = """
    @isTest
    class MyTest {
        static void t() {
            String s = '{ this is not a block }';
            System.assert(true);
        }
    }
    """
    res = validate_apex_syntax(code_with_braces_in_string)
    assert res["valid"] is True


def test_structure_valid():
    res = validate_apex_test_structure(VALID_APEX_TEST)
    assert res["valid"] is True
    assert res["test_count"] >= 2


def test_structure_missing_istest():
    code_no_istest = """
    public class RegularClass {
        public static void regularMethod() {}
    }
    """
    res = validate_apex_test_structure(code_no_istest)
    assert res["valid"] is False
    assert "Missing @isTest" in res["error"]


def test_structure_no_test_methods():
    code_no_methods = """
    @isTest
    private class EmptyTest {
    }
    """
    res = validate_apex_test_structure(code_no_methods)
    assert res["valid"] is False
    assert "No test methods found" in res["error"]


def test_best_practices_valid():
    res = validate_apex_best_practices(VALID_APEX_TEST)
    assert res["valid"] is True
    assert len(res["warnings"]) == 0


def test_best_practices_warnings():
    lazy_test = """
    @isTest
    private class BadTest {
        @isTest(SeeAllData=true)
        static void testNothing() {
            // no startTest, no stopTest, no asserts
        }
    }
    """
    res = validate_apex_best_practices(lazy_test)
    assert res["valid"] is False
    assert any("startTest" in w for w in res["warnings"])
    assert any("stopTest" in w for w in res["warnings"])
    assert any("assert" in w for w in res["warnings"])
    assert any("SeeAllData" in w for w in res["warnings"])


def test_validate_apex_all():
    res = validate_apex_all(VALID_APEX_TEST)
    assert res["valid"] is True
    assert res["syntax"]["valid"] is True
    assert res["structure"]["valid"] is True
    assert res["structure"]["test_count"] >= 2
