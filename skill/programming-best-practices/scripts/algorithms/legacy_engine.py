"""Conservative algorithm recognition and advisory engine."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from .frontends import LEXICAL_API, containing_name, iter_source_units, qualified_names
from .model import make_occurrence, relative_location
from .python_misuse import detect_python_misuse
from .tree_sitter_frontend import parse_calls


def _requirement(name: str, state: str, hard: bool, reason: str) -> dict[str, Any]:
    return {"name": name, "state": state, "hard": hard, "reason": reason}


def _recommendation(summary: str, level: str, validation: list[str]) -> dict[str, Any]:
    return {"summary": summary, "correction_level": level, "validation": validation}


def _safe_literal_sequence(node: ast.AST) -> bool:
    if not isinstance(node, (ast.List, ast.Tuple)) or not node.elts:
        return False
    values = []
    for element in node.elts:
        try:
            values.append(ast.literal_eval(element))
        except (ValueError, TypeError):
            return False
    categories = {
        "number" if isinstance(value, (int, float, bool)) and not isinstance(value, complex)
        else "str" if isinstance(value, str)
        else "bytes" if isinstance(value, bytes)
        else "unsupported"
        for value in values
    }
    return len(categories) == 1 and "unsupported" not in categories

def _subscript_index(node: ast.AST) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant) and isinstance(node.operand.value, int):
        return -node.operand.value
    return None

def _sorted_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "sorted"


def _python_occurrences(unit, root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        tree = ast.parse(unit.text, filename=str(unit.path))
    except SyntaxError as exc:
        return [], [f"{unit.path}: Python syntax error at line {exc.lineno}; file was not analyzed."]
    names = qualified_names(tree)
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    sorted_shadowed = any(
        (isinstance(node, ast.Name) and node.id == "sorted" and isinstance(node.ctx, ast.Store))
        or (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == "sorted")
        or (isinstance(node, ast.arg) and node.arg == "sorted")
        or (isinstance(node, (ast.Import, ast.ImportFrom)) and any((alias.asname or alias.name.rsplit(".", 1)[-1]) == "sorted" for alias in node.names))
        for node in ast.walk(tree)
    )
    occurrences: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            token = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
            match = LEXICAL_API.fullmatch(token)
            parent = parents.get(node)
            consumed_by_extreme = isinstance(parent, ast.Subscript) and parent.value is node
            if match and not consumed_by_extreme:
                location = relative_location(unit.path, root, node.lineno, containing_name(node, tree, names))
                occurrences.append(make_occurrence(
                    algorithm_id=f"library.{_canonical_api(match.group(1))}",
                    rule_id="pbp.algorithm.library-api.recognized", family="library-api",
                    status="recognized", confidence="medium", location=location,
                    problem="use a standard-library algorithm or data structure",
                    current_approach=token, current_time="unknown", expected_time=None,
                    evidence=[{"kind": "ast", "description": f"Python call structure contains known API token {token!r}."}],
                    requirements=[_requirement(
                        "runtime binding and input semantics are resolved", "UNKNOWN", True,
                        "The name may be shadowed or the receiver type may be unknown.",
                    )],
                    alternatives=[], recommendation=None,
                ))
        if isinstance(node, ast.Subscript) and _sorted_call(node.value):
            index = _subscript_index(node.slice)
            if index in {0, -1}:
                target = "min" if index == 0 else "max"
                location = relative_location(unit.path, root, node.lineno, containing_name(node, tree, names))
                source_arg = node.value.args[0] if len(node.value.args) == 1 and not node.value.keywords else None
                safe = source_arg is not None and _safe_literal_sequence(source_arg) and not sorted_shadowed
                requirements = [
                    _requirement("only one extreme value is required", "PROVEN", True, "The sorted result is indexed once."),
                    _requirement(
                        "ordering semantics have no user-code side effects", "PROVEN" if safe else "UNKNOWN", True,
                        "A nonempty homogeneous primitive literal and builtin binding are proven." if safe else "Static analysis cannot prove custom comparison/key or name-binding side effects.",
                    ),
                    _requirement(
                        "empty-input behavior is compatible", "PROVEN" if safe else "UNKNOWN", True,
                        "The literal is statically nonempty." if safe else "IndexError and min/max ValueError are observably different.",
                    ),
                ]
                recommendation = _recommendation(
                    f"Replace the full sort with {target}(...)." if safe else f"Consider {target}(...) after confirming key/comparison and empty-input semantics.",
                    "SAFE" if safe else "ASSISTED",
                    ["reanalyze", "differential-test original and replacement", "property-test equivalence"],
                )
                if safe:
                    recommendation["patch"] = {
                        "kind": "replace-expression", "file": location["file"], "line": node.lineno,
                        "end_line": getattr(node, "end_lineno", node.lineno),
                        "replacement": f"{target}({ast.unparse(source_arg)})",
                    }
                occurrences.append(make_occurrence(
                    algorithm_id=f"selection.{target}", rule_id="pbp.algorithm.sort.full-sort-for-extreme",
                    family="selection", status="suboptimal", confidence="high", location=location,
                    problem=f"select the {target}imum element", current_approach="full sort followed by one index",
                    current_time="O(n log n)", expected_time="O(n)",
                    evidence=[{"kind": "ast", "description": f"sorted(...) result is read only at index {index}."}],
                    requirements=requirements,
                    alternatives=[{"algorithm_id": f"selection.{target}", "eligible": safe, "reason": "All hard requirements are PROVEN." if safe else "Hard semantic requirements remain UNKNOWN."}],
                    recommendation=recommendation,
                ))
        if isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add) and isinstance(node.value, (ast.Name, ast.JoinedStr, ast.BinOp)):
            parent_loop = any(
                isinstance(candidate, (ast.For, ast.While))
                and getattr(candidate, "lineno", 0) <= node.lineno <= getattr(candidate, "end_lineno", 0)
                for candidate in ast.walk(tree)
            )
            if parent_loop:
                location = relative_location(unit.path, root, node.lineno, containing_name(node, tree, names))
                occurrences.append(make_occurrence(
                    algorithm_id="sequence.buffered-concatenation", rule_id="pbp.algorithm.sequence.repeated-concatenation",
                    family="sequences", status="refactor-opportunity", confidence="medium", location=location,
                    problem="incremental-sequence-construction", current_approach="repeated addition inside a loop",
                    current_time="implementation-dependent", expected_time="O(n)",
                    evidence=[{"kind": "ast", "description": "An += operation occurs inside a loop."}],
                    requirements=[_requirement("the accumulator is an immutable sequence", "UNKNOWN", True, "The inferred runtime type is unknown.")],
                    alternatives=[{"algorithm_id": "sequence.buffered-concatenation", "eligible": False, "reason": "Accumulator type is UNKNOWN."}],
                    recommendation=_recommendation("If the accumulator is immutable, collect parts and join once.", "ASSISTED", ["reanalyze", "differential-test output and side effects"]),
                ))
    occurrences.extend(detect_python_misuse(tree, unit.path, root, names))
    return occurrences, []


def _canonical_api(token: str) -> str:
    value = token.lower()
    return "sort" if value == "sorted" else value

def _non_python_occurrences(unit, root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    calls, limitations = parse_calls(unit.language, unit.text)
    result: list[dict[str, Any]] = []
    if calls:
        candidates = [
            (match, call.line, call.qualified_name, "tree-sitter", "medium")
            for call in calls for match in LEXICAL_API.finditer(call.text)
        ]
    else:
        candidates = [
            (match, unit.text.count("\n", 0, match.start()) + 1, None, "lexical", "low")
            for match in LEXICAL_API.finditer(unit.text)
        ]
    for match, line, qualified_name, evidence_kind, confidence in candidates:
        location = relative_location(unit.path, root, line, qualified_name)
        result.append(make_occurrence(
            algorithm_id=f"library.{_canonical_api(match.group(1))}", rule_id="pbp.algorithm.library-api.recognized",
            family="library-api", status="recognized", confidence=confidence, location=location,
            problem="use a standard-library algorithm or data structure", current_approach=match.group(1),
            current_time="unknown", expected_time=None,
            evidence=[{"kind": evidence_kind, "description": f"A parsed call contains known API token {match.group(1)!r}."}],
            requirements=[_requirement(
                "API binding, overload and input semantics are resolved", "UNKNOWN", True,
                "Parsing proves call structure but not runtime binding or semantic preconditions.",
            )],
            alternatives=[], recommendation=None,
        ))
    return result, limitations

def analyze_repository(root: Path, *, profile: str = "standard", focus: set[str] | None = None) -> dict[str, Any]:
    root = root.resolve(strict=True)
    occurrences: list[dict[str, Any]] = []
    limitations: list[str] = []
    languages: set[str] = set()
    scanned = 0
    for unit in iter_source_units(root):
        scanned += 1
        languages.add(unit.language)
        if unit.language == "python":
            found, problems = _python_occurrences(unit, root)
            occurrences.extend(found)
            limitations.extend(problems)
        else:
            found, problems = _non_python_occurrences(unit, root)
            occurrences.extend(found)
            limitations.extend(problems)
    if any(language != "python" for language in languages):
        limitations.append("Non-Python Tree-sitter frontends provide structural call evidence but do not resolve runtime bindings; they never authorize corrections.")
    if focus:
        normalized = {item.replace("\\", "/").lstrip("./") for item in focus}
        occurrences = [item for item in occurrences if item["primary_location"]["file"].lstrip("./") in normalized]
    occurrences.sort(key=lambda item: (item["primary_location"]["file"], item["primary_location"]["line"], item["rule_id"]))
    return {
        "schema_version": "1.0.0", "catalog_version": "0.1.0", "profile": profile,
        "effective_scope": "repository" if not focus else "changed files + local dependency context",
        "languages": sorted(languages), "files_scanned": scanned,
        "algorithms": occurrences, "limitations": sorted(set(limitations)),
    }
