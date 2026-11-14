"""Safe source frontends.

Python uses its standard AST. Other ecosystems currently expose conservative
lexical facts. Those facts are explicitly low-confidence and can never grant a
SAFE correction; this is preferable to pretending a missing grammar proved a
semantic precondition.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

try:
    from analysis_core.files import project_files
except ModuleNotFoundError:  # carga aislada del paquete (tests de contrato)
    import importlib.util
    import sys

    _spec = importlib.util.spec_from_file_location("_pbp_analysis_core_files", Path(__file__).resolve().parent.parent / "analysis_core" / "files.py")
    if _spec is None or _spec.loader is None:
        raise
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = _module
    _spec.loader.exec_module(_module)
    project_files = _module.project_files

LANGUAGE_BY_SUFFIX = {
    ".py": "python", ".java": "java", ".kt": "kotlin", ".kts": "kotlin",
    ".js": "javascript", ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript",
    ".cs": "csharp", ".go": "go", ".rs": "rust", ".c": "c", ".h": "cpp",
    ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".hpp": "cpp",
}

EXCLUDED = {".git", ".venv", "venv", "node_modules", "vendor", "dist", "build", "target", "__pycache__"}


@dataclass(frozen=True)
class SourceUnit:
    path: Path
    language: str
    text: str


def iter_source_units(root: Path) -> Iterator[SourceUnit]:
    for path in project_files(root, EXCLUDED):
        language = LANGUAGE_BY_SUFFIX.get(path.suffix.lower())
        if not language:
            continue
        try:
            yield SourceUnit(path, language, path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue


def qualified_names(tree: ast.AST) -> dict[ast.AST, str]:
    result: dict[ast.AST, str] = {}
    stack: list[str] = []

    def visit(node: ast.AST) -> None:
        named = isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        if named:
            stack.append(node.name)
            result[node] = ".".join(stack)
        for child in ast.iter_child_nodes(node):
            visit(child)
        if named:
            stack.pop()

    visit(tree)
    return result


def containing_name(node: ast.AST, tree: ast.AST, names: dict[ast.AST, str]) -> str | None:
    best: tuple[int, str] | None = None
    line = getattr(node, "lineno", 0)
    for candidate, name in names.items():
        start, end = getattr(candidate, "lineno", 0), getattr(candidate, "end_lineno", 0)
        if start <= line <= end and (best is None or start >= best[0]):
            best = (start, name)
    return best[1] if best else None


LEXICAL_API = re.compile(r"\b(sort(?:ed)?|binary_search|lower_bound|upper_bound|heap(?:q)?|priority_queue|HashMap|HashSet|Dictionary|deque|VecDeque|BTreeMap)\b", re.IGNORECASE)
