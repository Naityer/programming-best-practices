"""Data-driven recognition of vetted standard-library mappings."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .model import make_occurrence, relative_location

CATALOG = Path(__file__).resolve().parent.parent.parent / "references" / "algorithms" / "catalog.json"


@lru_cache(maxsize=1)
def catalog_version() -> str:
    return str(json.loads(CATALOG.read_text(encoding="utf-8")).get("catalog_version", "unknown"))

@lru_cache(maxsize=1)
def _mappings() -> dict[str, list[tuple[str, str, str]]]:
    document = json.loads(CATALOG.read_text(encoding="utf-8"))
    result: dict[str, list[tuple[str, str, str]]] = {}
    for entry in document.get("algorithms", []):
        for language, values in entry.get("standard_mappings", {}).items():
            for value in values:
                result.setdefault(language, []).append((str(value), entry["id"], entry["family"]))
    return result


def _language_key(language: str) -> str:
    return {"kotlin": "java", "typescript": "javascript", "c": "cpp"}.get(language, language)


def _operation_text(operation: dict[str, Any]) -> str:
    attributes = operation.get("attributes", {})
    return str(
        attributes.get("callee_text") or attributes.get("callee")
        or attributes.get("expression") or operation.get("text") or ""
    )


def _matches(mapping: str, operation_text: str) -> bool:
    token = mapping.rsplit(".", 1)[-1].lower()
    text = operation_text.lower()
    if mapping.lower() in text:
        return True
    return bool(re.search(rf"(?<![a-z0-9_]){re.escape(token)}\s*\(", text)) or text == token


def recognize_catalog_apis(ir: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    language = _language_key(str(ir.get("language")))
    mappings = _mappings().get(language, [])
    if not mappings:
        return []
    file = str(ir.get("file") or "unknown")
    output: list[dict[str, Any]] = []
    for function in ir.get("functions", []):
        for operation in function.get("operations", []):
            if operation.get("kind") not in {"call", "sort", "binary-search", "queue-operation"}:
                continue
            text = _operation_text(operation)
            for mapping, algorithm_id, family in mappings:
                if not _matches(mapping, text):
                    continue
                raw_location = operation.get("location", {})
                line = int(raw_location.get("line") or operation.get("line") or 1)
                qualified = raw_location.get("qualified_name") or operation.get("qualified_name")
                location = relative_location(root / file, root, line, qualified)
                output.append(make_occurrence(
                    algorithm_id=algorithm_id,
                    rule_id="pbp.algorithm.catalog-api.recognized",
                    family=family, status="recognized", confidence="medium",
                    location=location,
                    problem=f"recognized-standard-api:{algorithm_id}",
                    current_approach=mapping, current_time="implementation-dependent", expected_time=None,
                    evidence=[{"kind": "catalog-mapping", "description": f"Structured call matches the catalog mapping {mapping!r}."}],
                    requirements=[{
                        "name": "runtime binding, overload and semantic preconditions are resolved",
                        "state": "UNKNOWN", "hard": True,
                        "reason": "Static call structure does not prove runtime binding or input contracts.",
                    }],
                    alternatives=[], recommendation=None,
                ))
    return output

