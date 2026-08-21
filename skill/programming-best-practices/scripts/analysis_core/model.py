"""Small universal IR contract.

The IR records observable facts only. Pattern roles and algorithm recommendations
remain in their domain packages so that sharing the frontend does not couple the
two reasoning engines.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

RequirementState = Literal["PROVEN", "LIKELY", "UNKNOWN", "CONTRADICTED"]


@dataclass(frozen=True)
class SourceLocation:
    file: str
    line: int
    end_line: int | None = None
    qualified_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass(frozen=True)
class Evidence:
    kind: str
    description: str
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {"kind": self.kind, "description": self.description}
        if self.location:
            result["location"] = self.location.to_dict()
        return result


@dataclass(frozen=True)
class Requirement:
    name: str
    state: RequirementState
    hard: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Operation:
    kind: str
    location: SourceLocation
    container_kind: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["location"] = self.location.to_dict()
        return {key: value for key, value in result.items() if value not in (None, {}, [])}


@dataclass(frozen=True)
class ProblemSignature:
    problem: str
    properties: dict[str, Any]
    operations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "problem": self.problem,
            "properties": self.properties,
            "operations": list(self.operations),
        }
