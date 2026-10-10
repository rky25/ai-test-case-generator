"""
Apex test code validator.

Validates generated Apex test code for:
  1. Brace matching and basic syntax
  2. Required Apex test patterns (@isTest, Test.startTest, assertions)
  3. Test method structure and naming conventions
  4. Salesforce best practices compliance

Zero external dependencies — stdlib only.
"""

import re
import sys
import json
from pathlib import Path
from typing import Optional


def validate_apex_syntax(code: str) -> dict:
    """
    Check that generated Apex test code has valid basic syntax.
    Since we can't AST-parse Apex in Python, we check:
    - Balanced braces, parentheses, brackets
    - No obvious syntax errors
    - Valid class structure

    Returns:
        {"valid": True} or {"valid": False, "error": "...", "line": N}
    """
    # Check balanced braces
    brace_count = 0
    paren_count = 0
    bracket_count = 0
    in_string = False
    in_line_comment = False
    in_block_comment = False
    string_char = None

    lines = code.splitlines()
    for line_num, line in enumerate(lines, 1):
        i = 0
        while i < len(line):
            ch = line[i]

            # Handle comments
            if in_block_comment:
                if ch == "*" and i + 1 < len(line) and line[i + 1] == "/":
                    in_block_comment = False
                    i += 2
                    continue
                i += 1
                continue

            if in_line_comment:
                break  # rest of line is comment

            if ch == "/" and i + 1 < len(line):
                if line[i + 1] == "/":
                    in_line_comment = True
                    break
                elif line[i + 1] == "*":
                    in_block_comment = True
                    i += 2
                    continue

            # Handle strings
            if in_string:
                if ch == "\\" and i + 1 < len(line):
                    i += 2  # skip escaped character
                    continue
                if ch == string_char:
                    in_string = False
                i += 1
                continue

            if ch in ("'",):
                in_string = True
                string_char = ch
                i += 1
                continue

            # Count braces
            if ch == "{":
                brace_count += 1
            elif ch == "}":
                brace_count -= 1
                if brace_count < 0:
                    return {
                        "valid": False,
                        "error": "Unmatched closing brace '}'",
                        "line": line_num,
                    }
            elif ch == "(":
                paren_count += 1
            elif ch == ")":
                paren_count -= 1
                if paren_count < 0:
                    return {
                        "valid": False,
                        "error": "Unmatched closing parenthesis ')'",
                        "line": line_num,
                    }
            elif ch == "[":
                bracket_count += 1
            elif ch == "]":
                bracket_count -= 1
                if bracket_count < 0:
                    return {
                        "valid": False,
                        "error": "Unmatched closing bracket ']'",
                        "line": line_num,
                    }

            i += 1

        in_line_comment = False

    if brace_count != 0:
        return {
            "valid": False,
            "error": f"Unbalanced braces: {brace_count} unclosed '{{' remaining",
            "line": len(lines),
        }
    if paren_count != 0:
        return {
            "valid": False,
            "error": f"Unbalanced parentheses: {paren_count} unclosed '(' remaining",
            "line": len(lines),
        }

    return {"valid": True, "error": None, "line": None}


def validate_apex_test_structure(code: str) -> dict:
    """
    Verify the generated code contains proper Apex test structure:
    - @isTest class annotation
    - Test methods with @isTest or testMethod keyword
    - System.assert* calls

    Returns:
        {"valid": True, "test_count": N} or {"valid": False, "error": "..."}
    """
    # Check for @isTest class annotation
    has_is_test = bool(re.search(r"@isTest", code, re.IGNORECASE))

    # Find test methods
    test_methods = re.findall(
        r"(?:@isTest|testMethod)\s+.*?(?:static\s+)?(?:void|[\w<>]+)\s+(\w+)\s*\(",
        code,
        re.IGNORECASE | re.DOTALL,
    )

    # Also match: static testMethod void methodName
    test_methods_alt = re.findall(
        r"(?:static\s+)?testMethod\s+void\s+(\w+)\s*\(",
        code,
        re.IGNORECASE,
    )

    # Also match @isTest above a method
    test_methods_annotated = re.findall(
        r"@isTest\s+(?:static\s+)?void\s+(\w+)\s*\(",
        code,
        re.IGNORECASE,
    )

    all_test_methods = set(test_methods + test_methods_alt + test_methods_annotated)
    test_count = len(all_test_methods)

    if not has_is_test:
        return {
            "valid": False,
            "test_count": test_count,
            "error": "Missing @isTest annotation on test class",
        }

    if test_count == 0:
        return {
            "valid": False,
            "test_count": 0,
            "error": "No test methods found (expected @isTest or testMethod annotated methods)",
        }

    return {"valid": True, "test_count": test_count, "error": None}


