"""Optional Level-B frontend for non-Python languages via tree-sitter.

Not implemented in this corte (design-patterns-module/02-decisiones.md, D4).
Present as the wiring point spec §6 requires ("Tree-sitter es apropiado como
frontend común") and to make the degradation policy explicit and testable:
if `tree_sitter` is not installed, this frontend must never fall back to
regex — regex is explicitly banned as a primary analyzer (spec §6) — and must
never claim a language it cannot actually parse. Callers get a `limitation`
and zero patterns for the affected files, not a guess.
"""

from __future__ import annotations

from pathlib import Path

from .base import SourceUnit

SUPPORTED_SUFFIXES = {
    ".java": "java", ".kt": "kotlin", ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".cs": "csharp", ".go": "go",
    ".rs": "rust", ".c": "c", ".cc": "cpp", ".cpp": "cpp", ".h": "c", ".hpp": "cpp",
}


def available() -> bool:
    try:
        import tree_sitter  # noqa: F401
    except ImportError:
        return False
    return True


class TreeSitterFrontend:
    level = "B"

    def __init__(self) -> None:
        self._ready = available()

    def supports(self, path: Path) -> bool:
        return self._ready and path.suffix in SUPPORTED_SUFFIXES

    def parse(self, source: str, path: Path) -> SourceUnit:
        # Not implemented: no grammar wiring exists yet for any of
        # SUPPORTED_SUFFIXES. supports() only returns True once a grammar is
        # actually registered here — until then this frontend claims nothing,
        # so analyze_design_patterns.py's caller falls back to a `limitation`
        # for those files instead of a silent zero-pattern result that looks
        # like "nothing found" rather than "not analyzed".
        raise NotImplementedError(
            f"tree-sitter frontend has no grammar wired for {path.suffix} yet"
        )

    def build_relations(self, units: list[SourceUnit]) -> tuple[list, list[str]]:
        return [], []
