"""
AI-powered test case generator.
Constructs prompts from parsed function data and calls an
OpenAI-compatible chat completions API.  Uses only stdlib
(urllib) so the engine has zero pip dependencies.
"""

import json
import sys
import time
import urllib.request
import urllib.error
from typing import Optional


# ── System prompt ─────────────────────────────────────────────────
SYSTEM_PROMPT = """\
You are an expert enterprise Python test engineer. Your ONLY job is to
produce production-grade pytest test code for a given function or class.

Rules you MUST follow:
1.  Output ONLY valid Python code. No markdown fences, no conversational prose.
2.  Start with necessary imports (pytest, the function/class under test, unittest.mock if needed).
3.  Use a test class named  Test<FunctionName>  (PascalCase).
4.  Give every test method a clear, descriptive name:
        test_<what_is_being_tested>
5.  Cover ALL of these categories when applicable:
      • Happy path – normal expected inputs and outputs.
      • Edge cases – empty strings, empty lists, zero, None, single element, large values.
      • Boundary values – min/max limits, off-by-one conditions.
      • Error / exception cases – invalid inputs that should raise ValueError, TypeError, or custom domain exceptions.
      • Type variations – different valid types if accepted.
6.  Use  @pytest.mark.parametrize  when multiple inputs test identical assertion logic.
7.  Use  pytest.raises  for exception tests, checking both error type and error message if applicable.
8.  Add a concise docstring to every test method.
9.  Generate between 6 and 20 comprehensive test methods depending on complexity.
10. If the function is a method of a class, instantiate the class in a  @pytest.fixture  and inject it into test methods.
11. Dependency Mocking (Enterprise Rule):
      • If the function interacts with external APIs, network, databases, files, or external services:
        Use  unittest.mock.patch  or  unittest.mock.MagicMock .
      • Mock both success cases AND failure cases (e.g. timeout, connection error, 404, bad gateway).
      • Test mock assertions: verify mock.assert_called_once_with(...) where critical.
12. Async Functions:
      • If the function is  async def , use  @pytest.mark.asyncio  and  await .
      • If mocking async dependencies, use  unittest.mock.AsyncMock .
13. Relative Import Path:
      • Assume the test file lives in  generated_tests/  at the project root.
      • Use: from <module> import <target>
"""


def build_prompt(
    func_info: dict,
    imports: list[str],
    filename: str,
    file_context: Optional[dict] = None,
    dependencies: Optional[dict] = None,
    frameworks: Optional[list[str]] = None,
    fixtures: Optional[list[dict]] = None,
) -> list[dict]:
    """
    Build the messages list for the chat completions API with rich enterprise context.
    """
    parts = []

    parts.append(f"Source file: {filename}")

    if file_context:
        if file_context.get("module_docstring"):
            parts.append(f"Module docstring:\n{file_context['module_docstring']}")
        if file_context.get("constants"):
            parts.append("Global constants:\n" + "\n".join(file_context["constants"]))

    if imports:
        parts.append("File imports:\n" + "\n".join(imports))

    # Cross-file dependency context
    if dependencies:
        dep_lines = []
        for name, info in dependencies.items():
            if info["type"] == "class":
                methods_str = ", ".join(m["name"] for m in info.get("methods", [])) or "no methods"
                init_str = ", ".join(info.get("init_args", []))
                dep_lines.append(
                    f"  • Class {name} (from {info['source_file']}):\n"
                    f"      __init__({init_str})\n"
                    f"      Methods: [{methods_str}]"
                )
            elif info["type"] == "function":
                args_str = ", ".join(info.get("args", []))
                dep_lines.append(f"  • Function {name}({args_str}) (from {info['source_file']})")
        if dep_lines:
            parts.append(
                "Imported Local Dependencies (from other files in this project):\n"
                + "\n".join(dep_lines)
                + "\nNOTE: When mocking or interacting with these dependencies, use these exact signatures and method names!"
            )

    # Framework detection instructions
    if frameworks:
        fw_rules = []
        if "fastapi" in frameworks:
            fw_rules.append("• FastAPI: Use fastapi.testclient.TestClient, test status codes (200, 400, 422), and override dependencies with app.dependency_overrides if needed.")
        if "flask" in frameworks:
            fw_rules.append("• Flask: Use app.test_client(), test response status codes and json data.")
        if "django" in frameworks:
            fw_rules.append("• Django: Use django.test.Client or TestCase, mock ORM queries with MagicMock.")
        if "sqlalchemy" in frameworks:
            fw_rules.append("• SQLAlchemy: Mock session.query(), filter(), first(), and verify rollback behavior on exceptions.")
        if "pydantic" in frameworks:
            fw_rules.append("• Pydantic: Test valid model parsing and test pydantic.ValidationError on invalid fields or missing required keys.")
        if "requests" in frameworks or "httpx" in frameworks:
            fw_rules.append("• HTTP Client: Mock response.status_code, response.json(), and test network timeouts/errors.")
        if "boto3" in frameworks:
            fw_rules.append("• AWS/Boto3: Mock boto3 client calls using unittest.mock.patch.")
        if fw_rules:
            parts.append("Framework-Specific Guidelines for this Project:\n" + "\n".join(fw_rules))

    # Existing workspace fixtures
    if fixtures:
        fix_lines = [
            f"  • {f['name']} (from {f['file']}): {f.get('docstring') or 'fixture'}"
            for f in fixtures[:8]
        ]
        parts.append(
            "Existing Project Fixtures (available in workspace):\n"
            + "\n".join(fix_lines)
            + "\nPrefer using or referencing these fixtures if applicable instead of reinventing them!"
        )

    if func_info.get("class_name"):
        parts.append(f"This function is a method of class: {func_info['class_name']}")
        if func_info.get("class_source"):
            parts.append(f"Full class source:\n```python\n{func_info['class_source']}\n```")

    parts.append(f"Function to generate tests for:\n```python\n{func_info['body']}\n```")

    if func_info.get("docstring"):
        parts.append(f"Docstring:\n{func_info['docstring']}")

    if func_info.get("decorators"):
        parts.append("Decorators: " + ", ".join(func_info["decorators"]))

    if func_info.get("is_async"):
        parts.append("NOTE: This is an ASYNC function (async def). Use @pytest.mark.asyncio and await.")

    user_content = "\n\n".join(parts)

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def call_api(
    api_key: str,
    base_url: str,
    model: str,
    messages: list[dict],
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> str:
    """
    Call an OpenAI-compatible /chat/completions endpoint.

    Args:
        api_key:     Bearer token
        base_url:    e.g. "https://api.openai.com/v1"
        model:       e.g. "gpt-4o-mini"
        messages:    chat messages list
        temperature: sampling temperature (lower = more deterministic)
        max_tokens:  response length cap

    Returns:
        The assistant's reply as a plain string.

    Raises:
        RuntimeError on HTTP or parsing errors.
    """
    clean_base = base_url.rstrip("/")
    if clean_base.endswith("/chat/completions"):
        url = clean_base
    else:
        url = f"{clean_base}/chat/completions"

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    data = json.dumps(payload).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            choice = body.get("choices", [{}])[0]
            msg = choice.get("message", {})
            content = msg.get("content")
            if content is None:
                raise RuntimeError(f"API response missing content: {body}")
            return content
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"API returned HTTP {exc.code}:\n{error_body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unexpected API response format: {exc}") from exc


