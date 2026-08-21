"""Universal IR orchestration, indexed detectors and bounded call propagation."""

from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
from typing import Any

try:
    from analysis_core.ir import build_python_ir
except ModuleNotFoundError:  # support isolated package loading used by contract tests
    import importlib.util
    import sys

    ir_path = Path(__file__).resolve().parent.parent / "analysis_core" / "ir.py"
    ir_spec = importlib.util.spec_from_file_location("_pbp_analysis_core_ir", ir_path)
    if ir_spec is None or ir_spec.loader is None:
        raise
    ir_module = importlib.util.module_from_spec(ir_spec)
    sys.modules[ir_spec.name] = ir_module
    ir_spec.loader.exec_module(ir_module)
    build_python_ir = ir_module.build_python_ir

from .model import make_occurrence, relative_location
from .structural_frontend import parse_structural_ir


def build_unit_ir(language: str, text: str, file: str) -> tuple[dict[str, Any], list[str]]:
    if language == "python":
        try:
            return build_python_ir(text, file), []
        except SyntaxError as exc:
            return {"language": language, "file": file, "functions": [], "operation_index": {}, "call_graph": {}}, [
                f"{file}: Python syntax error at line {exc.lineno}; IR was not generated."
            ]
    result, limitations = parse_structural_ir(language, text)
    result["file"] = file
    return result, limitations


def _requirement(name: str, state: str, hard: bool, reason: str) -> dict[str, Any]:
    return {"name": name, "state": state, "hard": hard, "reason": reason}


def _operation_location(operation: dict[str, Any], file: str, root: Path) -> dict[str, Any]:
    location = operation.get("location") or {}
    return relative_location(
        root / file, root, int(location.get("line") or operation.get("line") or 1),
        location.get("qualified_name") or operation.get("qualified_name"),
    )


def _repeated_membership(operation: dict[str, Any], file: str, root: Path, *, via: str | None = None) -> dict[str, Any]:
    location = _operation_location(operation, file, root)
    evidence = "A sequential membership operation executes inside an iteration."
    if via:
        evidence = f"A loop calls {via}, whose bounded local summary performs sequential membership."
    return make_occurrence(
        algorithm_id="hashing.membership-index",
        rule_id="pbp.algorithm.search.repeated-linear-membership",
        family="search", status="refactor-opportunity", confidence="medium",
        location=location, problem="repeated-membership",
        current_approach="sequential membership inside repeated work",
        current_time="O(n*m)", expected_time="O(n+m) average",
        evidence=[{"kind": "algorithmic-ir", "description": evidence}],
        requirements=[
            _requirement("hash/equality semantics are compatible", "UNKNOWN", True, "Runtime element types and equality contracts are unresolved."),
            _requirement("ordering and duplicates are not observably changed", "UNKNOWN", True, "The surrounding contract is unavailable."),
            _requirement("additional index memory is acceptable", "UNKNOWN", True, "Memory constraints are unavailable."),
        ],
        alternatives=[
            {"algorithm_id": "hashing.membership-index", "eligible": False, "reason": "Hard equality, ordering and memory requirements remain UNKNOWN."},
            {"algorithm_id": "search.binary", "eligible": False, "reason": "Sortedness and update frequency are UNKNOWN."},
        ],
        recommendation={
            "summary": "Consider building a standard-library membership index once after proving equality, ordering and memory constraints.",
            "correction_level": "ASSISTED",
            "validation": ["reanalyze", "property-test membership equivalence", "benchmark representative sizes"],
        },
    )


def _repeated_concatenation(operation: dict[str, Any], file: str, root: Path) -> dict[str, Any]:
    location = _operation_location(operation, file, root)
    return make_occurrence(
        algorithm_id="sequences.buffered-concatenation",
        rule_id="pbp.algorithm.sequence.repeated-concatenation",
        family="sequences", status="refactor-opportunity", confidence="medium",
        location=location, problem="incremental-sequence-construction",
        current_approach="repeated addition inside an iteration",
        current_time="implementation-dependent", expected_time="O(n)",
        evidence=[{"kind": "algorithmic-ir", "description": "An additive assignment executes inside an iteration."}],
        requirements=[
            _requirement("the accumulator is an immutable sequence", "UNKNOWN", True, "Runtime type and allocation behavior are unresolved."),
            _requirement("buffering preserves ordering, encoding and side effects", "UNKNOWN", True, "Element conversion and mutation semantics are unresolved."),
        ],
        alternatives=[{"algorithm_id": "sequences.buffered-concatenation", "eligible": False, "reason": "Hard type and side-effect requirements remain UNKNOWN."}],
        recommendation={"summary": "If the accumulator is immutable, prefer the ecosystem's maintained builder/join API after proving conversion and ordering semantics.", "correction_level": "ASSISTED", "validation": ["reanalyze", "differential-test output and exceptions", "benchmark representative sizes"]},
    )

