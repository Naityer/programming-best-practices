"""Loads and validates references/design-patterns/catalog.json.

The catalog is knowledge (roles, conflicts, prose signals), not detection
logic — spec §8 is explicit that "no conviene intentar meter toda la
detección en JSON": the algorithms live in detectors/. This module only
loads, validates, and indexes it by id.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FAMILIES = {"creational", "structural", "behavioral"}

DEFAULT_PATH = (
    Path(__file__).resolve().parents[2] / "references" / "design-patterns" / "catalog.json"
)


@dataclass(frozen=True)
class PatternSpec:
    id: str
    name: str
    family: str
    roles: tuple[str, ...]
    required_relations: tuple[str, ...] = ()
    behavioral_signals: tuple[str, ...] = ()
    conflicts_with: tuple[str, ...] = field(default_factory=tuple)
    opportunity_signal: str = ""


def validate_catalog(data: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["$: expected object"]
    if data.get("schema_version") != "1.0.0":
        errors.append("$.schema_version: expected '1.0.0'")
    patterns = data.get("patterns")
    if not isinstance(patterns, list) or not patterns:
        errors.append("$.patterns: expected non-empty array")
        return errors
    seen_ids: set[str] = set()
    required_fields = {"id", "name", "family", "roles", "required_relations", "conflicts_with"}
    allowed_fields = required_fields | {"behavioral_signals", "opportunity_signal"}
    for index, item in enumerate(patterns):
        path = f"$.patterns[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path}: expected object")
            continue
        missing = required_fields - item.keys()
        for field_name in sorted(missing):
            errors.append(f"{path}.{field_name}: missing required field")
        unknown = item.keys() - allowed_fields
        for field_name in sorted(unknown):
            errors.append(f"{path}.{field_name}: unexpected field")
        pattern_id = item.get("id")
        if not isinstance(pattern_id, str) or not pattern_id:
            errors.append(f"{path}.id: expected non-empty string")
        elif pattern_id in seen_ids:
            errors.append(f"{path}.id: duplicate id {pattern_id!r}")
        else:
            seen_ids.add(pattern_id)
        if item.get("family") not in FAMILIES:
            errors.append(f"{path}.family: expected one of {sorted(FAMILIES)}, got {item.get('family')!r}")
        roles = item.get("roles")
        if not isinstance(roles, list) or not roles or not all(isinstance(r, str) and r for r in roles):
            errors.append(f"{path}.roles: expected non-empty array of non-empty strings")
    for index, item in enumerate(patterns):
        if not isinstance(item, dict):
            continue
        for conflict in item.get("conflicts_with", []) or []:
            if conflict not in seen_ids:
                errors.append(f"$.patterns[{index}].conflicts_with: unknown pattern id {conflict!r}")
    return errors


class Catalog:
    def __init__(self, specs: list[PatternSpec]) -> None:
        self._by_id = {spec.id: spec for spec in specs}

    def __iter__(self):
        return iter(self._by_id.values())

    def __len__(self) -> int:
        return len(self._by_id)

    def get(self, pattern_id: str) -> PatternSpec | None:
        return self._by_id.get(pattern_id)

    def ids(self) -> list[str]:
        return list(self._by_id)


def load_catalog(path: Path = DEFAULT_PATH) -> Catalog:
    data = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_catalog(data)
    if errors:
        raise ValueError("invalid catalog:\n" + "\n".join(errors))
    specs = [
        PatternSpec(
            id=item["id"],
            name=item["name"],
            family=item["family"],
            roles=tuple(item["roles"]),
            required_relations=tuple(item.get("required_relations", [])),
            behavioral_signals=tuple(item.get("behavioral_signals", [])),
            conflicts_with=tuple(item.get("conflicts_with", [])),
            opportunity_signal=item.get("opportunity_signal", ""),
        )
        for item in data["patterns"]
    ]
    return Catalog(specs)
