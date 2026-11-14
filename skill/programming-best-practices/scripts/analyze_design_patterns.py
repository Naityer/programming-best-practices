#!/usr/bin/env python3
"""CLI for the design-pattern analyzer (spec §16): source -> IR -> engine ->
design-patterns.json + uml/*.mmd/*.puml.

Read-only by construction: it only ever calls `Path.read_text` on files under
`--root` and `ast.parse`s them (frontends/python.py) — it never imports,
executes, or writes inside the audited repository. `--output`/`--uml-dir` are
expected outside that tree, same convention `run_audit.py` enforces for every
other check's artifact directory.

Always exits 0 once analysis runs, even with zero patterns found or with
`limitations` recorded. It exits 2 only for a genuine operational failure
(unreadable `--root`, unwritable `--output`) — see design-patterns-module/
05-hallazgos-codigo.md trap #1: `run_audit.py` maps a non-zero exit for a
`quality`-category check to `failed`, not `findings`, so exit code must never
be used to signal "patterns were found" the way e.g. ruff uses exit 1.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from analysis_core.files import project_files
from design_patterns.catalog import load_catalog
from design_patterns.detectors import registry
from design_patterns.engine import run_engine
from design_patterns.frontends.python import PythonFrontend
from design_patterns.ir import CodeGraph
from design_patterns.model import AnalysisResult
from design_patterns.misimplementations import detect_misimplementations
from design_patterns.opportunities import detect_opportunities
from design_patterns.uml import artifact_name, build_uml_contract, render_mermaid, render_plantuml

# Same category of exclusion as normalize_tool_output.py's VENDORED_RE, kept
# as a plain name set here rather than importing that module's private regex
# across scripts — see design-patterns-module/04-progreso.md for the
# follow-up to share a single source (and add a `git check-ignore` pass, the
# way normalize_tool_output.py does for tool reports).
_EXCLUDED_DIR_NAMES = {
    ".git", ".venv", "venv", "env", "virtualenv", "node_modules", "bower_components",
    "vendor", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
    "site-packages", "dist", "build", "out", "target", "coverage", "htmlcov",
    ".quality-audit", ".quality-audit-stats", ".next", ".turbo", ".gradle", ".m2",
}


_UNSUPPORTED_SOURCE_LANGUAGES = {
    ".c": "C", ".cc": "C++", ".cpp": "C++", ".cxx": "C++", ".h": "C/C++",
    ".hpp": "C++", ".cs": "C#", ".go": "Go", ".java": "Java", ".js": "JavaScript",
    ".jsx": "JavaScript", ".kt": "Kotlin", ".kts": "Kotlin", ".rs": "Rust",
    ".ts": "TypeScript", ".tsx": "TypeScript",
}


def _is_excluded(root: Path, path: Path) -> bool:
    return any(part in _EXCLUDED_DIR_NAMES for part in path.relative_to(root).parts[:-1])


def _iter_python_files(root: Path) -> list[Path]:
    return [path for path in project_files(root, _EXCLUDED_DIR_NAMES) if path.suffix == ".py"]


def _unsupported_language_limitations(root: Path) -> list[str]:
    counts: dict[str, int] = {}
    for path in project_files(root, _EXCLUDED_DIR_NAMES):
        language = _UNSUPPORTED_SOURCE_LANGUAGES.get(path.suffix.lower())
        if language:
            counts[language] = counts.get(language, 0) + 1
    return [
        f"{language} design-pattern frontend is not operational; {count} source file(s) were not analyzed."
        for language, count in sorted(counts.items())
    ]


def _deduplicate_patterns(patterns):
    """Consolidate one finding identity while preserving all evidence."""
    unique = []
    seen = set()
    for pattern in patterns:
        data = pattern.to_dict()
        fingerprint = json.dumps(
            {
                "pattern_id": data["pattern_id"],
                "status": data["status"],
                "confidence": data["confidence"],
                "primary_location": data["primary_location"],
                "roles": data["roles"],
                "refactoring": data["refactoring"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        if fingerprint in seen:
            existing = next(item for item in unique if json.dumps({
                "pattern_id": item.pattern_id, "status": item.status,
                "confidence": item.confidence,
                "primary_location": item.primary_location.to_dict(),
                "roles": item.roles, "refactoring": item.refactoring,
            }, sort_keys=True, separators=(",", ":")) == fingerprint)
            known_evidence = {(item.kind, item.description) for item in existing.evidence}
            existing.evidence.extend(item for item in pattern.evidence if (item.kind, item.description) not in known_evidence)
            continue
        seen.add(fingerprint)
        unique.append(pattern)
    return unique


def analyze(root: Path, *, uml_dir: Path | None = None, focus: list[str] | None = None) -> AnalysisResult:
    """`focus`: repo-relative paths (spec §17). The graph is always built
    from every file under `root` — Target/Adaptee can live outside a diff —
    but when `focus` is given, only patterns anchored inside it are kept in
    the output. Reading wider than reporting is the point, not a bug.
    """
    root = root.expanduser().resolve(strict=True)
    catalog = load_catalog()
    frontend = PythonFrontend()
    files = _iter_python_files(root)

    units = []
    limitations: list[str] = _unsupported_language_limitations(root)
    for path in files:
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            limitations.append(f"could not read {path.relative_to(root).as_posix()}: {exc}")
            continue
        units.append(frontend.parse(source, path.relative_to(root)))

    relations, frontend_limitations = frontend.build_relations(units)
    limitations.extend(frontend_limitations)

    entities = [entity for unit in units for entity in unit.entities]
    discriminator_branches = [branch for unit in units for branch in unit.discriminator_branches]
    graph = CodeGraph(entities, relations, discriminator_branches, frontend_level=frontend.level)

    patterns, engine_limitations = run_engine(graph, catalog, registry())
    limitations.extend(engine_limitations)
    patterns.extend(result for _, result in detect_misimplementations(graph))
    opportunity_patterns, opportunity_limitations = detect_opportunities(graph)
    patterns.extend(opportunity_patterns)
    limitations.extend(opportunity_limitations)
    patterns = _deduplicate_patterns(patterns)

    effective_scope = "repository"
    if focus:
        focus_set = {Path(item).as_posix() for item in focus}
        patterns = [p for p in patterns if p.primary_location.file in focus_set]
        effective_scope = "changed files + local dependency context"

    for pattern in patterns:
        pattern.uml = build_uml_contract(pattern)

    if uml_dir is not None:
        uml_dir.mkdir(parents=True, exist_ok=True)
        counters: dict[str, int] = {}
        for pattern in patterns:
            counters[pattern.pattern_id] = counters.get(pattern.pattern_id, 0) + 1
            name = artifact_name(pattern, counters[pattern.pattern_id])
            (uml_dir / f"{name}.mmd").write_text(render_mermaid(pattern), encoding="utf-8")
            (uml_dir / f"{name}.puml").write_text(render_plantuml(pattern), encoding="utf-8")
            pattern.uml_artifact = f"uml/{name}.mmd"

    return AnalysisResult(
        files_scanned=len(files),
        languages=["python"] if files else [],
        patterns=patterns,
        limitations=limitations,
        effective_scope=effective_scope,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--uml-dir", type=Path)
    parser.add_argument(
        "--focus", action="append",
        help="Repo-relative path to keep findings anchored to (repeatable). "
             "The whole repo is still read for dependency context (spec §17).",
    )
    args = parser.parse_args()
    try:
        result = analyze(args.root, uml_dir=args.uml_dir, focus=args.focus)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    payload = json.dumps(result.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
