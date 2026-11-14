"""High-precision Python misuse detectors from Atlas cases 40–47."""

from __future__ import annotations

import ast
import re
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


# Qué se sabe de un nombre sin ejecutar nada: lo que dice su anotación o lo que se le asigna en su función. Sin evidencia, no se asume.
_HASH_CALLS = {"set", "frozenset", "dict", "defaultdict", "Counter", "OrderedDict"}
_HASH_ANNOTATION = re.compile(r"^\s*(typing\.|collections\.abc\.|collections\.)?(set|frozenset|dict|Set|FrozenSet|Dict|Mapping|MutableMapping|AbstractSet|MutableSet|DefaultDict|defaultdict|Counter|OrderedDict)\b")
_LIST_ANNOTATION = re.compile(r"^\s*(typing\.)?(list|List|MutableSequence)\b")
_MEMOIZERS = {"lru_cache", "cache", "memoize", "memoized", "memoise", "cached", "cached_property", "cache_result"}


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


def _scope_of(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> ast.AST:
    current = parents.get(node)
    while current is not None and not isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.Module)):
        current = parents.get(current)
    return current if current is not None else node


def _parameter_annotation(scope: ast.AST, name: str) -> str | None:
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        arguments = scope.args
        for argument in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]:
            if argument.arg == name and argument.annotation is not None:
                return ast.unparse(argument.annotation)
    return None


