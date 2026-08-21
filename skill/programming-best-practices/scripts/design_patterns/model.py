"""Public result model — the shape written to design-patterns.json (spec §18)
and validated against references/design-patterns/design-pattern-result.schema.json.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Status = Literal["detected", "partial", "misimplemented", "refactor-opportunity", "ambiguous"]
Confidence = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class Location:
    file: str
    line: int

    def to_dict(self) -> dict:
        return {"file": self.file, "line": self.line}


@dataclass(frozen=True)
class EvidenceEntry:
    kind: str
    description: str

    def to_dict(self) -> dict:
        return {"kind": self.kind, "description": self.description}


@dataclass(frozen=True)
class Contradiction:
    """A competing pattern that explains the same structure (spec §10, §12).
    Present only on `status: ambiguous`; the engine refuses to pick a winner.
    """

    pattern_id: str
    reason: str

    def to_dict(self) -> dict:
        return {"pattern_id": self.pattern_id, "reason": self.reason}


@dataclass
class PatternResult:
    pattern_id: str
    status: Status
    confidence: Confidence
    primary_location: Location
    roles: dict[str, str] = field(default_factory=dict)  # role -> qualified_name
    evidence: list[EvidenceEntry] = field(default_factory=list)
    contradictions: list[Contradiction] = field(default_factory=list)
    refactoring: dict | None = None  # {"smell": ..., "candidate_pattern": ...}, only for opportunities
    uml_artifact: str | None = None
    uml: dict | None = None  # renderer-neutral UML bound to repository roles

    def to_dict(self) -> dict:
        return {
            "pattern_id": self.pattern_id,
            "status": self.status,
            "confidence": self.confidence,
            "primary_location": self.primary_location.to_dict(),
            "roles": dict(self.roles),
            "evidence": [item.to_dict() for item in self.evidence],
            "contradictions": [item.to_dict() for item in self.contradictions],
            "refactoring": self.refactoring,
            "uml_artifact": self.uml_artifact,
            "uml": self.uml,
        }


@dataclass
class AnalysisResult:
    files_scanned: int
    languages: list[str]
    patterns: list[PatternResult] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    # spec §17: "repository" when the whole tree was in scope, or
    # "changed files + local dependency context" when findings were narrowed
    # to a requested set of files while still reading the wider repo to
    # resolve Target/Adaptee-style dependencies outside that set.
    effective_scope: str = "repository"

    def to_dict(self) -> dict:
        return {
            "schema_version": "1.0.0",
            "files_scanned": self.files_scanned,
            "languages": sorted(set(self.languages)),
            "patterns": [item.to_dict() for item in self.patterns],
            "limitations": list(self.limitations),
            "effective_scope": self.effective_scope,
        }
