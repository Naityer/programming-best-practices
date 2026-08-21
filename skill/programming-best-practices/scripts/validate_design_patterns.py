#!/usr/bin/env python3
"""Validate design-patterns.json without third-party packages — same style as
validate_report.py, against references/design-patterns/design-pattern-result.schema.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

STATUSES = {"detected", "partial", "misimplemented", "refactor-opportunity", "ambiguous"}
CONFIDENCES = {"high", "medium", "low"}
EVIDENCE_KINDS = {"hard", "behavioral", "supporting", "contradiction"}
UML_CLASSIFIERS = {"class", "abstract", "interface"}
UML_RELATION_TYPES = {"generalization", "realization", "association", "dependency", "aggregation", "composition"}


def _required(obj: dict[str, Any], fields: set[str], path: str, errors: list[str]) -> None:
    for field in sorted(fields - obj.keys()):
        errors.append(f"{path}.{field}: missing required field")


def _unknown(obj: dict[str, Any], allowed: set[str], path: str, errors: list[str]) -> None:
    for field in sorted(obj.keys() - allowed):
        errors.append(f"{path}.{field}: unexpected field")


def _enum(value: Any, values: set[str], path: str, errors: list[str]) -> None:
    if value not in values:
        errors.append(f"{path}: expected one of {sorted(values)}, got {value!r}")


def _nonempty_string(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value:
        errors.append(f"{path}: expected non-empty string")

def _validate_uml(uml: Any, path: str, errors: list[str]) -> None:
    if not isinstance(uml, dict):
        errors.append(f"{path}: expected object or null")
        return
    fields = {"notation", "nodes", "relationships"}
    _required(uml, fields, path, errors)
    _unknown(uml, fields, path, errors)
    if uml.get("notation") != "UML 2.5.1":
        errors.append(f"{path}.notation: expected 'UML 2.5.1'")

    nodes = uml.get("nodes")
    if not isinstance(nodes, list):
        errors.append(f"{path}.nodes: expected array")
    else:
        node_fields = {"role", "name", "bound", "classifier"}
        for index, node in enumerate(nodes):
            node_path = f"{path}.nodes[{index}]"
            if not isinstance(node, dict):
                errors.append(f"{node_path}: expected object")
                continue
            _required(node, node_fields, node_path, errors)
            _unknown(node, node_fields, node_path, errors)
            _nonempty_string(node.get("role"), f"{node_path}.role", errors)
            if node.get("name") is not None:
                _nonempty_string(node.get("name"), f"{node_path}.name", errors)
            if not isinstance(node.get("bound"), bool):
                errors.append(f"{node_path}.bound: expected boolean")
            _enum(node.get("classifier"), UML_CLASSIFIERS, f"{node_path}.classifier", errors)

    relationships = uml.get("relationships")
    if not isinstance(relationships, list):
        errors.append(f"{path}.relationships: expected array")
        return
    rel_fields = {"source_role", "target_role", "type", "label", "source_multiplicity", "target_multiplicity"}
    for index, relation in enumerate(relationships):
        rel_path = f"{path}.relationships[{index}]"
        if not isinstance(relation, dict):
            errors.append(f"{rel_path}: expected object")
            continue
        _required(relation, rel_fields, rel_path, errors)
        _unknown(relation, rel_fields, rel_path, errors)
        _nonempty_string(relation.get("source_role"), f"{rel_path}.source_role", errors)
        _nonempty_string(relation.get("target_role"), f"{rel_path}.target_role", errors)
        _nonempty_string(relation.get("label"), f"{rel_path}.label", errors)
        _enum(relation.get("type"), UML_RELATION_TYPES, f"{rel_path}.type", errors)
        for field in ("source_multiplicity", "target_multiplicity"):
            if relation.get(field) is not None:
                _nonempty_string(relation.get(field), f"{rel_path}.{field}", errors)


def validate_design_patterns(data: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["$: expected object"]

    top_fields = {"schema_version", "files_scanned", "languages", "patterns", "limitations", "effective_scope"}
    _required(data, top_fields, "$", errors)
    _unknown(data, top_fields, "$", errors)
    if data.get("schema_version") != "1.0.0":
        errors.append("$.schema_version: expected '1.0.0'")

    files_scanned = data.get("files_scanned")
    if not isinstance(files_scanned, int) or isinstance(files_scanned, bool) or files_scanned < 0:
        errors.append("$.files_scanned: expected non-negative integer")

    languages = data.get("languages")
    if not isinstance(languages, list) or any(not isinstance(item, str) or not item for item in languages):
        errors.append("$.languages: expected array of non-empty strings")

    _nonempty_string(data.get("effective_scope"), "$.effective_scope", errors)

    patterns = data.get("patterns")
    if not isinstance(patterns, list):
        errors.append("$.patterns: expected array")
    else:
        pattern_fields = {
            "pattern_id", "status", "confidence", "primary_location", "roles",
            "evidence", "contradictions", "refactoring", "uml_artifact", "uml",
        }
        required = {"pattern_id", "status", "confidence", "primary_location", "roles", "evidence", "contradictions"}
        for index, item in enumerate(patterns):
            path = f"$.patterns[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{path}: expected object")
                continue
            _required(item, required, path, errors)
            _unknown(item, pattern_fields, path, errors)
            _nonempty_string(item.get("pattern_id"), f"{path}.pattern_id", errors)
            _enum(item.get("status"), STATUSES, f"{path}.status", errors)
            _enum(item.get("confidence"), CONFIDENCES, f"{path}.confidence", errors)

            location = item.get("primary_location")
            if not isinstance(location, dict):
                errors.append(f"{path}.primary_location: expected object")
            else:
                _required(location, {"file", "line"}, f"{path}.primary_location", errors)
                _unknown(location, {"file", "line"}, f"{path}.primary_location", errors)
                _nonempty_string(location.get("file"), f"{path}.primary_location.file", errors)
                line = location.get("line")
                if not isinstance(line, int) or isinstance(line, bool) or line < 1:
                    errors.append(f"{path}.primary_location.line: expected positive integer")

            roles = item.get("roles")
            if not isinstance(roles, dict) or any(not isinstance(v, str) or not v for v in roles.values()):
                errors.append(f"{path}.roles: expected object of non-empty strings")

            evidence = item.get("evidence")
            if not isinstance(evidence, list):
                errors.append(f"{path}.evidence: expected array")
            else:
                for ev_index, entry in enumerate(evidence):
                    ev_path = f"{path}.evidence[{ev_index}]"
                    if not isinstance(entry, dict):
                        errors.append(f"{ev_path}: expected object")
                        continue
                    _required(entry, {"kind", "description"}, ev_path, errors)
                    _unknown(entry, {"kind", "description"}, ev_path, errors)
                    _enum(entry.get("kind"), EVIDENCE_KINDS, f"{ev_path}.kind", errors)
                    _nonempty_string(entry.get("description"), f"{ev_path}.description", errors)

            contradictions = item.get("contradictions")
            if not isinstance(contradictions, list):
                errors.append(f"{path}.contradictions: expected array")
            else:
                for c_index, entry in enumerate(contradictions):
                    c_path = f"{path}.contradictions[{c_index}]"
                    if not isinstance(entry, dict):
                        errors.append(f"{c_path}: expected object")
                        continue
                    _required(entry, {"pattern_id", "reason"}, c_path, errors)
                    _unknown(entry, {"pattern_id", "reason"}, c_path, errors)
                    _nonempty_string(entry.get("pattern_id"), f"{c_path}.pattern_id", errors)
                    _nonempty_string(entry.get("reason"), f"{c_path}.reason", errors)

            if "refactoring" in item and item["refactoring"] is not None and not isinstance(item["refactoring"], dict):
                errors.append(f"{path}.refactoring: expected object or null")
            if "uml_artifact" in item and item["uml_artifact"] is not None and not isinstance(item["uml_artifact"], str):
                errors.append(f"{path}.uml_artifact: expected string or null")

            # spec §14/§31.8: a lexical-only detection must never be `high`.
            if item.get("confidence") == "high" and item.get("status") not in {"detected", "misimplemented"}:
                errors.append(f"{path}.confidence: 'high' is only meaningful for 'detected'/'misimplemented', got status {item.get('status')!r}")

    limitations = data.get("limitations")
    if not isinstance(limitations, list) or any(not isinstance(item, str) for item in limitations):
        errors.append("$.limitations: expected array of strings")

    return errors


def load_and_validate(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return None, [f"$: cannot read input: {exc}"]
    except json.JSONDecodeError as exc:
        return None, [f"$: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"]
    errors = validate_design_patterns(data)
    return data if isinstance(data, dict) else None, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    _, errors = load_and_validate(args.report)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 2
    print("valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