def _assigned_values(scope: ast.AST, name: str) -> list[ast.AST | None]:
    """Todo lo que se le asigna a `name` en el ámbito; None = una asignación cuyo valor no se conoce (+=, bucle…)."""
    values: list[ast.AST | None] = []
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            values.append(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            values.append(node.value)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            values.append(None)
        elif isinstance(node, (ast.For, ast.AsyncFor)) and any(isinstance(t, ast.Name) and t.id == name for t in ast.walk(node.target)):
            values.append(None)
    return values


def _is_hash_build(value: ast.AST | None) -> bool:
    if isinstance(value, (ast.Set, ast.Dict, ast.SetComp, ast.DictComp)):
        return True
    if isinstance(value, ast.Call):
        function = value.func
        name = function.id if isinstance(function, ast.Name) else function.attr if isinstance(function, ast.Attribute) else ""
        return name in _HASH_CALLS or name == "fromkeys"
    return False


def _is_list_build(value: ast.AST | None) -> bool:
    if isinstance(value, (ast.List, ast.ListComp)):
        return True
    if isinstance(value, ast.BinOp) and isinstance(value.op, (ast.Mult, ast.Add)):
        return _is_list_build(value.left) or _is_list_build(value.right)
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
        return value.func.id in {"list", "sorted"}
    return False


def _known_hashed(container: ast.AST, node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """¿Es `container` un conjunto o un diccionario ya construido? Entonces `x in container` es O(1), no O(n)."""
    if not isinstance(container, ast.Name):
        return False
    scope = _scope_of(node, parents)
    annotation = _parameter_annotation(scope, container.id)
    if annotation is not None:
        return bool(_HASH_ANNOTATION.match(annotation))
    values = _assigned_values(scope, container.id)
    return bool(values) and all(_is_hash_build(v) for v in values)


def _known_list(receiver: ast.AST, node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """¿Es `receiver` una lista, por su anotación o porque solo se le asignan listas en su función?"""
    if not isinstance(receiver, ast.Name):
        return False
    scope = _scope_of(node, parents)
    annotation = _parameter_annotation(scope, receiver.id)
    if annotation is not None:
        return bool(_LIST_ANNOTATION.match(annotation))
    values = _assigned_values(scope, receiver.id)
    return bool(values) and all(_is_list_build(v) for v in values)


def _decorator_name(decorator: ast.AST) -> str:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return target.id if isinstance(target, ast.Name) else target.attr if isinstance(target, ast.Attribute) else ""


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
    parents = _parents(tree)
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
        if isinstance(container, (ast.Set, ast.Dict)) or _known_hashed(container, node, parents):
            continue  # ya es un índice hash: `x in container` es O(1)
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
    parents = _parents(tree)
    assigned_lists = {
        target.id for node in ast.walk(tree) if isinstance(node, ast.Assign) and isinstance(node.value, ast.List)
        for target in node.targets if isinstance(target, ast.Name)
    }
    loops = [node for node in ast.walk(tree) if isinstance(node, (ast.For, ast.While, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))]
    for call in [node for node in ast.walk(tree) if isinstance(node, ast.Call)]:
        if not isinstance(call.func, ast.Attribute) or call.func.attr != "pop" or not isinstance(call.func.value, ast.Name):
            continue
        if not call.args or not isinstance(call.args[0], ast.Constant) or call.args[0].value != 0:
            continue
        annotation = _parameter_annotation(_scope_of(call, parents), call.func.value.id)
        # Una lista creada con un literal en el módulo, o un parámetro ANOTADO como lista: sin una de las dos, no se sabe qué tipo es.
        if call.func.value.id not in assigned_lists and not (annotation is not None and _LIST_ANNOTATION.match(annotation)):
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
        if any(_decorator_name(d) in _MEMOIZERS for d in fn.decorator_list):
            continue  # lru_cache / cache / memoize: ya está memoizada
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


def _index_in_loop(tree: ast.AST, path: Path, root: Path, names: dict[ast.AST, str]) -> list[dict[str, Any]]:
    """`lista.index(x)` dentro de un bucle: cada búsqueda recorre la lista, O(n·m). Solo si se sabe que el receptor es una lista (no un `str`)."""
    output = []
    parents = _parents(tree)
    loops = [node for node in ast.walk(tree) if isinstance(node, (ast.For, ast.While, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))]
    for call in [node for node in ast.walk(tree) if isinstance(node, ast.Call)]:
        if not isinstance(call.func, ast.Attribute) or call.func.attr != "index" or not call.args:
            continue
        if not any(_inside(call, loop) for loop in loops) or not _known_list(call.func.value, call, parents):
            continue
        output.append(make_occurrence(
            algorithm_id="search.hash-lookup", rule_id="pbp.algorithm.search.repeated-linear-index",
            family="search", status="refactor-opportunity", confidence="medium",
            location=_location(path, root, call, tree, names), problem="locate elements by value repeatedly",
            current_approach="list.index() inside a loop", current_time="O(n*m)", expected_time="O(n+m) average",
            evidence=[{"kind": "ast", "description": f"{call.func.value.id} is a list and .index() is called inside a loop: every call scans it from the start."}],
            requirements=[
                _req("index() returns the FIRST occurrence", "UNKNOWN", True, "A value-to-position map must keep the first position when values repeat."),
                _req("the list is not modified between lookups", "UNKNOWN", True, "Mutations would invalidate a precomputed map."),
            ],
            alternatives=[{"algorithm_id": "search.hash-lookup", "eligible": False, "reason": "Duplicates and mutation remain UNKNOWN."}],
            recommendation=_recommend("Build a value-to-position dict once before the loop (keeping the first position) if the list does not change meanwhile.", "ASSISTED", "differential-test with duplicate values", "benchmark representative sizes"),
        ))
    return output


def _list_rebuild(tree: ast.AST, path: Path, root: Path, names: dict[ast.AST, str]) -> list[dict[str, Any]]:
    """`x = x + [v]` dentro de un bucle: cada vuelta copia toda la lista, O(n^2). `x.append(v)` es O(1) amortizado."""
    output = []
    parents = _parents(tree)
    loops = [node for node in ast.walk(tree) if isinstance(node, (ast.For, ast.While))]
    for node in [n for n in ast.walk(tree) if isinstance(n, ast.Assign)]:
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name) or not isinstance(node.value, ast.BinOp) or not isinstance(node.value.op, ast.Add):
            continue
        name = node.targets[0].id
        left, right = node.value.left, node.value.right
        own_side, other_side = (left, right) if isinstance(left, ast.Name) and left.id == name else (right, left) if isinstance(right, ast.Name) and right.id == name else (None, None)
        if own_side is None or not isinstance(other_side, (ast.List, ast.ListComp)):
            continue
        if not any(_inside(node, loop) for loop in loops) or not _known_list(own_side, node, parents):
            continue
        output.append(make_occurrence(
            algorithm_id="sequences.buffered-concatenation", rule_id="pbp.algorithm.sequence.repeated-list-rebuild",
            family="sequences", status="refactor-opportunity", confidence="high",
            location=_location(path, root, node, tree, names), problem="grow a list while iterating",
            current_approach="list rebuilt with + on every iteration", current_time="O(n^2)", expected_time="O(n)",
            evidence=[{"kind": "ast", "description": f"`{name} = {name} + [...]` inside a loop copies the whole list on every iteration."}],
            requirements=[_req("the list is not aliased elsewhere", "UNKNOWN", True, "`+` creates a new list; `append` mutates the shared one, so aliases would observe the change.")],
            alternatives=[{"algorithm_id": "sequences.buffered-concatenation", "eligible": False, "reason": "Aliasing remains UNKNOWN."}],
            recommendation=_recommend("Use `append`/`extend` (or a comprehension) once aliases are ruled out.", "ASSISTED", "reanalyze", "differential-test with aliased lists"),
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
    detectors = (_repeated_membership, _quadratic_dedup, _queue_pop_zero, _recursive_fibonacci, _index_in_loop, _list_rebuild, _unsorted_bisect, _negative_dijkstra)
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