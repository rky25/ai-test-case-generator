"""
AST-based Python source code analyzer.
Extracts function signatures, bodies, docstrings, and imports
using Python's built-in ast module. Zero external dependencies.
"""

import ast
import sys
import json
from pathlib import Path
from typing import Optional


def extract_functions(filepath: str, function_name: Optional[str] = None) -> list[dict]:
    """
    Parse a Python file and extract function/method information.

    Args:
        filepath: Path to the Python source file.
        function_name: If provided, extract only this specific function.

    Returns:
        List of dicts, each describing one function.
    """
    source = Path(filepath).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=filepath)
    source_lines = source.splitlines()

    functions = []

    # Top-level functions
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if function_name and node.name != function_name:
                continue
            info = _extract_function_info(node, source_lines, class_name=None)
            functions.append(info)

        # Methods inside top-level classes
        elif isinstance(node, ast.ClassDef):
            class_source = "\n".join(source_lines[node.lineno - 1 : node.end_lineno])
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if function_name and item.name != function_name:
                        continue
                    info = _extract_function_info(
                        item,
                        source_lines,
                        class_name=node.name,
                        class_source=class_source,
                    )
                    functions.append(info)

    return functions


def _extract_function_info(
    node,
    source_lines: list[str],
    class_name: Optional[str] = None,
    class_source: Optional[str] = None,
) -> dict:
    """Extract detailed metadata from a single function AST node."""

    # Function source code
    start = node.lineno - 1
    end = node.end_lineno
    func_source = "\n".join(source_lines[start:end])

    # Arguments
    args = _extract_args(node.args)

    # Return type
    return_type = ast.unparse(node.returns) if node.returns else None

    # Docstring
    docstring = ast.get_docstring(node)

    # Decorators
    decorators = [ast.unparse(d) for d in node.decorator_list]

    return {
        "name": node.name,
        "args": args,
        "return_type": return_type,
        "docstring": docstring,
        "body": func_source,
        "decorators": decorators,
        "is_async": isinstance(node, ast.AsyncFunctionDef),
        "class_name": class_name,
        "class_source": class_source,
        "start_line": node.lineno,
        "end_line": node.end_lineno,
    }


def _extract_args(args_node) -> list[dict]:
    """Extract argument names and type annotations."""
    result = []

    all_args = args_node.args + args_node.posonlyargs + args_node.kwonlyargs

    for arg in all_args:
        result.append(
            {
                "name": arg.arg,
                "annotation": ast.unparse(arg.annotation) if arg.annotation else None,
            }
        )

    if args_node.vararg:
        result.append(
            {
                "name": f"*{args_node.vararg.arg}",
                "annotation": (
                    ast.unparse(args_node.vararg.annotation)
                    if args_node.vararg.annotation
                    else None
                ),
            }
        )

    if args_node.kwarg:
        result.append(
            {
                "name": f"**{args_node.kwarg.arg}",
                "annotation": (
                    ast.unparse(args_node.kwarg.annotation)
                    if args_node.kwarg.annotation
                    else None
                ),
            }
        )

    return result


def extract_imports(filepath: str) -> list[str]:
    """Extract all import statements from the top of a Python file."""
    source = Path(filepath).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=filepath)

    imports = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(ast.unparse(node))

    return imports


def extract_file_context(filepath: str) -> dict:
    """
    Extract high-level context: module docstring, global constants,
    and class names. Helps the LLM understand the broader file.
    """
    source = Path(filepath).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=filepath)

    module_docstring = ast.get_docstring(tree)

    classes = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes.append(
                {
                    "name": node.name,
                    "bases": [ast.unparse(b) for b in node.bases],
                    "docstring": ast.get_docstring(node),
                }
            )

    # Simple global constants (NAME = literal)
    constants = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    try:
                        constants.append(f"{target.id} = {ast.unparse(node.value)}")
                    except Exception:
                        pass

    return {
        "module_docstring": module_docstring,
        "classes": classes,
        "constants": constants,
    }


def _resolve_local_module(
    module_name: Optional[str],
    level: int,
    current_file: Path,
    project_root: Path,
) -> Optional[Path]:
    """Resolve an import to a local .py file if it exists in the project."""
    candidates = []

    if level > 0:
        base = current_file.parent
        for _ in range(level - 1):
            base = base.parent
        if module_name:
            rel_parts = module_name.split(".")
            candidates.append(base.joinpath(*rel_parts).with_suffix(".py"))
            candidates.append(base.joinpath(*rel_parts, "__init__.py"))
        else:
            candidates.append(base / "__init__.py")
    elif module_name:
        parts = module_name.split(".")
        candidates.append(current_file.parent.joinpath(*parts).with_suffix(".py"))
        candidates.append(current_file.parent.joinpath(*parts, "__init__.py"))
        candidates.append(project_root.joinpath(*parts).with_suffix(".py"))
        candidates.append(project_root.joinpath(*parts, "__init__.py"))

    for c in candidates:
        try:
            if c.is_file():
                return c.resolve()
        except (OSError, PermissionError):
            pass

    return None


