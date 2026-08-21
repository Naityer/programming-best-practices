"""Tree-sitter structural operations shared by all non-Python ecosystems."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

try:
    from tree_sitter_language_pack import get_parser
except ImportError:  # optional and fail-closed
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
LOOP_MARKERS = ("for", "while", "loop", "foreach")
MEMBERSHIP_MARKERS = (
    ".contains(", ".contains_key(", ".includes(", "std::find(",
    "binary_search(", " in ",
)
SORT_MARKERS = (".sort(", ".sorted(", "sort.", "std::sort(", "collections.sort(", "arrays.sort(")


@dataclass(frozen=True)
class StructuralOperation:
    kind: str
    text: str
    line: int
    end_line: int
    qualified_name: str | None
    loop_depth: int
    attributes: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _name(node: Any, source: bytes) -> str | None:
    named = node.child_by_field_name("name")
    if named is not None:
        return source[named.start_byte:named.end_byte].decode("utf-8", errors="replace")
    declarator = node.child_by_field_name("declarator")
    if declarator is not None:
        text = source[declarator.start_byte:declarator.end_byte].decode("utf-8", errors="replace")
        return text.split("(", 1)[0].strip().split()[-1]
    return None


def _is_loop(node_type: str) -> bool:
    lowered = node_type.lower()
    return any(marker in lowered for marker in LOOP_MARKERS) and any(
        suffix in lowered for suffix in ("statement", "expression", "clause", "loop")
    )


def _classify(node: Any, raw: str) -> tuple[str | None, dict[str, Any]]:
    lowered = raw.lower()
    node_type = node.type.lower()
    if _is_loop(node_type):
        return "iterate", {}
    if node.type in CALL_TYPES:
        if any(marker in lowered for marker in SORT_MARKERS):
            return "sort", {"callee_text": raw[:240]}
        if any(marker in lowered for marker in MEMBERSHIP_MARKERS):
            return "membership", {"callee_text": raw[:240]}
        return "call", {"callee_text": raw[:240]}
    if "binary" in node_type or "comparison" in node_type or "contains" in node_type:
        padded = f" {lowered} "
        if any(marker in padded for marker in MEMBERSHIP_MARKERS):
            return "membership", {"expression": raw[:240]}
        if "==" in raw or "!=" in raw:
            return "comparison", {"expression": raw[:240]}
    if "assignment" in node_type and "+=" in raw:
        return "concatenate", {"expression": raw[:240]}
    return None, {}


def parse_structural_ir(language: str, text: str) -> tuple[dict[str, Any], list[str]]:
    grammar = GRAMMAR.get(language)
    if grammar is None:
        return {"language": language, "functions": [], "operation_index": {}, "call_graph": {}}, [
            f"No Tree-sitter grammar is configured for {language}."
        ]
    if get_parser is None:
        return {"language": language, "functions": [], "operation_index": {}, "call_graph": {}}, [
            "tree-sitter-language-pack is unavailable; structural IR was skipped."
        ]
    try:
        parser = get_parser(grammar)
        source = text.encode("utf-8")
        tree = parser.parse(source)
    except (LookupError, OSError, ValueError) as exc:
        return {"language": language, "functions": [], "operation_index": {}, "call_graph": {}}, [
            f"Tree-sitter {language} frontend is unavailable: {exc}"
        ]

    functions: dict[str, dict[str, Any]] = {}
    module_name = "<module>"
    functions[module_name] = {"name": module_name, "operations": [], "calls": [], "cfg": {"nodes": [], "edges": []}, "data_flow": []}

    def visit(node: Any, scope: tuple[str, ...], loop_depth: int = 0) -> None:
        current_scope = scope
        if node.type in FUNCTION_TYPES:
            function_name = _name(node, source)
            if function_name:
                current_scope = (*scope, function_name)
                qualified = ".".join(current_scope)
                functions.setdefault(qualified, {"name": qualified, "operations": [], "calls": [], "cfg": {"nodes": [], "edges": []}, "data_flow": []})
        qualified = ".".join(current_scope) or module_name
        raw = source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
        kind, attributes = _classify(node, raw)
        if kind:
            operation = StructuralOperation(
                kind, raw[:500], node.start_point[0] + 1, node.end_point[0] + 1,
                None if qualified == module_name else qualified, loop_depth, attributes,
            )
            functions[qualified]["operations"].append(operation.to_dict())
            node_id = f"n{len(functions[qualified]['cfg']['nodes'])}"
            functions[qualified]["cfg"]["nodes"].append({"id": node_id, "kind": kind, "line": operation.line})
            previous = functions[qualified]["cfg"]["nodes"][-2]["id"] if len(functions[qualified]["cfg"]["nodes"]) > 1 else "entry"
            functions[qualified]["cfg"]["edges"].append({"source": previous, "target": node_id, "kind": "next"})
            if kind == "iterate":
                functions[qualified]["cfg"]["edges"].append({"source": node_id, "target": node_id, "kind": "loop-back"})
        if node.type in CALL_TYPES:
            callee = raw.split("(", 1)[0].strip().split(".")[-1]
            if callee:
                functions[qualified]["calls"].append(callee)
        child_depth = loop_depth + 1 if _is_loop(node.type) else loop_depth
        for child in node.children:
            visit(child, current_scope, child_depth)

    visit(tree.root_node, ())
    index: dict[str, list[str]] = {}
    for name, function in functions.items():
        function["calls"] = sorted(set(function["calls"]))
        depths = [op["loop_depth"] + 1 for op in function["operations"] if op["kind"] == "iterate"]
        if depths and max(depths) >= 2:
            time = "O(n*m)"
        elif any(op["kind"] == "sort" for op in function["operations"]):
            time = "O(n log n)"
        elif depths:
            time = "O(n)"
        else:
            time = "unknown"
        function["complexity"] = {"average": time, "worst": "implementation-dependent" if "sort" in {op['kind'] for op in function['operations']} else time, "space": "unknown", "basis": "Tree-sitter structural evidence"}
        for operation in function["operations"]:
            index.setdefault(operation["kind"], []).append(name)
    limitations = []
    if tree.root_node.has_error:
        limitations.append(f"Tree-sitter parsed {language} with syntax errors; recovered IR is conservative.")
    return {
        "language": language,
        "functions": list(functions.values()),
        "operation_index": {key: sorted(set(value)) for key, value in sorted(index.items())},
        "call_graph": {name: function["calls"] for name, function in functions.items()},
    }, limitations

