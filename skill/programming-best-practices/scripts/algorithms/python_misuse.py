"""High-precision Python misuse detectors from Atlas cases 40–47."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from .frontends import containing_name
from .model import make_occurrence, relative_location


def _req(name: str, state: str, hard: bool, reason: str) -> dict[str, Any]:
    return {"name": name, "state": state, "hard": hard, "reason": reason}


def _recommend(summary: str, level: str, *validation: str) -> dict[str, Any]:
    return {"summary": summary, "correction_level": level, "validation": list(validation)}


def _inside(node: ast.AST, candidate: ast.AST) -> bool:
    line = getattr(node, "lineno", 0)
    return getattr(candidate, "lineno", 0) <= line <= getattr(candidate, "end_lineno", 0)


def _location(path: Path, root: Path, node: ast.AST, tree: ast.AST, names: dict[ast.AST, str]) -> dict[str, Any]:
    return relative_location(path, root, getattr(node, "lineno", 1), containing_name(node, tree, names))


def _safe_hash_literal(node: ast.AST) -> bool:
    if not isinstance(node, (ast.List, ast.Tuple)) or not 9 <= len(node.elts) <= 64:
        return False
    values = []
    for element in node.elts:
        try:
            values.append(ast.literal_eval(element))
        except (TypeError, ValueError):
            return False
    categories = {
        "number" if isinstance(value, (int, float, bool)) and not isinstance(value, complex)
        else "str" if isinstance(value, str)
        else "bytes" if isinstance(value, bytes)
        else "unsupported"
        for value in values
    }
    return len(categories) == 1 and "unsupported" not in categories


def _repeated_membership(tree: ast.AST, path: Path, root: Path, names: dict[ast.AST, str]) -> list[dict[str, Any]]:
    output = []
    loops = [node for node in ast.walk(tree) if isinstance(node, (ast.For, ast.While, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))]
    used_names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    index_name = "_pbp_membership_index"
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or not any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
            continue
        containing_loops = [loop for loop in loops if _inside(node, loop)]
        if not containing_loops:
            continue
        container = node.comparators[0] if node.comparators else None
        if isinstance(container, (ast.Set, ast.Dict)):
            continue
        if isinstance(container, (ast.List, ast.Tuple)) and len(container.elts) <= 8:
            continue  # Atlas §102: tiny algorithms should not trigger overengineering.
        statement_loop = next((loop for loop in reversed(containing_loops) if isinstance(loop, (ast.For, ast.While))), None)
        safe = (
            statement_loop is not None
            and len(node.ops) == len(node.comparators) == 1
            and _safe_hash_literal(container)
            and index_name not in used_names
        )
        requirements = [
            _req("hash/equality semantics are compatible", "PROVEN" if safe else "UNKNOWN", True, "Homogeneous immutable primitive literals have compatible equality/hash semantics." if safe else "Runtime element types are unknown."),
            _req("ordering and duplicates are not observable", "PROVEN" if safe else "UNKNOWN", True, "The container is observed only by one membership comparison." if safe else "The surrounding data contract is unavailable."),
            _req("additional O(m) memory is acceptable", "PROVEN" if safe else "UNKNOWN", True, "The literal size is statically bounded to at most 64 elements." if safe else "Memory constraints are unavailable."),
        ]
        recommendation = _recommend(
            "Hoist a bounded primitive set before the loop." if safe else "Consider building a set once if equality, ordering and memory constraints permit it.",
            "SAFE" if safe else "ASSISTED",
            "reanalyze", "property-test membership equivalence", "benchmark representative sizes",
        )
        if safe and statement_loop is not None and isinstance(container, (ast.List, ast.Tuple)):
            set_source = "{" + ", ".join(ast.unparse(element) for element in container.elts) + "}"
            operator = "not in" if isinstance(node.ops[0], ast.NotIn) else "in"
            recommendation["patch"] = {
                "kind": "multi-edit", "file": _location(path, root, node, tree, names)["file"],
                "edits": [
                    {"kind": "insert-before", "line": statement_loop.lineno, "text": " " * statement_loop.col_offset + f"{index_name} = {set_source}\n"},
                    {"kind": "replace-expression", "line": node.lineno, "end_line": getattr(node, "end_lineno", node.lineno), "original": ast.unparse(node), "replacement": f"{ast.unparse(node.left)} {operator} {index_name}"},
                ],
            }
        output.append(make_occurrence(
            algorithm_id="hashing.membership-index", rule_id="pbp.algorithm.search.repeated-linear-membership",
            family="search", status="refactor-opportunity", confidence="high" if safe else "medium",
            location=_location(path, root, node, tree, names), problem="repeated-membership",
            current_approach="sequence membership inside a loop", current_time="O(n*m)", expected_time="O(n+m) average",
            evidence=[{"kind": "ast", "description": "A membership comparison over a non-hash literal/container occurs inside a loop."}],
            requirements=requirements,
            alternatives=[{"algorithm_id": "hashing.membership-index", "eligible": safe, "reason": "All hard requirements are PROVEN." if safe else "Hard semantic and memory requirements remain UNKNOWN."}],
            recommendation=recommendation,
        ))
    return output

def _quadratic_dedup(tree: ast.AST, path: Path, root: Path, names: dict[ast.AST, str]) -> list[dict[str, Any]]:
    output = []
    for loop in [node for node in ast.walk(tree) if isinstance(node, ast.For)]:
        for condition in [node for node in ast.walk(loop) if isinstance(node, ast.If)]:
            test = condition.test
            if not isinstance(test, ast.Compare) or not any(isinstance(op, ast.NotIn) for op in test.ops) or not test.comparators:
                continue
            target = test.comparators[0]
            if not isinstance(target, ast.Name):
                continue
            appends = [
                call for call in ast.walk(condition)
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name) and call.func.value.id == target.id and call.func.attr == "append"
            ]
            if not appends:
                continue
            output.append(make_occurrence(
                algorithm_id="hashing.stable-dedup", rule_id="pbp.algorithm.dedup.quadratic-membership",
                family="hashing", status="suboptimal", confidence="high",
                location=_location(path, root, condition, tree, names), problem="remove duplicates while scanning",
                current_approach="list membership followed by append", current_time="O(n^2)", expected_time="O(n) average",
                evidence=[{"kind": "ast", "description": f"Loop checks `x not in {target.id}` and appends to the same list."}],
                requirements=[
                    _req("first-occurrence order must be preserved", "LIKELY", False, "The current append pattern preserves first occurrence order."),
                    _req("elements are hashable with compatible equality", "UNKNOWN", True, "Runtime element types are unknown."),
                ],
                alternatives=[{"algorithm_id": "hashing.stable-dedup", "eligible": False, "reason": "Element hashability is UNKNOWN."}],
                recommendation=_recommend("Track a separate seen-set while retaining the output list after proving hashability.", "ASSISTED", "differential-test unhashable and duplicate inputs", "property-test order and equality"),
            ))
    return output


def _queue_pop_zero(tree: ast.AST, path: Path, root: Path, names: dict[ast.AST, str]) -> list[dict[str, Any]]:
    output = []
    assigned_lists = {
        target.id for node in ast.walk(tree) if isinstance(node, ast.Assign) and isinstance(node.value, ast.List)
        for target in node.targets if isinstance(target, ast.Name)
    }
    loops = [node for node in ast.walk(tree) if isinstance(node, (ast.For, ast.While, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))]
    for call in [node for node in ast.walk(tree) if isinstance(node, ast.Call)]:
        if not isinstance(call.func, ast.Attribute) or call.func.attr != "pop" or not isinstance(call.func.value, ast.Name):
            continue
        if call.func.value.id not in assigned_lists or not call.args or not isinstance(call.args[0], ast.Constant) or call.args[0].value != 0:
            continue
        if not any(_inside(call, loop) for loop in loops):
            continue
        output.append(make_occurrence(
            algorithm_id="sequences.deque-queue", rule_id="pbp.algorithm.graph.bfs-list-pop-zero",
            family="graphs", status="suboptimal", confidence="high",
            location=_location(path, root, call, tree, names), problem="consume a FIFO work queue",
            current_approach="list.pop(0) inside traversal loop", current_time="O(V^2) worst", expected_time="O(V+E)",
            evidence=[{"kind": "ast", "description": f"{call.func.value.id} is initialized as a list and pop(0) is called inside a loop."}],
            requirements=[_req("FIFO behavior is required", "PROVEN", True, "Index zero is removed repeatedly."), _req("queue is not observed as a list elsewhere", "UNKNOWN", True, "Aliasing and external observations require data-flow analysis.")],
            alternatives=[{"algorithm_id": "sequences.deque-queue", "eligible": False, "reason": "Aliasing remains UNKNOWN."}],
            recommendation=_recommend("Consider collections.deque and popleft() after checking aliases and list-specific behavior.", "ASSISTED", "reanalyze", "differential-test traversal order"),
        ))
    return output


def _recursive_fibonacci(tree: ast.AST, path: Path, root: Path, names: dict[ast.AST, str]) -> list[dict[str, Any]]:
    output = []
    for fn in [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        self_calls = [call for call in ast.walk(fn) if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == fn.name]
        if len(self_calls) < 2:
            continue
        offsets = []
        for call in self_calls:
            if call.args and isinstance(call.args[0], ast.BinOp) and isinstance(call.args[0].op, ast.Sub) and isinstance(call.args[0].right, ast.Constant):
                offsets.append(call.args[0].right.value)
        if not {1, 2}.issubset(set(offsets)):
            continue
        output.append(make_occurrence(
            algorithm_id="dynamic-programming.memoization", rule_id="pbp.algorithm.dp.overlapping-recursion",
            family="dynamic-programming", status="suboptimal", confidence="high",
            location=_location(path, root, fn, tree, names), problem="solve overlapping recurrence subproblems",
            current_approach="two recursive calls for n-1 and n-2", current_time="O(2^n)", expected_time="O(n)",
            evidence=[{"kind": "recurrence", "description": f"{fn.name} recursively calls itself for n-1 and n-2."}],
            requirements=[_req("result depends only on the recursion key", "UNKNOWN", True, "Purity and hidden state require data-flow analysis."), _req("cache growth is bounded", "UNKNOWN", True, "Input bounds are unavailable.")],
            alternatives=[{"algorithm_id": "dynamic-programming.memoization", "eligible": False, "reason": "Purity and bounds remain UNKNOWN."}],
            recommendation=_recommend("Consider iterative dynamic programming or bounded memoization after proving purity and input bounds.", "ASSISTED", "differential-test base and random inputs", "benchmark representative n"),
        ))
    return output


def _unsorted_bisect(tree: ast.AST, path: Path, root: Path, names: dict[ast.AST, str]) -> list[dict[str, Any]]:
    output = []
    for call in [node for node in ast.walk(tree) if isinstance(node, ast.Call) and node.args]:
        function = call.func.attr if isinstance(call.func, ast.Attribute) else call.func.id if isinstance(call.func, ast.Name) else ""
        if not function.startswith("bisect") or not isinstance(call.args[0], (ast.List, ast.Tuple)):
            continue
        values = [element.value for element in call.args[0].elts if isinstance(element, ast.Constant)]
        if len(values) != len(call.args[0].elts):
            continue
        try:
            contradicted = values != sorted(values)
        except TypeError:
            contradicted = True
        if not contradicted:
            continue
        output.append(make_occurrence(
            algorithm_id="search.binary", rule_id="pbp.algorithm.search.binary-unsorted-input",
            family="search", status="incorrect", confidence="high", category="quality",
            location=_location(path, root, call, tree, names), problem="search an ordered sequence",
            current_approach="binary search over a statically unsorted literal", current_time="O(log n) but invalid", expected_time=None,
            evidence=[{"kind": "precondition", "description": f"Literal input {values!r} is not sorted."}],
            contradictions=[{"kind": "hard-requirement", "description": "Binary search requires ordering under the same comparator."}],
            requirements=[_req("input is ordered", "CONTRADICTED", True, "The literal order is statically visible and unsorted.")],
            alternatives=[{"algorithm_id": "search.linear", "eligible": True, "reason": "Linear search does not require sorted input."}],
            recommendation=_recommend("Do not use binary search on this literal; establish ordering or use linear search.", "BLOCKED", "reanalyze", "property-test against linear search"),
        ))
    return output


def _negative_dijkstra(tree: ast.AST, path: Path, root: Path, names: dict[ast.AST, str]) -> list[dict[str, Any]]:
    negative_graphs: set[str] = set()
    for call in [node for node in ast.walk(tree) if isinstance(node, ast.Call)]:
        if isinstance(call.func, ast.Attribute) and call.func.attr == "add_edge" and isinstance(call.func.value, ast.Name):
            for keyword in call.keywords:
                value = keyword.value
                negative = isinstance(value, ast.UnaryOp) and isinstance(value.op, ast.USub) and isinstance(value.operand, ast.Constant) and isinstance(value.operand.value, (int, float))
                if keyword.arg in {"weight", "cost"} and negative:
                    negative_graphs.add(call.func.value.id)
    output = []
    for call in [node for node in ast.walk(tree) if isinstance(node, ast.Call) and node.args]:
        function = call.func.attr if isinstance(call.func, ast.Attribute) else call.func.id if isinstance(call.func, ast.Name) else ""
        if "dijkstra" not in function.lower() or not isinstance(call.args[0], ast.Name) or call.args[0].id not in negative_graphs:
            continue
        output.append(make_occurrence(
            algorithm_id="graphs.dijkstra", rule_id="pbp.algorithm.graph.dijkstra-negative-weight",
            family="graphs", status="incorrect", confidence="high", category="quality",
            location=_location(path, root, call, tree, names), problem="compute shortest paths on a weighted graph",
            current_approach="Dijkstra on a graph with a statically negative edge", current_time="invalid precondition", expected_time=None,
            evidence=[{"kind": "data-flow", "description": f"Graph {call.args[0].id!r} receives a negative weight and is passed to a Dijkstra API in the same module."}],
            contradictions=[{"kind": "hard-requirement", "description": "A reachable edge weight is negative."}],
            requirements=[_req("all reachable edge weights are nonnegative", "CONTRADICTED", True, "A negative edge assignment is statically visible.")],
            alternatives=[{"algorithm_id": "graphs.bellman-ford", "eligible": True, "reason": "Supports negative edges when negative-cycle behavior is handled."}],
            recommendation=_recommend("Dijkstra is blocked; validate negative-cycle semantics and consider Bellman-Ford.", "BLOCKED", "reanalyze", "differential-test against exhaustive small graphs"),
        ))
    return output


def detect_python_misuse(tree: ast.AST, path: Path, root: Path, names: dict[ast.AST, str]) -> list[dict[str, Any]]:
    detectors = (_repeated_membership, _quadratic_dedup, _queue_pop_zero, _recursive_fibonacci, _unsorted_bisect, _negative_dijkstra)
    items = [item for detector in detectors for item in detector(tree, path, root, names)]
    specific_membership_sites = {
        (item["primary_location"]["file"], item["primary_location"]["line"])
        for item in items if item["rule_id"] == "pbp.algorithm.dedup.quadratic-membership"
    }
    return [
        item for item in items
        if item["rule_id"] != "pbp.algorithm.search.repeated-linear-membership"
        or (item["primary_location"]["file"], item["primary_location"]["line"]) not in specific_membership_sites
    ]