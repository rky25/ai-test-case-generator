"""
AI-powered Salesforce Apex test case generator.
Constructs Apex-specific prompts and calls an OpenAI-compatible
chat completions API. Uses the same API infrastructure as the
Python generator but with Salesforce-specific system prompts.

Zero external dependencies — stdlib only.
"""

import json
import sys
import re
from typing import Optional

# Reuse the core API call infrastructure from generator.py
from generator import (
    call_api_with_fallback,
    clean_response,
    parse_api_keys,
)


# ── Apex System Prompt ────────────────────────────────────────────
APEX_SYSTEM_PROMPT = """\
You are an expert enterprise Salesforce Apex test engineer. Your ONLY job is to
produce production-grade Apex test classes for a given Apex class or method.

Rules you MUST follow:
1.  Output ONLY valid Apex code. No markdown fences, no conversational prose.
2.  Start with the @isTest annotation on the test class.
3.  Name the test class:  <OriginalClassName>Test  (e.g. AccountServiceTest).
4.  Give every test method a clear, descriptive name:
        testMethodName_Scenario  (e.g. testCreateAccount_ValidInput)
5.  Cover ALL of these categories when applicable:
      • Happy path – normal expected inputs and outputs.
      • Bulk testing – test with 200+ records to verify governor limit compliance.
      • Edge cases – empty strings, null values, empty lists, boundary values.
      • Negative cases – invalid inputs that should throw exceptions.
      • Error / exception cases – test DmlException, QueryException, custom exceptions.
      • Security testing – verify sharing rules are respected (if with sharing).
      • Profile/Permission testing – test with different user contexts if applicable.
6.  Use @TestSetup for common test data creation across methods.
7.  ALWAYS wrap test logic inside Test.startTest() and Test.stopTest().
8.  Use System.assert, System.assertEquals, System.assertNotEquals with descriptive messages.
9.  Generate between 6 and 20 comprehensive test methods depending on complexity.
10. Governor Limits Awareness:
      • If the code uses SOQL queries, test bulk scenarios (200+ records).
      • If the code performs DML, verify bulk DML handling.
      • Use Test.startTest()/Test.stopTest() to reset governor limits.
11. Mocking & Callouts:
      • If the class makes HTTP callouts, implement HttpCalloutMock.
      • If using web services, implement WebServiceMock.
      • Mock external API responses for both success AND failure scenarios.
12. Async Apex Testing:
      • For @future methods: call the method, then Test.stopTest() to force execution.
      • For Queueable: System.enqueueJob(), then Test.stopTest().
      • For Batch: Database.executeBatch(), then Test.stopTest().
      • For Schedulable: Use System.schedule() with a cron expression.
13. Data Creation:
      • Create ALL test data within the test class (no reliance on org data).
      • Use @TestSetup to share test data across test methods.
      • Follow the pattern: create parent objects first, then child objects.
      • Set all required fields when creating SObjects.
14. Platform Events:
      • If the code publishes events, use Test.startTest()/Test.stopTest()
        and EventBus.publish(), then verify with Test.getEventBus().deliver().
15. Trigger Testing:
      • If testing triggers, test all trigger events (before/after insert/update/delete).
      • Test both single record and bulk (200+) record scenarios.
16. Best Practices:
      • Do NOT use @isTest(SeeAllData=true) unless absolutely necessary.
      • Use System.runAs() to test with different user contexts.
      • Assert specific field values, not just record counts.
      • Test both positive and negative SOQL results.
      • Verify that exceptions contain expected error messages.
"""


