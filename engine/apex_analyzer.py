"""
Regex-based Salesforce Apex source code analyzer.
Extracts class definitions, method signatures, annotations,
SOQL queries, DML operations, and SObject references.

Since Apex is not Python, we use regular expressions instead of AST.
Zero external dependencies — stdlib only.
"""

import re
import sys
import json
from pathlib import Path
from typing import Optional


# ── Regex patterns ────────────────────────────────────────────────

# Match class declarations: public class Foo extends Bar implements IBaz {
_CLASS_RE = re.compile(
    r"(?P<annotations>(?:\s*@\w+(?:\([^)]*\))?\s*)*)"
    r"\s*(?P<access>public|private|global|protected)?"
    r"\s*(?P<modifiers>(?:(?:virtual|abstract|with\s+sharing|without\s+sharing|inherited\s+sharing)\s+)*)"
    r"class\s+(?P<name>\w+)"
    r"(?:\s+extends\s+(?P<extends>[\w.]+))?"
    r"(?:\s+implements\s+(?P<implements>[\w\s,.]+))?"
    r"\s*\{",
    re.IGNORECASE | re.MULTILINE,
)

# Match method declarations
_METHOD_RE = re.compile(
    r"(?P<annotations>(?:\s*@\w+(?:\([^)]*\))?\s*)*)"
    r"\s*(?P<access>public|private|global|protected)?"
    r"\s*(?P<modifiers>(?:(?:static|virtual|abstract|override|testMethod)\s+)*)"
    r"(?P<return_type>[\w<>,\s\[\]]+?)\s+"
    r"(?P<name>\w+)\s*\("
    r"(?P<params>[^)]*)"
    r"\)\s*\{",
    re.IGNORECASE | re.MULTILINE,
)

# Match SOQL queries
_SOQL_RE = re.compile(
    r"\[\s*SELECT\s+.+?\s+FROM\s+(?P<sobject>\w+).*?\]",
    re.IGNORECASE | re.DOTALL,
)

# Match DML statements
_DML_RE = re.compile(
    r"\b(?P<operation>insert|update|upsert|delete|undelete|merge)\s+",
    re.IGNORECASE,
)

# Match SObject instantiation: new Account(...)
_SOBJECT_NEW_RE = re.compile(
    r"new\s+(?P<sobject>[A-Z]\w+)\s*\(",
    re.MULTILINE,
)

# Match trigger declarations
_TRIGGER_RE = re.compile(
    r"trigger\s+(?P<name>\w+)\s+on\s+(?P<sobject>\w+)\s*\("
    r"(?P<events>[^)]+)\)",
    re.IGNORECASE,
)

# Common Salesforce annotations
_ANNOTATION_RE = re.compile(
    r"@(\w+)(?:\(([^)]*)\))?",
    re.IGNORECASE,
)

# Known Salesforce SObject types (common ones for detection)
KNOWN_SOBJECTS = {
    "Account", "Contact", "Lead", "Opportunity", "Case", "Task",
    "Event", "User", "Profile", "Role", "Campaign", "Contract",
    "Order", "OrderItem", "Product2", "Pricebook2", "PricebookEntry",
    "Quote", "QuoteLineItem", "Asset", "ContentDocument",
    "ContentVersion", "Attachment", "Note", "EmailMessage",
    "FeedItem", "Group", "GroupMember", "PermissionSet",
    "PermissionSetAssignment", "CustomObject__c",
}


def extract_classes(filepath: str) -> list[dict]:
    """
    Parse an Apex .cls file and extract class-level information.

    Returns:
        List of dicts describing each class found.
    """
    source = Path(filepath).read_text(encoding="utf-8")
    classes = []

    for match in _CLASS_RE.finditer(source):
        annotations = _parse_annotations(match.group("annotations") or "")
        implements = match.group("implements")
        impl_list = (
            [i.strip() for i in implements.split(",")]
            if implements else []
        )

        classes.append({
            "name": match.group("name"),
            "access": (match.group("access") or "").strip(),
            "modifiers": (match.group("modifiers") or "").strip(),
            "extends": match.group("extends"),
            "implements": impl_list,
            "annotations": annotations,
            "start_pos": match.start(),
        })

    return classes