def _nested_join(operation: dict[str, Any], file: str, root: Path) -> dict[str, Any]:
    location = _operation_location(operation, file, root)
    return make_occurrence(
        algorithm_id="data-processing.hash-join", rule_id="pbp.algorithm.data.nested-equality-join",
        family="data-processing", status="refactor-opportunity", confidence="medium",
        location=location, problem="equality-join", current_approach="nested iteration with key equality",
        current_time="O(n*m)", expected_time="O(n+m) average",
        evidence=[{"kind": "algorithmic-ir", "description": "A key-like equality comparison appears under two nested iterations."}],
        requirements=[
            _requirement("the operation is an equality join rather than all-pairs work", "LIKELY", True, "Key-like field syntax is present, but the domain contract is not available."),
            _requirement("join keys are hashable and equality-compatible", "UNKNOWN", True, "Runtime key types are unresolved."),
            _requirement("additional index memory is acceptable", "UNKNOWN", True, "Memory constraints are unavailable."),
        ],
        alternatives=[{"algorithm_id": "data-processing.hash-join", "eligible": False, "reason": "Hard key and memory requirements remain UNKNOWN."}],
        recommendation={"summary": "Consider a standard-library hash index or database join after proving key semantics and memory bounds.", "correction_level": "ASSISTED", "validation": ["differential-test multiplicity and order", "property-test duplicate keys", "benchmark representative cardinalities"]},
    )


def detect_indexed_behaviors(ir: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    file = ir.get("file", "unknown")
    output: list[dict[str, Any]] = []
    enabled = set(ir.get("operation_index", {}))
    for function in ir.get("functions", []):
        operations = function.get("operations", [])
        if "membership" in enabled:
            output.extend(
                _repeated_membership(operation, file, root)
                for operation in operations
                if operation.get("kind") == "membership" and int(operation.get("loop_depth", 0)) > 0 and int(operation.get("attributes", {}).get("literal_size", 9)) > 8
            )
        if "concatenate" in enabled:
            output.extend(
                _repeated_concatenation(operation, file, root)
                for operation in operations
                if operation.get("kind") == "concatenate" and int(operation.get("loop_depth", 0)) > 0
            )
        if "comparison" in enabled:
            for operation in operations:
                attributes = operation.get("attributes", {})
                expression = str(attributes.get("expression") or attributes.get("source") or "")
                key_like = any(marker in expression.lower() for marker in (".id", ".key", "['id']", '["id"]'))
                if operation.get("kind") == "comparison" and int(operation.get("loop_depth", 0)) >= 2 and key_like:
                    output.append(_nested_join(operation, file, root))
    return output


def _call_name(operation: dict[str, Any]) -> str | None:
    attributes = operation.get("attributes", {})
    value = attributes.get("callee") or attributes.get("callee_text")
    if not value:
        return None
    return str(value).split("(", 1)[0].strip().split(".")[-1]


def detect_interprocedural(units: list[dict[str, Any]], root: Path, profile: str) -> list[dict[str, Any]]:
    """Propagate membership facts through direct callees or bounded DEEP paths."""
    max_hops = 1 if profile == "standard" else 3
    functions: dict[str, tuple[str, dict[str, Any]]] = {}
    simple_names: dict[str, list[str]] = defaultdict(list)
    for unit in units:
        for function in unit.get("functions", []):
            name = str(function.get("name") or "<module>")
            key = f"{unit.get('file')}::{name}"
            functions[key] = (str(unit.get("file")), function)
            simple_names[name.split(".")[-1]].append(key)
    output: list[dict[str, Any]] = []
    for _, (file, caller) in functions.items():
        for operation in caller.get("operations", []):
            if operation.get("kind") != "call" or int(operation.get("loop_depth", 0)) < 1:
                continue
            initial = _call_name(operation)
            if not initial:
                continue
            pending = deque((key, 1, initial) for key in simple_names.get(initial, []))
            visited: set[str] = set()
            while pending:
                target_key, depth, path = pending.popleft()
                if target_key in visited or depth > max_hops:
                    continue
                visited.add(target_key)
                _, target = functions[target_key]
                if any(item.get("kind") == "membership" for item in target.get("operations", [])):
                    output.append(_repeated_membership(operation, file, root, via=path))
                    break
                if depth < max_hops:
                    for target_call in target.get("operations", []):
                        callee = _call_name(target_call) if target_call.get("kind") == "call" else None
                        if callee:
                            pending.extend((key, depth + 1, f"{path} -> {callee}") for key in simple_names.get(callee, []))
    return output


def aggregate_analysis(units: list[dict[str, Any]], cache: dict[str, Any]) -> dict[str, Any]:
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    function_count = cfg_nodes = cfg_edges = data_flow_facts = 0
    complexity_counts: dict[str, int] = defaultdict(int)
    for unit in units:
        for function in unit.get("functions", []):
            function_count += 1
            cfg = function.get("cfg", {})
            cfg_nodes += len(cfg.get("nodes", []))
            cfg_edges += len(cfg.get("edges", []))
            data_flow_facts += len(function.get("data_flow", []))
            complexity_counts[str(function.get("complexity", {}).get("worst", "unknown"))] += 1
        for kind, owners in unit.get("operation_index", {}).items():
            index[kind].append({"file": unit.get("file"), "functions": owners})
    return {
        "ir_version": "1.0.0",
        "units": units,
        "operation_index": dict(sorted(index.items())),
        "metrics": {
            "functions": function_count, "cfg_nodes": cfg_nodes, "cfg_edges": cfg_edges,
            "data_flow_facts": data_flow_facts, "complexity": dict(sorted(complexity_counts.items())),
        },
        "cache": cache,
    }

