"""Language-neutral structural IR and the safe Python frontend.

The builders record observable syntax facts.  They deliberately do not infer
runtime types or semantic preconditions that source structure cannot prove.
"""

from __future__ import annotations

import ast
import hashlib
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class IRLocation:
    file: str
    line: int
    end_line: int
    qualified_name: str | None = None


@dataclass(frozen=True)
class AlgorithmicOperation:
    kind: str
    location: IRLocation
    loop_depth: int = 0
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["location"] = asdict(self.location)
        return result


@dataclass(frozen=True)
class CFGNode:
    id: str
    kind: str
    line: int


@dataclass(frozen=True)
class CFGEdge:
    source: str
    target: str
    kind: str = "next"


@dataclass(frozen=True)
class DataFlowFact:
    symbol: str
    definitions: tuple[int, ...]
    uses: tuple[int, ...]
    mutations: tuple[int, ...]
    escapes: bool


@dataclass
class FunctionIR:
    id: str
    name: str
    location: IRLocation
    operations: list[AlgorithmicOperation] = field(default_factory=list)
    cfg_nodes: list[CFGNode] = field(default_factory=list)
    cfg_edges: list[CFGEdge] = field(default_factory=list)
    data_flow: list[DataFlowFact] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    complexity: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "location": asdict(self.location),
            "operations": [item.to_dict() for item in self.operations],
            "cfg": {
                "nodes": [asdict(item) for item in self.cfg_nodes],
                "edges": [asdict(item) for item in self.cfg_edges],
            },
            "data_flow": [asdict(item) for item in self.data_flow],
            "calls": sorted(set(self.calls)),
            "complexity": self.complexity,
        }


def _stable_id(file: str, name: str, line: int) -> str:
    digest = hashlib.sha256(f"{file}:{name}:{line}".encode()).hexdigest()[:16]
    return f"FN-{digest.upper()}"


def _owned_walk(root: ast.AST):
    """Walk one function without attributing nested function bodies to it."""
    pending = [root]
    while pending:
        node = pending.pop()
        yield node
        for child in reversed(list(ast.iter_child_nodes(node))):
            if child is not root and isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
            ):
                continue
            pending.append(child)


def _loop_depth(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> int:
    depth = 0
    current = parents.get(node)
    while current is not None:
        if isinstance(current, (ast.For, ast.AsyncFor, ast.While, ast.comprehension)):
            depth += 1
        current = parents.get(current)
    return depth


def _call_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return "<dynamic>"


def _operation(node: ast.AST, *, file: str, name: str, parents: dict[ast.AST, ast.AST]) -> AlgorithmicOperation | None:
    kind: str | None = None
    attributes: dict[str, Any] = {}
    if isinstance(node, (ast.For, ast.AsyncFor, ast.While, ast.comprehension)):
        kind = "iterate"
    elif isinstance(node, ast.Compare) and any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
        kind = "membership"
        attributes["negated"] = any(isinstance(op, ast.NotIn) for op in node.ops)
        if node.comparators and isinstance(node.comparators[0], ast.Name):
            attributes["container"] = node.comparators[0].id
        if node.comparators and isinstance(node.comparators[0], (ast.List, ast.Tuple)):
            attributes["literal_size"] = len(node.comparators[0].elts)
    elif isinstance(node, ast.Call):
        call_name = _call_name(node)
        kind = "call"
        attributes["callee"] = call_name
        lowered = call_name.lower()
        if lowered in {"sort", "sorted", "qsort"}:
            kind = "sort"
        elif lowered in {"bisect", "bisect_left", "bisect_right", "binary_search", "lower_bound", "upper_bound"}:
            kind = "binary-search"
        elif lowered in {"pop", "popleft", "dequeue"}:
            kind = "queue-operation"
    elif isinstance(node, ast.AugAssign) and isinstance(node.op, (ast.FloorDiv, ast.RShift)):
        divisor = getattr(node.value, "value", None)
        if divisor in {1, 2}:
            kind = "binary-reduction"
    elif isinstance(node, ast.Assign) and isinstance(node.value, ast.BinOp) and isinstance(node.value.op, (ast.FloorDiv, ast.RShift)):
        divisor = getattr(node.value.right, "value", None)
        if divisor in {1, 2}:
            kind = "binary-reduction"
    elif isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add):
        kind = "concatenate"
    elif isinstance(node, ast.Compare):
        kind = "comparison"
        attributes["operators"] = [type(op).__name__ for op in node.ops]
        attributes["expression"] = ast.unparse(node)
    if kind is None:
        return None
    line = max(1, getattr(node, "lineno", 1))
    return AlgorithmicOperation(
        kind=kind,
        location=IRLocation(file, line, max(line, getattr(node, "end_lineno", line)), name),
        loop_depth=_loop_depth(node, parents),
        attributes=attributes,
    )