def extract_methods(
    filepath: str,
    method_name: Optional[str] = None,
) -> list[dict]:
    """
    Parse an Apex .cls file and extract method information.

    Args:
        filepath: Path to the .cls file.
        method_name: If provided, extract only this specific method.

    Returns:
        List of dicts, each describing one method.
    """
    source = Path(filepath).read_text(encoding="utf-8")
    source_lines = source.splitlines()
    methods = []

    for match in _METHOD_RE.finditer(source):
        name = match.group("name")

        # Skip control statements, constructor-like patterns, and class declarations
        if name.lower() in (
            "if", "else", "for", "while", "do", "switch", "when",
            "catch", "try", "finally", "return", "throw", "break", "continue"
        ):
            continue

        return_type = (match.group("return_type") or "").strip()
        if return_type.lower() in ("class", "interface", "enum", "trigger"):
            continue

        if method_name and name != method_name:
            continue

        annotations = _parse_annotations(match.group("annotations") or "")
        params = _parse_params(match.group("params") or "")
        modifiers = (match.group("modifiers") or "").strip()

        # Extract method body (find matching closing brace)
        body_start = match.end() - 1  # position of opening {
        body = _extract_body(source, body_start)
        start_line = source[:match.start()].count("\n") + 1
        end_line = source[:body_start + len(body)].count("\n") + 1

        # Detect SOQL queries in method body
        soql_queries = _extract_soql(body)

        # Detect DML operations in method body
        dml_ops = _extract_dml(body)

        # Detect SObject references
        sobjects = _extract_sobject_refs(body)

        # Detect if method is a test method
        is_test = (
            "@isTest" in [a["name"] for a in annotations]
            or "testMethod" in modifiers.lower()
        )

        methods.append({
            "name": name,
            "access": (match.group("access") or "").strip(),
            "modifiers": modifiers,
            "return_type": return_type,
            "params": params,
            "annotations": annotations,
            "body": body,
            "start_line": start_line,
            "end_line": end_line,
            "is_static": "static" in modifiers.lower(),
            "is_test": is_test,
            "soql_queries": soql_queries,
            "dml_operations": dml_ops,
            "sobject_refs": sobjects,
        })

    return methods


def extract_file_context(filepath: str) -> dict:
    """
    Extract high-level Apex file context: class info, annotations,
    sharing settings, SOQL, DML, and SObject usage.
    """
    source = Path(filepath).read_text(encoding="utf-8")

    classes = extract_classes(filepath)
    all_soql = _extract_soql(source)
    all_dml = _extract_dml(source)
    all_sobjects = _extract_sobject_refs(source)

    # Detect if it's a trigger
    trigger_match = _TRIGGER_RE.search(source)
    trigger_info = None
    if trigger_match:
        events = [e.strip() for e in trigger_match.group("events").split(",")]
        trigger_info = {
            "name": trigger_match.group("name"),
            "sobject": trigger_match.group("sobject"),
            "events": events,
        }

    # Detect sharing model
    sharing = None
    if "with sharing" in source.lower():
        sharing = "with sharing"
    elif "without sharing" in source.lower():
        sharing = "without sharing"
    elif "inherited sharing" in source.lower():
        sharing = "inherited sharing"

    return {
        "classes": classes,
        "trigger": trigger_info,
        "sharing_model": sharing,
        "soql_queries": all_soql,
        "dml_operations": list(set(all_dml)),
        "sobject_refs": list(set(all_sobjects)),
        "is_test_class": "@isTest" in source or "testMethod" in source.lower(),
        "source": source,
    }


def detect_apex_patterns(filepath: str) -> list[str]:
    """
    Detect Salesforce-specific patterns used in the file.
    Helps guide the AI with relevant test generation strategies.
    """
    source = Path(filepath).read_text(encoding="utf-8")
    patterns = set()

    pattern_checks = {
        "soql": r"\[\s*SELECT\s+",
        "dml": r"\b(?:insert|update|upsert|delete|undelete|merge)\s+",
        "aura_enabled": r"@AuraEnabled",
        "rest_resource": r"@RestResource",
        "http_callout": r"@HttpGet|@HttpPost|@HttpPut|@HttpDelete|@HttpPatch",
        "future_method": r"@future",
        "queueable": r"implements\s+Queueable",
        "schedulable": r"implements\s+Schedulable",
        "batchable": r"implements\s+Database\.Batchable",
        "invocable_method": r"@InvocableMethod",
        "invocable_variable": r"@InvocableVariable",
        "platform_event": r"EventBus\.publish",
        "custom_metadata": r"__mdt\b",
        "custom_setting": r"getInstance\(\)|getOrgDefaults\(\)",
        "custom_object": r"__c\b",
        "trigger_handler": r"trigger\s+\w+\s+on",
        "exception_handling": r"\bcatch\s*\(",
        "governor_limits": r"Limits\.\w+",
        "test_setup": r"@TestSetup|@testSetup",
        "mock_callout": r"HttpCalloutMock|WebServiceMock",
        "email_service": r"Messaging\.SingleEmailMessage|Messaging\.sendEmail",
        "approval_process": r"Approval\.ProcessSubmitRequest",
        "sharing_rules": r"with\s+sharing|without\s+sharing",
    }

    for pattern_name, regex in pattern_checks.items():
        if re.search(regex, source, re.IGNORECASE):
            patterns.add(pattern_name)

    return sorted(list(patterns))