def extract_cross_file_dependencies(
    filepath: str, project_root: Optional[str] = None
) -> dict:
    """
    Follow local imports and extract class/function signatures from other files.
    This gives the AI exact awareness of methods and signatures of imported classes.
    """
    current_path = Path(filepath).resolve()
    root_path = Path(project_root).resolve() if project_root else current_path.parent

    try:
        source = current_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(current_path))
    except Exception:
        return {}

    dependencies = {}
    parsed_files = {}

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ImportFrom):
            mod_path = _resolve_local_module(
                node.module, node.level, current_path, root_path
            )
            if not mod_path or mod_path == current_path:
                continue

            if str(mod_path) not in parsed_files:
                try:
                    mod_code = mod_path.read_text(encoding="utf-8")
                    parsed_files[str(mod_path)] = (
                        ast.parse(mod_code, filename=str(mod_path)),
                        mod_code.splitlines(),
                    )
                except Exception:
                    parsed_files[str(mod_path)] = (None, None)

            mod_tree, mod_lines = parsed_files[str(mod_path)]
            if not mod_tree:
                continue

            try:
                rel_file_str = (
                    str(mod_path.relative_to(root_path))
                    if mod_path.is_relative_to(root_path)
                    else mod_path.name
                )
            except Exception:
                rel_file_str = mod_path.name

            target_names = [alias.name for alias in node.names]
            for item in mod_tree.body:
                if isinstance(item, ast.ClassDef):
                    if "*" in target_names or item.name in target_names:
                        methods = []
                        init_args = []
                        for sub in item.body:
                            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                if sub.name == "__init__":
                                    init_args = [
                                        a["name"]
                                        for a in _extract_args(sub.args)
                                        if a["name"] != "self"
                                    ]
                                elif not sub.name.startswith("_") or sub.name.startswith("__"):
                                    methods.append(
                                        {
                                            "name": sub.name,
                                            "args": [
                                                a["name"] for a in _extract_args(sub.args)
                                            ],
                                            "return_type": (
                                                ast.unparse(sub.returns)
                                                if sub.returns
                                                else None
                                            ),
                                            "docstring": ast.get_docstring(sub),
                                        }
                                    )
                        dependencies[item.name] = {
                            "type": "class",
                            "source_file": rel_file_str,
                            "bases": [ast.unparse(b) for b in item.bases],
                            "docstring": ast.get_docstring(item),
                            "init_args": init_args,
                            "methods": methods[:8],
                        }
                elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if "*" in target_names or item.name in target_names:
                        dependencies[item.name] = {
                            "type": "function",
                            "source_file": rel_file_str,
                            "args": [a["name"] for a in _extract_args(item.args)],
                            "return_type": (
                                ast.unparse(item.returns) if item.returns else None
                            ),
                            "docstring": ast.get_docstring(item),
                            "is_async": isinstance(item, ast.AsyncFunctionDef),
                        }

    return dependencies


def detect_frameworks(filepath: str, project_root: Optional[str] = None) -> list[str]:
    """
    Detect web frameworks, ORMs, and async libraries used in the file or project.
    Enables framework-tailored test generation instructions.
    """
    frameworks = set()
    current_path = Path(filepath).resolve()

    try:
        source = current_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(current_path))
        for node in ast.iter_child_nodes(tree):
            mod_names = []
            if isinstance(node, ast.Import):
                mod_names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mod_names = [node.module.split(".")[0]]

            for m in mod_names:
                if m in ("fastapi", "starlette"):
                    frameworks.add("fastapi")
                elif m == "flask":
                    frameworks.add("flask")
                elif m == "django":
                    frameworks.add("django")
                elif m in ("sqlalchemy", "sqlmodel"):
                    frameworks.add("sqlalchemy")
                elif m == "pydantic":
                    frameworks.add("pydantic")
                elif m in ("requests", "urllib3"):
                    frameworks.add("requests")
                elif m == "httpx":
                    frameworks.add("httpx")
                elif m in ("boto3", "botocore"):
                    frameworks.add("boto3")
                elif m == "celery":
                    frameworks.add("celery")
                elif m == "redis":
                    frameworks.add("redis")
    except Exception:
        pass

    return sorted(list(frameworks))


def discover_workspace_fixtures(project_root: str) -> list[dict]:
    """
    Scan existing conftest.py files in the project to find reusable fixtures.
    """
    root = Path(project_root).resolve()
    fixtures = []

    conftest_files = list(root.glob("**/conftest.py"))
    for f in root.glob("**/tests/**/*.py"):
        if f not in conftest_files:
            conftest_files.append(f)

    for cfile in conftest_files[:10]:
        if "generated_tests" in cfile.parts:
            continue
        try:
            tree = ast.parse(cfile.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    is_fixture = any(
                        "fixture" in ast.unparse(d) for d in node.decorator_list
                    )
                    if is_fixture:
                        fixtures.append(
                            {
                                "name": node.name,
                                "args": [a.arg for a in node.args.args],
                                "docstring": ast.get_docstring(node),
                                "file": cfile.name,
                            }
                        )
        except Exception:
            continue

    return fixtures[:15]


# ── Standalone usage ──────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analyzer.py <filepath> [function_name]")
        sys.exit(1)

    fp = sys.argv[1]
    fn = sys.argv[2] if len(sys.argv) > 2 else None

    result = {
        "file": fp,
        "imports": extract_imports(fp),
        "context": extract_file_context(fp),
        "functions": extract_functions(fp, fn),
        "dependencies": extract_cross_file_dependencies(fp),
        "frameworks": detect_frameworks(fp),
        "fixtures": discover_workspace_fixtures(str(Path(fp).parent)),
    }
    print(json.dumps(result, indent=2))