def _cfg(nodes: list[ast.stmt]) -> tuple[list[CFGNode], list[CFGEdge]]:
    statements = sorted(
        (node for root in nodes for node in ast.walk(root) if isinstance(node, ast.stmt)),
        key=lambda node: (getattr(node, "lineno", 0), getattr(node, "col_offset", 0)),
    )
    cfg_nodes = [CFGNode("entry", "entry", statements[0].lineno if statements else 1)]
    cfg_nodes.extend(CFGNode(f"n{index}", type(node).__name__, node.lineno) for index, node in enumerate(statements))
    cfg_nodes.append(CFGNode("exit", "exit", statements[-1].end_lineno if statements else 1))
    cfg_edges: list[CFGEdge] = []
    previous = "entry"
    for index, node in enumerate(statements):
        current = f"n{index}"
        cfg_edges.append(CFGEdge(previous, current))
        if isinstance(node, ast.If):
            cfg_edges.append(CFGEdge(current, f"n{index + 1}" if index + 1 < len(statements) else "exit", "false"))
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            cfg_edges.append(CFGEdge(current, current, "loop-back"))
        previous = current
    cfg_edges.append(CFGEdge(previous, "exit"))
    return cfg_nodes, cfg_edges


def _data_flow(root: ast.AST) -> list[DataFlowFact]:
    definitions: dict[str, list[int]] = defaultdict(list)
    uses: dict[str, list[int]] = defaultdict(list)
    mutations: dict[str, list[int]] = defaultdict(list)
    escapes: set[str] = set()
    for node in _owned_walk(root):
        if isinstance(node, ast.Name):
            target = definitions if isinstance(node.ctx, (ast.Store, ast.Param)) else uses
            target[node.id].append(getattr(node, "lineno", 1))
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            mutations[node.target.id].append(node.lineno)
        elif isinstance(node, ast.Call):
            for argument in (*node.args, *(keyword.value for keyword in node.keywords)):
                if isinstance(argument, ast.Name):
                    escapes.add(argument.id)
    symbols = sorted(set(definitions) | set(uses) | set(mutations))
    return [
        DataFlowFact(symbol, tuple(definitions[symbol]), tuple(uses[symbol]), tuple(mutations[symbol]), symbol in escapes)
        for symbol in symbols
    ]


def _complexity(operations: list[AlgorithmicOperation], recursive_calls: int) -> dict[str, str]:
    depths = [item.loop_depth + 1 for item in operations if item.kind == "iterate"]
    sort_present = any(item.kind == "sort" for item in operations)
    binary_reduction = any(item.kind == "binary-reduction" for item in operations)
    if binary_reduction:
        return {"average": "O(log n)", "worst": "O(log n)", "space": "O(1)", "basis": "binary reduction inside iteration"}
    if recursive_calls >= 2:
        return {"average": "unknown", "worst": "O(2^n)", "space": "O(n)", "basis": "branching recurrence"}
    if recursive_calls == 1:
        return {"average": "unknown", "worst": "unknown", "space": "O(depth)", "basis": "unresolved recurrence"}
    if depths and max(depths) >= 2:
        return {"average": "unknown", "worst": "O(n*m)", "space": "unknown", "basis": "nested independent iteration"}
    if sort_present and depths:
        return {"average": "O(n log n)", "worst": "implementation-dependent", "space": "implementation-dependent", "basis": "iteration plus library sort"}
    if sort_present:
        return {"average": "O(n log n)", "worst": "implementation-dependent", "space": "implementation-dependent", "basis": "library sort contract"}
    if depths:
        sequential = sum(1 for value in depths if value == 1)
        expression = "O(n+m)" if sequential > 1 else "O(n)"
        return {"average": expression, "worst": expression, "space": "unknown", "basis": "loop structure"}
    return {"average": "unknown", "worst": "unknown", "space": "unknown", "basis": "insufficient structural evidence"}


def build_python_ir(text: str, file: str) -> dict[str, Any]:
    tree = ast.parse(text, filename=file)
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    functions: list[FunctionIR] = []
    candidates: list[tuple[str, ast.AST]] = [("<module>", tree)]
    candidates.extend(
        (node.name, node) for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    local_names = {name for name, _ in candidates if name != "<module>"}
    for name, root in candidates:
        body = list(getattr(root, "body", []))
        line = max(1, getattr(root, "lineno", 1))
        end = max(line, getattr(root, "end_lineno", line))
        operations = [
            operation for node in _owned_walk(root)
            if (operation := _operation(node, file=file, name=name, parents=parents)) is not None
        ]
        calls = [
            _call_name(node) for node in _owned_walk(root)
            if isinstance(node, ast.Call) and _call_name(node) in local_names
        ]
        recursive_calls = sum(1 for call in calls if call == name)
        cfg_nodes, cfg_edges = _cfg(body)
        functions.append(FunctionIR(
            id=_stable_id(file, name, line), name=name,
            location=IRLocation(file, line, end, None if name == "<module>" else name),
            operations=operations, cfg_nodes=cfg_nodes, cfg_edges=cfg_edges,
            data_flow=_data_flow(root), calls=calls,
            complexity=_complexity(operations, recursive_calls),
        ))
    operation_index: dict[str, list[str]] = defaultdict(list)
    for function in functions:
        for operation in function.operations:
            operation_index[operation.kind].append(function.id)
    return {
        "language": "python",
        "file": file,
        "functions": [function.to_dict() for function in functions],
        "operation_index": {key: sorted(set(value)) for key, value in sorted(operation_index.items())},
        "call_graph": {function.id: [target.id for target in functions if target.name in function.calls] for function in functions},
    }