def extract_apex_imports(filepath: str) -> list[str]:
    """
    Apex doesn't have import statements like Python,
    but we can detect class references and dependencies.
    Returns a list of referenced classes/types.
    """
    source = Path(filepath).read_text(encoding="utf-8")
    refs = set()

    # Type references in method signatures and variable declarations
    type_re = re.compile(
        r"(?:List|Set|Map)\s*<\s*([\w.]+?)(?:\s*,\s*([\w.]+?))?\s*>",
        re.IGNORECASE,
    )
    for m in type_re.finditer(source):
        refs.add(m.group(1))
        if m.group(2):
            refs.add(m.group(2))

    # Direct class references (Type.method patterns)
    class_ref_re = re.compile(r"\b([A-Z]\w+)\.\w+\(")
    for m in class_ref_re.finditer(source):
        name = m.group(1)
        if name not in ("System", "Test", "Assert", "String", "Integer",
                        "Decimal", "Double", "Boolean", "Date", "Datetime",
                        "Time", "Id", "Blob", "Long"):
            refs.add(name)

    # Method parameter types and return types
    methods = extract_methods(filepath)
    primitive_types = {
        "void", "String", "Integer", "Decimal", "Double", "Boolean",
        "Date", "Datetime", "Time", "Id", "Blob", "Long", "Object"
    }
    for meth in methods:
        ret = meth.get("return_type", "").strip()
        clean_ret = re.sub(r"^(?:List|Set|Map)\s*<\s*|\s*>$", "", ret).strip()
        if clean_ret and clean_ret not in primitive_types:
            refs.add(clean_ret)
        for p in meth.get("params", []):
            ptype = p.get("type", "").strip()
            clean_ptype = re.sub(r"^(?:List|Set|Map)\s*<\s*|\s*>$", "", ptype).strip()
            if clean_ptype and clean_ptype not in primitive_types:
                refs.add(clean_ptype)

    return sorted(list(refs))


# ── Internal helpers ──────────────────────────────────────────────

def _parse_annotations(text: str) -> list[dict]:
    """Parse Apex annotations like @isTest, @AuraEnabled(cacheable=true)."""
    annotations = []
    for match in _ANNOTATION_RE.finditer(text):
        annotations.append({
            "name": match.group(1),
            "params": match.group(2) or "",
        })
    return annotations


def _parse_params(params_str: str) -> list[dict]:
    """Parse method parameters: 'String name, Integer count' -> list of dicts."""
    params = []
    if not params_str.strip():
        return params

    for param in params_str.split(","):
        param = param.strip()
        if not param:
            continue

        # Handle generic types like List<String>
        # Find the last space that isn't inside angle brackets
        depth = 0
        last_space = -1
        for i, ch in enumerate(param):
            if ch == "<":
                depth += 1
            elif ch == ">":
                depth -= 1
            elif ch == " " and depth == 0:
                last_space = i

        if last_space > 0:
            param_type = param[:last_space].strip()
            param_name = param[last_space + 1:].strip()
        else:
            param_type = param
            param_name = ""

        params.append({
            "type": param_type,
            "name": param_name,
        })

    return params


def _extract_body(source: str, start_pos: int) -> str:
    """
    Extract a brace-delimited block from source starting at the
    opening brace at start_pos.
    """
    if start_pos >= len(source) or source[start_pos] != "{":
        return ""

    depth = 0
    end_pos = start_pos

    for i in range(start_pos, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                end_pos = i + 1
                break

    return source[start_pos:end_pos]


def _extract_soql(text: str) -> list[str]:
    """Extract SOQL query strings from text."""
    queries = []
    for match in _SOQL_RE.finditer(text):
        queries.append(match.group(0).strip())
    return queries


def _extract_dml(text: str) -> list[str]:
    """Extract DML operation types from text."""
    ops = []
    for match in _DML_RE.finditer(text):
        ops.append(match.group("operation").lower())
    return ops


def _extract_sobject_refs(text: str) -> list[str]:
    """Extract SObject references (new Account(...), etc.)."""
    refs = set()

    for match in _SOBJECT_NEW_RE.finditer(text):
        refs.add(match.group("sobject"))

    # Also check SOQL FROM clauses
    for match in _SOQL_RE.finditer(text):
        from_match = re.search(r"FROM\s+(\w+)", match.group(0), re.IGNORECASE)
        if from_match:
            refs.add(from_match.group(1))

    return sorted(list(refs))


# ── Standalone usage ──────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python apex_analyzer.py <filepath.cls> [method_name]")
        sys.exit(1)

    fp = sys.argv[1]
    mn = sys.argv[2] if len(sys.argv) > 2 else None

    result = {
        "file": fp,
        "classes": extract_classes(fp),
        "methods": extract_methods(fp, mn),
        "context": extract_file_context(fp),
        "patterns": detect_apex_patterns(fp),
        "references": extract_apex_imports(fp),
    }
    print(json.dumps(result, indent=2))
