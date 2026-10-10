"""
Tests for engine/apex_analyzer.py — Regex-based Salesforce Apex source code analysis.

Covers:
  - extract_classes: declaration, extends, implements, annotations
  - extract_methods: static, testMethod, params, return types, SOQL, DML
  - extract_file_context: sharing model, triggers, sobject references
  - detect_apex_patterns: aura_enabled, soql, dml, queueable, batchable, etc.
  - extract_apex_imports: referenced types and classes
"""

import sys
import textwrap
from pathlib import Path
import pytest

# Ensure engine is importable
ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE_DIR))

from apex_analyzer import (
    extract_classes,
    extract_methods,
    extract_file_context,
    detect_apex_patterns,
    extract_apex_imports,
)


@pytest.fixture
def sample_apex_file(tmp_path):
    """Create a sample Apex class file for testing."""
    code = textwrap.dedent("""\
        @RestResource(urlMapping='/accounts/*')
        public with sharing class AccountController extends BaseController implements Queueable, Database.AllowsCallouts {

            @AuraEnabled(cacheable=true)
            public static List<Account> getAccounts(String searchKey, Integer limitCount) {
                return [SELECT Id, Name, Industry, AnnualRevenue FROM Account WHERE Name LIKE :searchKey LIMIT :limitCount];
            }

            @AuraEnabled
            public static Account createAccount(String name, String phone) {
                if (String.isBlank(name)) {
                    throw new AuraHandledException('Name is required');
                }
                Account acc = new Account(Name = name, Phone = phone);
                insert acc;
                return acc;
            }

            public void execute(QueueableContext context) {
                List<Contact> contacts = [SELECT Id, Email FROM Contact WHERE AccountId != null];
                delete contacts;
            }

            @future(callout=true)
            public static void sendNotification(Id accountId) {
                // Future callout method
            }
        }
    """)
    p = tmp_path / "AccountController.cls"
    p.write_text(code, encoding="utf-8")
    return str(p)


@pytest.fixture
def trigger_apex_file(tmp_path):
    """Create a sample Apex trigger file for testing."""
    code = textwrap.dedent("""\
        trigger AccountTrigger on Account (before insert, after update, before delete) {
            if (Trigger.isBefore && Trigger.isInsert) {
                for (Account a : Trigger.new) {
                    if (a.Industry == null) {
                        a.Industry = 'Other';
                    }
                }
            }
        }
    """)
    p = tmp_path / "AccountTrigger.cls"
    p.write_text(code, encoding="utf-8")
    return str(p)


# ── Class Extraction ──────────────────────────────────────────────

def test_extract_classes_basic(sample_apex_file):
    classes = extract_classes(sample_apex_file)
    assert len(classes) == 1
    cls = classes[0]
    assert cls["name"] == "AccountController"
    assert cls["access"] == "public"
    assert cls["extends"] == "BaseController"
    assert "Queueable" in cls["implements"]
    assert "Database.AllowsCallouts" in cls["implements"]
    assert any(a["name"] == "RestResource" for a in cls["annotations"])


# ── Method Extraction ─────────────────────────────────────────────

def test_extract_methods_list(sample_apex_file):
    methods = extract_methods(sample_apex_file)
    method_names = [m["name"] for m in methods]
    assert "getAccounts" in method_names
    assert "createAccount" in method_names
    assert "execute" in method_names
    assert "sendNotification" in method_names


def test_extract_methods_details(sample_apex_file):
    methods = extract_methods(sample_apex_file, method_name="createAccount")
    assert len(methods) == 1
    m = methods[0]
    assert m["name"] == "createAccount"
    assert m["return_type"] == "Account"
    assert m["is_static"] is True
    assert len(m["params"]) == 2
    assert m["params"][0] == {"type": "String", "name": "name"}
    assert m["params"][1] == {"type": "String", "name": "phone"}
    assert "insert" in m["dml_operations"]
    assert "Account" in m["sobject_refs"]
    assert any(a["name"] == "AuraEnabled" for a in m["annotations"])


def test_extract_methods_soql_detection(sample_apex_file):
    methods = extract_methods(sample_apex_file, method_name="getAccounts")
    assert len(methods) == 1
    m = methods[0]
    assert len(m["soql_queries"]) == 1
    assert "SELECT Id, Name, Industry, AnnualRevenue FROM Account" in m["soql_queries"][0]


# ── File Context & Trigger ────────────────────────────────────────

def test_extract_file_context(sample_apex_file):
    ctx = extract_file_context(sample_apex_file)
    assert ctx["sharing_model"] == "with sharing"
    assert "Account" in ctx["sobject_refs"]
    assert "Contact" in ctx["sobject_refs"]
    assert "insert" in ctx["dml_operations"]
    assert "delete" in ctx["dml_operations"]
    assert ctx["is_test_class"] is False


def test_extract_trigger_context(trigger_apex_file):
    ctx = extract_file_context(trigger_apex_file)
    assert ctx["trigger"] is not None
    assert ctx["trigger"]["name"] == "AccountTrigger"
    assert ctx["trigger"]["sobject"] == "Account"
    assert "before insert" in ctx["trigger"]["events"]
    assert "after update" in ctx["trigger"]["events"]


# ── Pattern Detection ─────────────────────────────────────────────

def test_detect_apex_patterns(sample_apex_file):
    patterns = detect_apex_patterns(sample_apex_file)
    assert "soql" in patterns
    assert "dml" in patterns
    assert "aura_enabled" in patterns
    assert "queueable" in patterns
    assert "future_method" in patterns
    assert "rest_resource" in patterns
    assert "sharing_rules" in patterns


# ── Import & Reference Extraction ─────────────────────────────────

def test_extract_apex_imports(sample_apex_file):
    refs = extract_apex_imports(sample_apex_file)
    assert "Account" in refs
    assert "Contact" in refs
    assert "QueueableContext" in refs