def call_api_with_fallback(
    api_keys: list[str],
    base_url: str,
    model: str,
    messages: list[dict],
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> str:
    """
    Try each API key in order. If one fails, fall back to the next.
    Returns the response from the first key that succeeds.

    Args:
        api_keys:    list of API keys to try in order
        base_url:    API base URL
        model:       model name
        messages:    chat messages
        temperature: sampling temperature
        max_tokens:  response cap

    Raises:
        RuntimeError with details of ALL failures if every key fails.
    """
    errors = []

    for i, key in enumerate(api_keys, start=1):
        label = f"Key {i}/{len(api_keys)}"
        for attempt in range(2):
            try:
                result = call_api(key, base_url, model, messages, temperature, max_tokens)
                if len(api_keys) > 1 and i > 1:
                    # Log which fallback key worked (to stderr, not stdout)
                    print(f"  -> {label} succeeded (fallback)", file=sys.stderr)
                return result
            except RuntimeError as exc:
                err_str = str(exc)
                # If temporary spike (503 or 429) on first attempt, retry after brief pause
                if attempt == 0 and ("503" in err_str or "429" in err_str):
                    time.sleep(2)
                    continue
                errors.append(f"{label}: {exc}")
                if len(api_keys) > 1:
                    print(f"  -> {label} failed, trying next...", file=sys.stderr)
                break

    # All keys exhausted
    error_details = "\n".join(errors)
    raise RuntimeError(
        f"All {len(api_keys)} API key(s) failed:\n{error_details}"
    )


def clean_response(raw: str) -> str:
    r"""
    Strip markdown code fences, leading/trailing whitespace,
    and LLM token artifacts like <ctrl\d+>.
    """
    import re

    text = raw.strip()

    # Strip model control tokens like <ctrl63>
    text = re.sub(r"<ctrl\d+>", "", text)

    # Remove ```python ... ``` wrapper
    if text.startswith("```"):
        first_newline = text.index("\n") if "\n" in text else len(text)
        text = text[first_newline + 1 :]
    if text.endswith("```"):
        text = text[: -3]

    return text.strip()


def parse_api_keys(raw: str) -> list[str]:
    """
    Accept a single key or comma-separated keys.
    Strips whitespace, removes empties.
    """
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise ValueError("No valid API keys provided")
    return keys


def generate_tests(
    func_info: dict,
    imports: list[str],
    filename: str,
    api_key: str,
    base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai",
    model: str = "gemini-2.5-flash",
    file_context: Optional[dict] = None,
    dependencies: Optional[dict] = None,
    frameworks: Optional[list[str]] = None,
    fixtures: Optional[list[dict]] = None,
) -> str:
    """
    End-to-end: build prompt ➜ call API (with fallback) ➜ return clean test code.

    api_key can be a single key or comma-separated keys for fallback.
    """
    messages = build_prompt(
        func_info=func_info,
        imports=imports,
        filename=filename,
        file_context=file_context,
        dependencies=dependencies,
        frameworks=frameworks,
        fixtures=fixtures,
    )
    keys = parse_api_keys(api_key)
    raw = call_api_with_fallback(keys, base_url, model, messages)
    return clean_response(raw)


# ── Standalone test ───────────────────────────────────────────────
if __name__ == "__main__":
    print("generator.py loaded - use via main.py or import directly.")
