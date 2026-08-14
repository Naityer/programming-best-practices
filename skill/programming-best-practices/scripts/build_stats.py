#!/usr/bin/env python3
"""Aggregate cross-run tool-compliance, review, and trend statistics.

    python scripts/build_stats.py --root <repo> --output-dir <new-directory>

Reads `report.json` (and, when present, `review-ledger.json`) from every prior
run under `<repo>/.quality-audit/`. Never executes a tool, never re-scans
source, never invents a metric it cannot back with real evidence: anything
not computable from what's on disk comes back `null` with a reason in
`limitations`, the same discipline `report.json` already follows.

**Why this reads history instead of taking one execution.** A single audit
answers "what is true right now". This answers questions that need more than
one point: which tools' findings actually hold up under review, how a metric
is moving, and where two runs disagree. None of that exists in any single
`report.json` — it only exists across the run history that `.quality-audit/`
already accumulates on disk, one timestamped directory per audit.

**Why the confirm/dismiss ratios are never one "reliability" number.** A
single blended score would mix tool-caused noise with agent-asserted claims
that had no tool backing — two different failure modes with different fixes.
`SKILL.md` also forbids inventing a universal quality score; the same rule
applies here. `review` reports named, counted ratios instead, each with its
raw numerator/denominator and a Wilson 95% confidence interval, so a ratio
built from 2 decisions never reads the same as one built from 200.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, TypedDict

from render_stats import render

SCHEMA_VERSION = "1.0.0"
DEFAULT_HISTORY_GLOB = ".quality-audit/*"
DEFAULT_MAX_RUNS = 50
DEFAULT_MIN_SAMPLE = 5
STATS_DIR_NAME = ".quality-audit-stats"

# Qué mide cada herramienta, en prosa. Curado a mano — nunca inferido — porque
# adivinar el dominio de medición de una herramienta desconocida sería
# fabricar documentación. Clave: `output_format`/adaptador (`build_report.py`
# ahora lo conserva en `tools[]`), no el ejecutable: varios checks del mismo
# ecosistema comparten ejecutable genérico (`go`, `cargo`, `dotnet`) pero
# miden cosas distintas.
TOOL_MEASUREMENT_DOMAIN: dict[str, str] = {
    "semgrep": "Static pattern rules matched against source files in the configured ruleset.",
    "gitleaks": "Credential-pattern scan across tracked git history and the working tree.",
    "trivy": "Filesystem/config/dependency scan for known vulnerabilities, secrets, and misconfigurations.",
    "osv-scanner": "Resolved dependency versions checked against the OSV vulnerability database.",
    "coverage-py": "Executed-line/branch percentage across Python source exercised by the test suite.",
    "ruff-json": "Static lint rules matched against Python source files.",
    "jacoco": "Executed-line/branch/instruction percentage across JVM bytecode exercised by tests.",
    "cobertura": "Executed-line/branch percentage reported in Cobertura XML.",
    "lcov": "Executed-line/branch percentage reported in LCOV trace format.",
    "go-cover": "Executed-statement percentage from a Go coverage profile.",
    "llvm-cov": "Executed-line/branch/region/function percentage from LLVM coverage export.",
    "pit": "Mutation kill rate across JVM bytecode mutants.",
    "mutmut": "Mutation kill rate across Python AST mutants.",
    "stryker": "Mutation kill rate across JS/TS mutants.",
    "cargo-mutants": "Mutation kill rate across Rust mutants.",
    "bundle-size": "Shipped byte size and file count of a built web asset directory (measurement, not a verdict).",
    "pytest-benchmark": "Wall-clock timing statistics of Python microbenchmarks.",
    "web-runtime": "Browser runtime probe: idle frame rate, long tasks, load timing on declared targets.",
    "compare-perf-baseline": "Relative comparison of a performance measurement against the repository's committed baseline.",
}

# Sentido de cada métrica de tendencia: True si un valor MÁS ALTO es mejor.
# Tabla curada a mano, igual que el registro de arriba — cualquier métrica sin
# entrada se reporta con su pendiente cruda y sin `direction`, nunca con una
# dirección adivinada.
METRIC_POLARITY: dict[str, bool] = {
    "finding_counts.blocker": False,
    "finding_counts.high": False,
    "finding_counts.medium": False,
    "finding_counts.low": False,
    "coverage.line_percent": True,
    "coverage.branch_percent": True,
    "mutation.score_percent": True,
    "mutation.survived": False,
    "performance.bundle.total_bytes": False,
    "performance.bundle.file_count": False,
}


class RunRef(TypedDict):
    dir: Path
    report: Path
    ledger: Path | None


# ---------------------------------------------------------------------------
# Descubrimiento y carga
# ---------------------------------------------------------------------------


def discover_runs(
    root: Path, history_glob: str = DEFAULT_HISTORY_GLOB, *,
    since: str | None = None, max_runs: int | None = DEFAULT_MAX_RUNS,
) -> list[RunRef]:
    """Localiza ejecuciones previas, más recientes primero, acotadas por `max_runs`.

    El nombre del directorio de cada ejecución es el timestamp
    `%Y%m%dT%H%M%SZ[-N]` que genera `render_report.py` — ordena
    lexicográficamente igual que cronológicamente, así que no hace falta
    parsear `generated_at` solo para ordenar.
    """
    candidates = sorted(root.glob(f"{history_glob}/report.json"), key=lambda p: p.parent.name, reverse=True)
    if since:
        candidates = [p for p in candidates if p.parent.name >= since]
    if max_runs:
        candidates = candidates[:max_runs]
    runs: list[RunRef] = []
    for report_path in reversed(candidates):  # orden cronológico para las series
        ledger_path = report_path.parent / "review-ledger.json"
        runs.append({
            "dir": report_path.parent,
            "report": report_path,
            "ledger": ledger_path if ledger_path.is_file() else None,
        })
    return runs


def load_run(run: RunRef) -> dict[str, Any]:
    """Lee `report.json` y, si existe, `review-ledger.json`. No ejecuta nada."""
    report = json.loads(run["report"].read_text(encoding="utf-8"))
    ledger = json.loads(run["ledger"].read_text(encoding="utf-8")) if run["ledger"] is not None else None
    return {"dir": run["dir"], "report": report, "ledger": ledger}


# ---------------------------------------------------------------------------
# Estadística — §5 del plan: cada función documenta qué responde y cuándo se
# abstiene en vez de inventar.
# ---------------------------------------------------------------------------


def _mean_stdev(values: list[float]) -> tuple[float | None, float | None]:
    """Media y desviación típica muestral (`n-1`). `stdev` es `None` con `n<2`:
    no hay varianza definible en un solo punto, y `0.0` mentiría diciendo que
    hay certeza donde solo hay ausencia de dato."""
    if not values:
        return None, None
    mean = statistics.mean(values)
    stdev = statistics.stdev(values) if len(values) >= 2 else None
    return mean, stdev


def _ols_trend(points: list[tuple[float, float]]) -> tuple[float | None, float | None]:
    """Pendiente de mínimos cuadrados y su error estándar.

    `points` son (días desde la primera ejecución, valor) — se usa el tiempo
    transcurrido, no el índice de ejecución, para no distorsionar la pendiente
    por auditorías espaciadas de forma irregular.
    """
    n = len(points)
    if n < 2:
        return None, None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    sxx = sum((x - x_mean) ** 2 for x in xs)
    if sxx == 0:
        return None, None  # todas las ejecuciones en el mismo instante: sin eje temporal
    sxy = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    slope = sxy / sxx
    if n < 3:
        return slope, None  # el error estándar de la pendiente no está definido con 2 puntos
    residuals = [y - (y_mean + slope * (x - x_mean)) for x, y in zip(xs, ys)]
    residual_variance = sum(r * r for r in residuals) / (n - 2)
    se = (residual_variance / sxx) ** 0.5
    return slope, se


def _trend_direction(slope: float | None, se: float | None, n: int, metric_path: str) -> str:
    """Clasifica la tendencia sin umbral inventado: la pendiente se compara
    contra su propio error estándar (una prueba de significancia estándar),
    no contra un porcentaje de cambio arbitrario."""
    if n < 3 or slope is None:
        return "insufficient_data"
    if se is None or abs(slope) <= se:
        return "not_distinguishable_from_noise"
    polarity = METRIC_POLARITY.get(metric_path)
    if polarity is None:
        return "unknown_polarity"
    return "improving" if (slope > 0) == polarity else "worsening"


def _wilson_interval(k: int, n: int, z: float = 1.96) -> list[float] | None:
    """Intervalo de confianza de Wilson al 95% para una proporción `k/n`.

    Más fiable que la aproximación normal cuando `n` es pequeño — el caso
    habitual al empezar a usar la skill en un repositorio — porque no puede
    salirse de [0, 1] ni colapsar a un punto con muestras minúsculas.
    """
    if n <= 0:
        return None
    p = k / n
    denom = 1 + (z * z) / n
    center = (p + (z * z) / (2 * n)) / denom
    margin = (z * ((p * (1 - p) / n) + (z * z) / (4 * n * n)) ** 0.5) / denom
    return [round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4)]


def _rate(confirmed: int, dismissed: int, *, min_sample: int) -> dict[str, Any]:
    """Ratio de confirmación/falsos-positivos con su intervalo de Wilson.

    Por debajo de `min_sample` decisiones revisadas, el ratio sale `null` con
    `sample_size_warning: true` en vez de un 100%/0% que sobre 1 decisión no
    es una señal, es ruido con un signo delante.
    """
    reviewed = confirmed + dismissed
    if reviewed < min_sample:
        return {
            "reviewed": reviewed, "confirmed": confirmed, "dismissed": dismissed,
            "confirmation_rate": None, "false_positive_rate": None,
            "confirmation_rate_ci95": None, "false_positive_rate_ci95": None,
            "sample_size_warning": True,
        }
    return {
        "reviewed": reviewed, "confirmed": confirmed, "dismissed": dismissed,
        "confirmation_rate": round(confirmed / reviewed, 4),
        "false_positive_rate": round(dismissed / reviewed, 4),
        "confirmation_rate_ci95": _wilson_interval(confirmed, reviewed),
        "false_positive_rate_ci95": _wilson_interval(dismissed, reviewed),
        "sample_size_warning": False,
    }


def _days_since(epoch: datetime, timestamp: str | None) -> float | None:
    if not timestamp:
        return None
    try:
        moment = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (moment - epoch).total_seconds() / 86400.0


def _flatten_numeric(node: Any, prefix: str = "") -> Iterator[tuple[str, float]]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _flatten_numeric(value, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(node, bool):
        return
    elif isinstance(node, (int, float)):
        yield prefix, float(node)


def _parse_tool_name(name: str) -> tuple[str, str | None]:
    """`"<check-id> (<tool>)"` -> `(check-id, tool)`. `tool` es `None` si el
    nombre no sigue el formato esperado (defensivo, no debería ocurrir con
    `report.json` generado por `build_report.py`)."""
    if name.endswith(")") and " (" in name:
        check_id, _, rest = name.rpartition(" (")
        return check_id, rest[:-1]
    return name, None


# ---------------------------------------------------------------------------
# Ledger — mapa fingerprint -> acción, y snapshots de lo descartado
# ---------------------------------------------------------------------------


def _review_status_map(ledger_doc: dict[str, Any] | None) -> dict[str, str]:
    status: dict[str, str] = {}
    if not ledger_doc:
        return status
    for decision in ledger_doc.get("decisions", []):
        action = decision.get("action")
        for item in decision.get("matched", []):
            fingerprint = item.get("fingerprint")
            if fingerprint:
                status[fingerprint] = action
    return status


# ---------------------------------------------------------------------------
# Secciones de `stats.json`
# ---------------------------------------------------------------------------


def _current_run_section(latest: dict[str, Any], run_dir: Path, root: Path) -> dict[str, Any]:
    audit = latest.get("audit", {})
    try:
        rel = str(run_dir.relative_to(root).as_posix())
    except ValueError:
        rel = str(run_dir)
    return {
        "run_dir": rel,
        "generated_at": audit.get("generated_at"),
        "profile": audit.get("profile"),
        "scope": audit.get("scope"),
        "outcome": audit.get("outcome"),
        "finding_counts": latest.get("summary", {}).get("finding_counts", {}),
        "dimensions_snapshot": latest.get("summary", {}).get("dimensions", {}),
    }


def _timeline_entry(finding: dict[str, Any], run_dir: str, generated_at: str | None, review_status: str) -> dict[str, Any]:
    location = (finding.get("locations") or [{}])[0]
    evidence = finding.get("evidence") or [{}]
    first = evidence[0] if isinstance(evidence[0], dict) else {}
    return {
        "generated_at": generated_at,
        "run_dir": run_dir,
        "tool": first.get("source", "unknown"),
        "rule_id": finding.get("rule_id"),
        "category": finding.get("category"),
        "severity": finding.get("severity"),
        "confidence": finding.get("confidence"),
        "file": location.get("file"),
        "line": location.get("line"),
        "review_status": review_status,
        "sample_evidence": first.get("message", ""),
    }


def _timeline_entry_from_snapshot(item: dict[str, Any], run_dir: str, generated_at: str | None) -> dict[str, Any]:
    location = (item.get("locations") or [{}])[0]
    return {
        "generated_at": generated_at,
        "run_dir": run_dir,
        "tool": item.get("primary_source", "unknown"),
        "rule_id": item.get("rule_id"),
        "category": item.get("category"),
        "severity": item.get("severity"),
        "confidence": item.get("confidence"),
        "file": location.get("file"),
        "line": location.get("line"),
        "review_status": "dismissed",
        "sample_evidence": item.get("primary_message") or "",
    }


def _findings_timeline_for_run(run: dict[str, Any], run_dir_label: str) -> list[dict[str, Any]]:
    report = run["report"]
    ledger = run.get("ledger")
    generated_at = report.get("audit", {}).get("generated_at")
    status_map = _review_status_map(ledger)
    entries = []
    for finding in report.get("findings", []):
        action = status_map.get(finding.get("fingerprint"))
        review_status = "confirmed" if action == "confirm" else "unreviewed"
        entries.append(_timeline_entry(finding, run_dir_label, generated_at, review_status))
    if ledger:
        for decision in ledger.get("decisions", []):
            if decision.get("action") != "dismiss":
                continue
            for item in decision.get("matched", []):
                entries.append(_timeline_entry_from_snapshot(item, run_dir_label, generated_at))
    return entries


def _run_dir_label(run_dir: Path, root: Path) -> str:
    try:
        return str(run_dir.relative_to(root).as_posix())
    except ValueError:
        return str(run_dir)


def _by_tool_section(runs: list[dict[str, Any]], root: Path, timeline_by_run: list[list[dict[str, Any]]],
                      *, plan: dict[str, Any] | None, min_sample: int) -> dict[str, Any]:
    by_tool: dict[str, dict[str, Any]] = {}
    for run, timeline in zip(runs, timeline_by_run):
        report = run["report"]
        run_label = _run_dir_label(run["dir"], root)
        for tool_item in report.get("tools", []):
            name = tool_item.get("name")
            if not name:
                continue
            entry = by_tool.setdefault(name, {
                "runs_seen": 0, "status_histogram": {}, "durations_ms": [], "_findings": [],
                "category": None, "output_format": None, "gate": None,
                "last_command": None, "last_version": None, "last_run": None,
            })
            entry["runs_seen"] += 1
            status = tool_item.get("status", "unknown")
            entry["status_histogram"][status] = entry["status_histogram"].get(status, 0) + 1
            if status not in {"skipped", "unavailable"}:
                entry["durations_ms"].append(float(tool_item.get("duration_ms", 0)))
            if tool_item.get("category"):
                entry["category"] = tool_item["category"]
            if tool_item.get("output_format"):
                entry["output_format"] = tool_item["output_format"]
            if "gate" in tool_item:
                entry["gate"] = tool_item["gate"]
            if tool_item.get("command"):
                entry["last_command"] = tool_item["command"]
                entry["last_version"] = tool_item.get("version")
                entry["last_run"] = run_label

            # Los hallazgos de la línea de tiempo se etiquetan por `evidence[0].source`
            # (p.ej. "semgrep"), que en esta skill coincide deliberadamente con
            # `check["tool"]` — el token entre paréntesis del nombre del check —
            # para los checks que sí producen hallazgos.
            _, tool_token = _parse_tool_name(name)
            entry["_findings"].extend(item for item in timeline if item.get("tool") == tool_token)

    plan_tool_index: dict[str, Any] = {}
    if plan:
        for check in plan.get("checks", []):
            plan_tool_index[check.get("id")] = check

    result: dict[str, Any] = {}
    for name, entry in by_tool.items():
        findings_here = entry.pop("_findings", [])
        confirmed = sum(1 for f in findings_here if f["review_status"] == "confirmed")
        dismissed = sum(1 for f in findings_here if f["review_status"] == "dismissed")
        mean, stdev = _mean_stdev(entry["durations_ms"])
        output_format = entry["output_format"]
        check_id, _ = _parse_tool_name(name)
        coverage_of_codebase: dict[str, Any]
        if plan and check_id in plan_tool_index:
            coverage_of_codebase = {
                "computable": True,
                "effective_scope": plan_tool_index[check_id].get("effective_scope", "repository"),
            }
        else:
            coverage_of_codebase = {"computable": False, "reason": "requires --plan; not supplied"}
        result[name] = {
            "runs_seen": entry["runs_seen"],
            "status_histogram": dict(sorted(entry["status_histogram"].items())),
            "measurement_domain": TOOL_MEASUREMENT_DOMAIN.get(output_format),
            "measurement_domain_source": "static-registry" if output_format in TOOL_MEASUREMENT_DOMAIN else "not-registered",
            "category": entry["category"],
            "gate": entry["gate"],
            "avg_duration_ms": round(mean, 1) if mean is not None else None,
            "duration_ms_stddev": round(stdev, 1) if stdev is not None else None,
            "reproducibility": {"last_command": entry["last_command"], "last_version": entry["last_version"], "last_run": entry["last_run"]},
            "coverage_of_codebase": coverage_of_codebase,
            "findings_total": len(findings_here),
            "review": _rate(confirmed, dismissed, min_sample=min_sample),
        }
    return result


def _by_category_section(runs: list[dict[str, Any]]) -> dict[str, Any]:
    totals: dict[str, dict[str, Any]] = {}
    for run in runs:
        for finding in run["report"].get("findings", []):
            category = finding.get("category", "uncategorized")
            entry = totals.setdefault(category, {"findings_total": 0, "tools": set()})
            entry["findings_total"] += 1
            evidence = finding.get("evidence") or [{}]
            if evidence and isinstance(evidence[0], dict) and evidence[0].get("source"):
                entry["tools"].add(evidence[0]["source"])
    return {
        category: {"findings_total": entry["findings_total"], "tools": sorted(entry["tools"])}
        for category, entry in totals.items()
    }


def _review_section(runs: list[dict[str, Any]], *, min_sample: int) -> dict[str, Any]:
    runs_with_ledger = sum(1 for run in runs if run.get("ledger"))
    runs_without_ledger = len(runs) - runs_with_ledger

    tool_confirmed = tool_dismissed = 0
    llm_confirmed = llm_dismissed = 0
    by_tool_counts: dict[str, dict[str, int]] = {}
    decisions_considered = 0
    unreviewed = 0

    reviewed_fingerprints: set[str] = set()
    for run in runs:
        ledger = run.get("ledger")
        if not ledger:
            continue
        for decision in ledger.get("decisions", []):
            decisions_considered += 1
            action = decision.get("action")
            for item in decision.get("matched", []):
                source_types = set(item.get("evidence_source_types") or [])
                fingerprint = item.get("fingerprint")
                if fingerprint:
                    reviewed_fingerprints.add(fingerprint)
                # "Solo-LLM" = evidencia exclusivamente `llm` en el momento de
                # la decisión (sin respaldo `tool`/`specification`/`property`).
                # Un hallazgo con evidencia mixta tool+llm cuenta como
                # tool-sourced, nunca como alucinación del agente.
                is_llm_only = source_types == {"llm"}
                is_tool_sourced = "tool" in source_types
                if action not in ("confirm", "dismiss"):
                    continue
                if is_tool_sourced:
                    if action == "confirm":
                        tool_confirmed += 1
                    else:
                        tool_dismissed += 1
                    source = item.get("primary_source") or "unknown"
                    counts = by_tool_counts.setdefault(source, {"confirmed": 0, "dismissed": 0})
                    counts["confirmed" if action == "confirm" else "dismissed"] += 1
                elif is_llm_only:
                    if action == "confirm":
                        llm_confirmed += 1
                    else:
                        llm_dismissed += 1

    for run in runs:
        for finding in run["report"].get("findings", []):
            if finding.get("fingerprint") not in reviewed_fingerprints:
                unreviewed += 1

    by_tool_rates = {
        tool: _rate(counts["confirmed"], counts["dismissed"], min_sample=min_sample)
        for tool, counts in sorted(by_tool_counts.items())
    }

    return {
        "runs_with_ledger": runs_with_ledger,
        "runs_without_ledger": runs_without_ledger,
        "decisions_considered": decisions_considered,
        "tool_findings": {**_rate(tool_confirmed, tool_dismissed, min_sample=min_sample), "by_tool": by_tool_rates},
        "agent_llm_only_findings": _rate(llm_confirmed, llm_dismissed, min_sample=min_sample),
        "unreviewed_findings": {"count": unreviewed},
        "note": (
            "No single reliability score is produced; each ratio above is reported with its raw "
            "confirmed/dismissed counts and a 95% Wilson confidence interval. Ratios below the "
            "minimum sample size are null with sample_size_warning=true rather than a misleading "
            "100%/0%."
        ),
    }


def _trends_section(runs: list[dict[str, Any]]) -> dict[str, Any]:
    if not runs:
        return {"finding_counts": {}, "dimensions": {}}
    first_timestamp = runs[0]["report"].get("audit", {}).get("generated_at")
    try:
        epoch = datetime.fromisoformat((first_timestamp or "").replace("Z", "+00:00"))
        if epoch.tzinfo is None:
            epoch = epoch.replace(tzinfo=timezone.utc)
    except ValueError:
        epoch = datetime.now(timezone.utc)

    # Dos espacios de nombres separados, no una única tabla con prefijo: la
    # tabla de polaridad (`METRIC_POLARITY`) usa claves como "coverage.line_percent"
    # y "finding_counts.blocker" — cada serie debe buscarse con esa clave
    # exacta, sin un "dimensions." de más delante que la haga fallar siempre.
    finding_count_points: dict[str, list[tuple[str, float, float]]] = {}
    dimension_points: dict[str, list[tuple[str, float, float]]] = {}
    for run in runs:
        report = run["report"]
        generated_at = report.get("audit", {}).get("generated_at")
        day = _days_since(epoch, generated_at)
        if day is None:
            continue
        counts = report.get("summary", {}).get("finding_counts", {})
        for severity, value in counts.items():
            finding_count_points.setdefault(f"finding_counts.{severity}", []).append((generated_at, day, float(value)))
        dimensions = report.get("summary", {}).get("dimensions", {})
        for path, value in _flatten_numeric(dimensions):
            dimension_points.setdefault(path, []).append((generated_at, day, value))

    def _build_series(metric_path: str, points: list[tuple[str, float, float]]) -> dict[str, Any]:
        values = [value for _, _, value in points]
        mean, stdev = _mean_stdev(values)
        slope, se = _ols_trend([(day, value) for _, day, value in points])
        return {
            "series": [{"generated_at": ts, "value": value} for ts, _, value in points],
            "n": len(points),
            "mean": round(mean, 4) if mean is not None else None,
            "stdev": round(stdev, 4) if stdev is not None else None,
            "min": min(values) if values else None,
            "max": max(values) if values else None,
            "slope_per_day": round(slope, 6) if slope is not None else None,
            "slope_standard_error": round(se, 6) if se is not None else None,
            "direction": _trend_direction(slope, se, len(points), metric_path),
        }

    finding_counts = {
        path.split(".", 1)[1]: _build_series(path, points)
        for path, points in finding_count_points.items()
    }
    dimensions = {
        path: _build_series(path, points)
        for path, points in dimension_points.items()
    }
    return {"finding_counts": finding_counts, "dimensions": dimensions}


def _anomalies_section(root: Path, runs: list[dict[str, Any]]) -> dict[str, Any]:
    location_conflicts: list[dict[str, Any]] = []
    findings_on_removed_code: list[dict[str, Any]] = []
    decision_history: dict[str, list[dict[str, Any]]] = {}

    if runs:
        latest = runs[-1]["report"]
        by_location: dict[tuple[str, Any], list[dict[str, Any]]] = {}
        for finding in latest.get("findings", []):
            location = (finding.get("locations") or [{}])[0]
            key = (location.get("file"), location.get("line"))
            evidence = finding.get("evidence") or [{}]
            by_location.setdefault(key, []).append({
                "tool": evidence[0].get("source") if evidence and isinstance(evidence[0], dict) else None,
                "rule_id": finding.get("rule_id"), "severity": finding.get("severity"),
            })
            file_path = location.get("file")
            if file_path and not (root / file_path).exists():
                findings_on_removed_code.append({
                    "fingerprint": finding.get("fingerprint"), "file": file_path,
                    "note": "file no longer exists in the working tree",
                })
        for (file_path, line), entries in by_location.items():
            severities = {e["severity"] for e in entries}
            if file_path and len(entries) > 1 and len(severities) > 1:
                location_conflicts.append({"file": file_path, "line": line, "entries": entries})

    for run in runs:
        ledger = run.get("ledger")
        if not ledger:
            continue
        for decision in ledger.get("decisions", []):
            for item in decision.get("matched", []):
                fingerprint = item.get("fingerprint")
                if not fingerprint:
                    continue
                decision_history.setdefault(fingerprint, []).append({
                    "reviewed_at": decision.get("reviewed_at"), "action": decision.get("action"),
                })

    decision_reversals = [
        {"fingerprint": fp, "history": history}
        for fp, history in decision_history.items()
        if len({entry["action"] for entry in history}) > 1
    ]

    stale_baselines: list[dict[str, Any]] = []
    if runs:
        latest_dimensions = runs[-1]["report"].get("summary", {}).get("dimensions", {})
        stale = latest_dimensions.get("performance", {}).get("stale_metrics")
        if stale:
            stale_baselines = [{"metric_path": path, "reason": "present in baseline, absent from current measurement"} for path in stale]

    return {
        "location_conflicts": location_conflicts,
        "stale_baselines": stale_baselines,
        "decision_reversals": decision_reversals,
        "findings_on_removed_code": findings_on_removed_code,
    }


# ---------------------------------------------------------------------------
# Ensamblado
# ---------------------------------------------------------------------------


def build(
    root: Path, run_refs: list[RunRef], plan: dict[str, Any] | None, *,
    min_sample: int = DEFAULT_MIN_SAMPLE, include_history_timeline: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not run_refs:
        raise ValueError(f"no report.json found under {root / DEFAULT_HISTORY_GLOB}; run build_report.py at least once first")

    runs = [load_run(ref) for ref in run_refs]
    limitations: list[str] = []

    timeline_by_run = [
        _findings_timeline_for_run(run, _run_dir_label(run["dir"], root))
        for run in runs
    ]

    latest = runs[-1]
    findings_timeline: list[dict[str, Any]] = []
    if include_history_timeline:
        for entries in timeline_by_run:
            findings_timeline.extend(entries)
    else:
        findings_timeline = timeline_by_run[-1]

    runs_without_ledger = [i for i, run in enumerate(runs) if run.get("ledger") is None]
    if runs_without_ledger:
        limitations.append(
            f"{len(runs_without_ledger)} of {len(runs)} runs have no review-ledger.json; "
            "their findings are excluded from review ratios."
        )

    used_output_formats = {
        tool.get("output_format")
        for run in runs for tool in run["report"].get("tools", [])
        if tool.get("output_format")
    }
    unregistered = sorted(used_output_formats - set(TOOL_MEASUREMENT_DOMAIN))
    for output_format in unregistered:
        limitations.append(f"No measurement-domain description registered for output_format {output_format!r}.")

    if plan is None:
        limitations.append("No plan.json supplied; per-tool codebase coverage is not computable.")

    document = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repository": root.name,
        "root": str(root),
        "source_runs_considered": len(runs),
        "source_runs": [
            {
                "dir": _run_dir_label(run["dir"], root),
                "generated_at": run["report"].get("audit", {}).get("generated_at"),
                "profile": run["report"].get("audit", {}).get("profile"),
                "outcome": run["report"].get("audit", {}).get("outcome"),
                "has_ledger": run.get("ledger") is not None,
            }
            for run in runs
        ],
        "current_run": _current_run_section(latest["report"], latest["dir"], root),
        "findings_timeline": findings_timeline,
        "by_tool": _by_tool_section(runs, root, timeline_by_run, plan=plan, min_sample=min_sample),
        "by_category": _by_category_section(runs),
        "review": _review_section(runs, min_sample=min_sample),
        "trends": _trends_section(runs),
        "anomalies": _anomalies_section(root, runs),
        "limitations": sorted(set(limitations)),
    }
    return document


def _new_output_dir(root: Path, explicit: Path | None) -> Path:
    if explicit:
        candidate = explicit.expanduser().resolve()
        if candidate.exists():
            raise FileExistsError(f"output directory already exists: {candidate}")
        candidate.mkdir(parents=True)
        return candidate
    stem = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = root / STATS_DIR_NAME
    candidate = base / stem
    counter = 1
    while candidate.exists():
        candidate = base / f"{stem}-{counter}"
        counter += 1
    candidate.mkdir(parents=True)
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--history-glob", default=DEFAULT_HISTORY_GLOB)
    parser.add_argument("--since", default=None, help="Only consider runs whose directory stamp is >= this value")
    parser.add_argument("--max-runs", type=int, default=DEFAULT_MAX_RUNS)
    parser.add_argument("--plan", type=Path, default=None, help="plan.json from plan_audit.py, for per-tool coverage")
    parser.add_argument("--min-sample", type=int, default=DEFAULT_MIN_SAMPLE)
    parser.add_argument("--include-history-timeline", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--emit-svg", action="store_true")
    args = parser.parse_args()
    try:
        root = args.root.expanduser().resolve(strict=True)
        run_refs = discover_runs(root, args.history_glob, since=args.since, max_runs=args.max_runs)
        plan = json.loads(args.plan.read_text(encoding="utf-8")) if args.plan else None
        stats = build(root, run_refs, plan, min_sample=args.min_sample, include_history_timeline=args.include_history_timeline)
        destination = _new_output_dir(root, args.output_dir)
        (destination / "stats.json").write_text(
            json.dumps(stats, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8",
        )
        render(stats, destination, emit_svg=args.emit_svg)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
