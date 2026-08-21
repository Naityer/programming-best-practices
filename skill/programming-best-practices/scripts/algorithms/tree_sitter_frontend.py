"""Validated optional Tree-sitter frontend for non-Python ecosystems."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from tree_sitter_language_pack import get_parser
except ImportError:  # optional runtime: STANDARD must still degrade safely
    get_parser = None


GRAMMAR = {
    "java": "java", "kotlin": "kotlin", "javascript": "javascript",
    "typescript": "typescript", "csharp": "csharp", "go": "go",
    "rust": "rust", "c": "c", "cpp": "cpp",
}

FUNCTION_TYPES = {
    "function_declaration", "function_definition", "method_declaration",
    "method_definition", "function_item", "constructor_declaration",
    "arrow_function", "local_function_statement",
}

CALL_TYPES = {"call_expression", "method_invocation", "invocation_expression"}


@dataclass(frozen=True)
class StructuralCall:
    text: str
    line: int
    qualified_name: str | None


def _name(node: Any, source: bytes) -> str | None:
    named = node.child_by_field_name("name")
    if named is not None:
        return source[named.start_byte:named.end_byte].decode("utf-8", errors="replace")
    declarator = node.child_by_field_name("declarator")
    if declarator is not None:
        text = source[declarator.start_byte:declarator.end_byte].decode("utf-8", errors="replace")
        return text.split("(", 1)[0].strip().split()[-1]
    return None


def parse_calls(language: str, text: str) -> tuple[list[StructuralCall], list[str]]:
    grammar = GRAMMAR.get(language)
    if grammar is None:
        return [], [f"No Tree-sitter grammar is configured for {language}."]
    if get_parser is None:
        return [], ["tree-sitter-language-pack is unavailable; structured non-Python analysis was skipped."]
    try:
        parser = get_parser(grammar)
        source = text.encode("utf-8")
        tree = parser.parse(source)
    except (LookupError, OSError, ValueError) as exc:
        return [], [f"Tree-sitter {language} frontend is unavailable: {exc}"]

    calls: list[StructuralCall] = []

    def visit(node: Any, scope: tuple[str, ...]) -> None:
        current_scope = scope
        if node.type in FUNCTION_TYPES:
            function_name = _name(node, source)
            if function_name:
                current_scope = (*scope, function_name)
        if node.type in CALL_TYPES:
            raw = source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
            calls.append(StructuralCall(raw[:500], node.start_point[0] + 1, ".".join(current_scope) or None))
        for child in node.children:
            visit(child, current_scope)

    visit(tree.root_node, ())
    limitations = []
    if tree.root_node.has_error:
        limitations.append(f"Tree-sitter parsed {language} with syntax errors; only recovered structural facts were used.")
    return calls, limitations
