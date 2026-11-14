#!/usr/bin/env python3
"""Resumen compacto y sin ambigüedad de un informe de auditoría, para que vigilante (u otro consumidor) lo lea.

`report.json` es el registro completo (megabytes en un monorrepo). El consumidor solo necesita: ¿cuándo, qué
resultado, cuántos hallazgos de cada gravedad, qué evidencia falta y si una persona los revisó? Este script lo
extrae a `verdict.json` junto al informe, sin tocar `report.json`. Solo lectura sobre el informe; no mira el repo.

Contrato (`schema_version` 1.0.0):
  repository, generated_at, profile, scope, outcome (pass|fail|incomplete|informational),
  counts {blocker, high, medium, low}, graves (blocker+high),
  tools {passed, findings, failed, timed_out, skipped, unavailable}, incomplete_required (nombres),
  tools_not_run (nombres), coverage_gaps (limitaciones que dejan código sin analizar),
  semantic_review {done, confirmed, dismissed}, findings_total, report (ruta del informe completo).
`graves` incluye `blocker`: contar solo `high` dejaba pasar los bloqueantes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SEVERITIES = ("blocker", "high", "medium", "low")
GAP = re.compile(r"not operational|were not analyzed|not analy[sz]ed|sin analizar", re.I)
TOOL_STATES = ("passed", "findings", "failed", "timed_out", "skipped", "unavailable")


def build_verdict(report: dict, report_path: Path, ledger: dict | None = None) -> dict:
    audit = report.get("audit", {})
    counts = {s: 0 for s in SEVERITIES}
    for finding in report.get("findings", []):
        severity = str(finding.get("severity", "")).lower()
        if severity in counts:
            counts[severity] += 1
    tools = {s: 0 for s in TOOL_STATES}
    incomplete = []
    for tool in report.get("tools", []):
        status = tool.get("status")
        if status in tools:
            tools[status] += 1
        if status in {"failed", "timed_out", "unavailable"} and tool.get("gate"):
            incomplete.append(tool.get("name"))
    not_run = [t.get("name") for t in report.get("tools", []) if t.get("status") in {"skipped", "unavailable", "timed_out", "failed"}]
    gaps = [lim[:200] for lim in report.get("limitations", []) if GAP.search(str(lim))]
    decisions = (ledger or {}).get("decisions", [])
    review = {
        "done": ledger is not None,
        "confirmed": sum(1 for d in decisions if d.get("action") == "confirm"),
        "dismissed": sum(1 for d in decisions if d.get("action") == "dismiss"),
    }
    return {
        "schema_version": "1.0.0",
        "repository": audit.get("repository"),
        "generated_at": audit.get("generated_at"),
        "profile": audit.get("profile"),
        "scope": audit.get("scope"),
        "outcome": audit.get("outcome"),
        "counts": counts,
        "graves": counts["blocker"] + counts["high"],
        "findings_total": sum(counts.values()),
        "tools": tools,
        "incomplete_required": incomplete,
        "tools_not_run": not_run,
        "coverage_gaps": gaps,
        "semantic_review": review,
        "report": str(report_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Escribe verdict.json junto a un report.json.")
    parser.add_argument("report_dir", type=Path, help="Directorio con report.json (salida de build_report.py)")
    args = parser.parse_args()
    report_path = args.report_dir / "report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        ledger_path = args.report_dir / "review-ledger.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.is_file() else None
    except (OSError, json.JSONDecodeError) as exc:
        print(f"no se puede leer el informe: {exc}", file=sys.stderr)
        return 2
    verdict = build_verdict(report, report_path, ledger)
    target = args.report_dir / "verdict.json"
    target.write_text(json.dumps(verdict, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