def build_apex_prompt(
    method_info: dict,
    class_info: dict,
    file_context: dict,
    patterns: Optional[list[str]] = None,
    references: Optional[list[str]] = None,
) -> list[dict]:
    """
    Build the messages list for the chat completions API with
    rich Salesforce/Apex context.
    """
    parts = []

    # Class-level context
    if class_info:
        parts.append(f"Apex Class: {class_info.get('name', 'Unknown')}")
        if class_info.get("extends"):
            parts.append(f"Extends: {class_info['extends']}")
        if class_info.get("implements"):
            parts.append(f"Implements: {', '.join(class_info['implements'])}")
        if class_info.get("annotations"):
            ann_strs = [
                f"@{a['name']}({a['params']})" if a["params"] else f"@{a['name']}"
                for a in class_info["annotations"]
            ]
            parts.append(f"Class Annotations: {', '.join(ann_strs)}")

    # File-level context
    if file_context:
        if file_context.get("sharing_model"):
            parts.append(f"Sharing Model: {file_context['sharing_model']}")
        if file_context.get("trigger"):
            t = file_context["trigger"]
            parts.append(
                f"Trigger: {t['name']} on {t['sobject']} "
                f"({', '.join(t['events'])})"
            )
        if file_context.get("sobject_refs"):
            parts.append(f"SObjects Used: {', '.join(file_context['sobject_refs'])}")
        if file_context.get("dml_operations"):
            parts.append(f"DML Operations: {', '.join(file_context['dml_operations'])}")

    # Pattern-specific instructions
    if patterns:
        pattern_rules = []
        if "soql" in patterns:
            pattern_rules.append(
                "• SOQL: Test queries with 0, 1, and 200+ records. "
                "Verify query results and handle empty result sets."
            )
        if "dml" in patterns:
            pattern_rules.append(
                "• DML: Test insert/update/delete with single and bulk records. "
                "Test DmlException scenarios (required fields, validation rules)."
            )
        if "aura_enabled" in patterns:
            pattern_rules.append(
                "• @AuraEnabled: Test both success and AuraHandledException scenarios. "
                "Verify return values match expected data structure."
            )
        if "http_callout" in patterns or "mock_callout" in patterns:
            pattern_rules.append(
                "• HTTP Callouts: Implement HttpCalloutMock interface. "
                "Test 200 success, 400 bad request, 500 server error, and timeout scenarios."
            )
        if "future_method" in patterns:
            pattern_rules.append(
                "• @future: Call the method, then Test.stopTest() to execute synchronously. "
                "Verify the async operation completed correctly."
            )
        if "queueable" in patterns:
            pattern_rules.append(
                "• Queueable: Use System.enqueueJob() inside Test.startTest()/Test.stopTest(). "
                "Verify job execution and chaining if applicable."
            )
        if "batchable" in patterns:
            pattern_rules.append(
                "• Batch Apex: Use Database.executeBatch() with explicit batch size. "
                "Test start(), execute(), and finish() methods. Test with 200+ records."
            )
        if "schedulable" in patterns:
            pattern_rules.append(
                "• Schedulable: Use System.schedule() with a test cron expression. "
                "Verify the job is scheduled and executes correctly."
            )
        if "trigger_handler" in patterns:
            pattern_rules.append(
                "• Triggers: Test all trigger contexts (before/after insert/update/delete). "
                "Test with bulk records (200+). Verify trigger.new and trigger.old behavior."
            )
        if "invocable_method" in patterns:
            pattern_rules.append(
                "• @InvocableMethod: Test with valid input lists. "
                "Verify return values. Test with empty and null inputs."
            )
        if "platform_event" in patterns:
            pattern_rules.append(
                "• Platform Events: Use EventBus.publish() inside test context. "
                "Call Test.getEventBus().deliver() to process events."
            )
        if "sharing_rules" in patterns:
            pattern_rules.append(
                "• Sharing: Use System.runAs() to test record access with different users/profiles. "
                "Verify that sharing rules are correctly enforced."
            )
        if "exception_handling" in patterns:
            pattern_rules.append(
                "• Exception Handling: Test that expected exceptions are thrown with correct messages. "
                "Use try/catch in tests with System.assert(false) after the line that should throw."
            )

        if pattern_rules:
            parts.append(
                "Salesforce Pattern-Specific Testing Guidelines:\n"
                + "\n".join(pattern_rules)
            )

    # Referenced classes
    if references:
        parts.append(
            "Referenced Classes/Types in this file:\n"
            + ", ".join(references)
            + "\nMock or stub these dependencies where appropriate."
        )

    # Full source code for context
    if file_context.get("source"):
        parts.append(
            f"Full Apex class source code:\n```apex\n{file_context['source']}\n```"
        )

    # Method-specific context
    if method_info:
        parts.append(
            f"Method to generate tests for: {method_info['name']}\n"
            f"```apex\n{method_info['body']}\n```"
        )

        if method_info.get("annotations"):
            ann_strs = [
                f"@{a['name']}({a['params']})" if a["params"] else f"@{a['name']}"
                for a in method_info["annotations"]
            ]
            parts.append(f"Method Annotations: {', '.join(ann_strs)}")

        if method_info.get("soql_queries"):
            parts.append(
                "SOQL Queries in this method:\n"
                + "\n".join(f"  {q}" for q in method_info["soql_queries"])
            )

        if method_info.get("dml_operations"):
            parts.append(
                f"DML Operations: {', '.join(method_info['dml_operations'])}"
            )

        if method_info.get("is_static"):
            parts.append("NOTE: This is a STATIC method. Call directly via ClassName.methodName().")

    user_content = "\n\n".join(parts)

    return [
        {"role": "system", "content": APEX_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def clean_apex_response(raw: str) -> str:
    """
    Strip markdown code fences, control tokens, and
    clean up the AI response for Apex code.
    """
    text = clean_response(raw)

    # Remove any ```apex or ```java fences that clean_response might miss
    text = re.sub(r"^```(?:apex|java|cls)?\s*\n?", "", text, flags=re.MULTILINE)
    if text.endswith("```"):
        text = text[:-3]

    return text.strip()


def generate_apex_tests(
    method_info: dict,
    class_info: dict,
    file_context: dict,
    api_key: str,
    base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai",
    model: str = "gemini-2.5-flash",
    patterns: Optional[list[str]] = None,
    references: Optional[list[str]] = None,
) -> str:
    """
    End-to-end: build Apex prompt → call API (with fallback) → return clean test code.

    api_key can be a single key or comma-separated keys for fallback.
    """
    messages = build_apex_prompt(
        method_info=method_info,
        class_info=class_info,
        file_context=file_context,
        patterns=patterns,
        references=references,
    )
    keys = parse_api_keys(api_key)
    raw = call_api_with_fallback(keys, base_url, model, messages)
    return clean_apex_response(raw)


# ── Standalone test ───────────────────────────────────────────────
if __name__ == "__main__":
    print("apex_generator.py loaded - use via apex_main.py or import directly.")
