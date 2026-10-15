"""Shared pieces for the eval tasks: the Task type and helpers for writing checks."""

import ast
import re  # noqa: F401 - used by tasks that import it from here
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from evals.sandbox import run_python


@dataclass(frozen=True)
class Task:
    id: str
    level: str  # "easy" or "hard"
    prompt: str
    files: dict
    check: Callable[[Path, str], bool]
    solve: Callable[[Path], str]  # applies a correct solution, returns a correct reply
    # Optional. Returns {assertion name: passed}. When set, the task passes only if every assertion does.
    detail: Callable[[Path, str], dict] | None = None


# ---------- helpers ----------


def read(root, name: str) -> str:
    path = Path(root, name)
    return path.read_text() if path.exists() else ""


def write(root, name: str, text: str) -> None:
    path = Path(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def parse(text: str):
    try:
        return ast.parse(text)
    except SyntaxError:
        return None


def functions(tree) -> dict:
    return {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


def returns_binop(func, op, left, right) -> bool:
    """True if func has `return <left> <op> <right>`. Left and right are names or constants."""

    def matches(node, want) -> bool:
        if isinstance(node, ast.Name):
            return node.id == want
        return isinstance(node, ast.Constant) and node.value == want

    for node in ast.walk(func):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.BinOp) and isinstance(node.value.op, op):
            if matches(node.value.left, left) and matches(node.value.right, right):
                return True
    return False


def unchanged(root, files: dict) -> bool:
    return all(read(root, name) == text for name, text in files.items())


def unittest_passes(root, count: int | None = None, at_least: int | None = None) -> bool:
    """True if `python -m unittest` passes. Optionally require an exact or a minimum test count."""
    result = run_python(root, "-m", "unittest")
    if result.returncode != 0:
        return False
    match = re.search(r"Ran (\d+) tests?", result.stderr)
    ran = int(match.group(1)) if match else 0
    if count is not None and ran != count:
        return False
    return at_least is None or ran >= at_least


def materialize(root, files: dict) -> None:
    """Write a task's starting files into root, making folders as needed."""
    for name, text in files.items():
        path = Path(root, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def defines(root, name: str, func: str) -> bool:
    tree = parse(read(root, name))
    return tree is not None and func in functions(tree)


def imports_from(root, name: str, module: str, func: str) -> bool:
    tree = parse(read(root, name))
    if tree is None:
        return False
    return any(
        isinstance(n, ast.ImportFrom) and n.module == module and any(a.name == func for a in n.names)
        for n in ast.walk(tree)
    )
