"""Conservative algorithm recognition over a shared, cached structural IR."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .cache import FileAnalysisCache, frontend_fingerprint
from .catalog_recognizer import catalog_version, recognize_catalog_apis
from .correlation import correlate
from .frontends import iter_source_units
from .legacy_engine import _non_python_occurrences, _python_occurrences
from .universal import (
    aggregate_analysis,
    build_unit_ir,
    detect_indexed_behaviors,
    detect_interprocedural,
)


def _relative_file(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _deduplicate(occurrences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prefer the first, usually language-specific, result at one rule/site."""
    unique: dict[tuple[str, str, int], dict[str, Any]] = {}
    for item in occurrences:
        location = item.get("primary_location", {})
        key = (str(item.get("rule_id")), str(location.get("file")), int(location.get("line") or 1))
        unique.setdefault(key, item)
    values = list(unique.values())
    dedup_sites = {
        (item["primary_location"]["file"], item["primary_location"]["line"])
        for item in values if item["rule_id"] == "pbp.algorithm.dedup.quadratic-membership"
    }
    values = [
        item for item in values
        if not (
            item["rule_id"] == "pbp.algorithm.search.repeated-linear-membership"
            and (item["primary_location"]["file"], item["primary_location"]["line"]) in dedup_sites
        )
    ]
    return sorted(
        values,
        key=lambda item: (
            item["primary_location"]["file"], item["primary_location"]["line"], item["rule_id"],
        ),
    )


def analyze_repository(
    root: Path,
    *,
    profile: str = "standard",
    focus: set[str] | None = None,
    cache_dir: Path | None = None,
    use_cache: bool = True,
    profiling_evidence: dict[str, Any] | None = None,
    security_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = root.resolve(strict=True)
    if profile == "fast":
        return {
            "schema_version": "1.0.0", "catalog_version": "0.2.0", "profile": profile,
            "effective_scope": "algorithm analysis omitted by FAST profile", "languages": [],
            "files_scanned": 0, "algorithms": [],
            "analysis": {"ir_version": "1.0.0", "units": [], "operation_index": {}, "metrics": {}, "cache": {"enabled": False, "hits": 0, "misses": 0}},
            "limitations": ["FAST intentionally omits Algorithm Intelligence."],
        }

    cache = FileAnalysisCache(cache_dir, enabled=use_cache)
    occurrences: list[dict[str, Any]] = []
    limitations: list[str] = []
    languages: set[str] = set()
    ir_units: list[dict[str, Any]] = []
    scanned = 0
    for unit in iter_source_units(root):
        scanned += 1
        languages.add(unit.language)
        relative_file = _relative_file(unit.path, root)
        key = cache.key(f"{unit.language}:{relative_file}:{frontend_fingerprint(unit.language)}:catalog-{catalog_version()}", unit.text)
        cached = cache.get(key)
        if cached is not None:
            occurrences.extend(cached.get("occurrences", []))
            limitations.extend(cached.get("limitations", []))
            ir_units.append(cached.get("ir", {}))
            continue

        if unit.language == "python":
            found, problems = _python_occurrences(unit, root)
        else:
            found, problems = _non_python_occurrences(unit, root)
        ir, ir_problems = build_unit_ir(unit.language, unit.text, relative_file)
        found.extend(detect_indexed_behaviors(ir, root))
        found.extend(recognize_catalog_apis(ir, root))
        unit_problems = [*problems, *ir_problems]
        occurrences.extend(found)
        limitations.extend(unit_problems)
        ir_units.append(ir)
        cache.put(key, {"occurrences": found, "limitations": unit_problems, "ir": ir})

    occurrences.extend(detect_interprocedural(ir_units, root, profile))
    if any(language != "python" for language in languages):
        limitations.append(
            "Tree-sitter frontends provide behavioral structural facts across all ecosystems, "
            "but unresolved runtime bindings and types never authorize SAFE corrections."
        )
    if focus:
        normalized = {item.replace("\\", "/").lstrip("./") for item in focus}
        occurrences = [
            item for item in occurrences
            if item["primary_location"]["file"].lstrip("./") in normalized
        ]
        ir_units = [unit for unit in ir_units if str(unit.get("file", "")).lstrip("./") in normalized]
    occurrences = correlate(_deduplicate(occurrences), profiling=profiling_evidence, security=security_evidence)
    return {
        "schema_version": "1.0.0", "catalog_version": "0.2.0", "profile": profile,
        "effective_scope": "repository" if not focus else "changed files + local dependency context",
        "languages": sorted(languages), "files_scanned": scanned,
        "algorithms": occurrences,
        "analysis": aggregate_analysis(ir_units, cache.summary()),
        "limitations": sorted(set(limitations)),
    }