def validate_apex_best_practices(code: str) -> dict:
    """
    Check for Salesforce testing best practices:
    - Test.startTest() / Test.stopTest() usage
    - System.assert* calls present
    - No SeeAllData=true (anti-pattern)
    - Data creation inside tests

    Returns:
        {"valid": True, "warnings": [...]}
    """
    warnings = []

    # Check for Test.startTest/stopTest
    has_start_test = bool(re.search(r"Test\.startTest\s*\(\s*\)", code))
    has_stop_test = bool(re.search(r"Test\.stopTest\s*\(\s*\)", code))

    if not has_start_test:
        warnings.append(
            "Missing Test.startTest() — recommended for governor limit reset"
        )
    if not has_stop_test:
        warnings.append(
            "Missing Test.stopTest() — required to execute async operations"
        )

    # Check for assertions
    has_assertions = bool(
        re.search(
            r"System\.(assert|assertEquals|assertNotEquals)\s*\(",
            code,
            re.IGNORECASE,
        )
    )
    if not has_assertions:
        warnings.append(
            "No System.assert* calls found — tests should verify expected outcomes"
        )

    # Check for SeeAllData=true (anti-pattern)
    if re.search(r"SeeAllData\s*=\s*true", code, re.IGNORECASE):
        warnings.append(
            "Uses @isTest(SeeAllData=true) — avoid this; create test data explicitly"
        )

    # Check for hardcoded IDs
    hardcoded_ids = re.findall(r"['\"]([a-zA-Z0-9]{15}|[a-zA-Z0-9]{18})['\"]", code)
    sf_id_pattern = re.compile(r"^[0-9a-zA-Z]{15}$|^[0-9a-zA-Z]{18}$")
    for potential_id in hardcoded_ids:
        # Rough check: Salesforce IDs start with specific 3-char prefixes
        if potential_id[:3] in ("001", "003", "005", "006", "00Q", "500", "a0"):
            warnings.append(
                f"Possible hardcoded Salesforce ID detected: '{potential_id}' — "
                "create records dynamically instead"
            )
            break

    return {"valid": len(warnings) == 0, "warnings": warnings}


def validate_apex_all(code: str) -> dict:
    """
    Run all Apex validations and return a combined result.

    Returns:
        {
            "valid": bool,
            "syntax": {...},
            "structure": {...},
            "best_practices": {...},
        }
    """
    syntax = validate_apex_syntax(code)
    structure = (
        validate_apex_test_structure(code)
        if syntax["valid"]
        else {"valid": False, "test_count": 0, "error": "Syntax error"}
    )
    best_practices = (
        validate_apex_best_practices(code)
        if syntax["valid"]
        else {"valid": False, "warnings": []}
    )

    overall = syntax["valid"] and structure["valid"]

    return {
        "valid": overall,
        "syntax": syntax,
        "structure": structure,
        "best_practices": best_practices,
    }


# ── Standalone usage ──────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python apex_validator.py <test_file.cls>")
        sys.exit(1)

    test_path = Path(sys.argv[1])
    if not test_path.is_file():
        print(f"Error: file not found: {sys.argv[1]}", file=sys.stderr)
        sys.exit(1)

    code = test_path.read_text(encoding="utf-8")
    result = validate_apex_all(code)
    print(json.dumps(result, indent=2))

    if not result["valid"]:
        sys.exit(1)
