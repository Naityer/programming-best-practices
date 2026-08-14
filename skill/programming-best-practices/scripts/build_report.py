#!/usr/bin/env python3
"""Build and render a canonical audit report from execution evidence and reviewed fragments."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from normalize_tool_output import normalize
from render_report import render

SUPPORTED_FORMATS = {
    "semgrep", "gitleaks", "trivy", "osv-scanner", "coverage-py", "ruff-json",
    "jacoco", "cobertura", "lcov", "pit", "stryker", "go-cover", "llvm-cov",
    "mutmut", "cargo-mutants",
    # Rendimiento. Registrar el adaptador en normalize_tool_output NO basta:
    # sin estar aquí, y sin su fichero en `candidates` de `_auto_fragment`, el
    # check se ejecuta y pasa pero su medición no llega nunca al informe. La
    # auditoría diría "correcto" sin haber mirado nada, que es el peor
    # resultado posible.
    "bundle-size", "pytest-benchmark", "web-runtime",
}


def _merge_dimensions(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge_dimensions(target[key], value)
        else:
            target[key] = value


def _auto_fragment(check: dict[str, Any], root: Path) -> dict[str, Any] | None:
    kind = check.get("output_format")
    if kind not in SUPPORTED_FORMATS or check.get("status") not in {"passed", "findings"}:
        return None
    artifact = Path(check.get("artifact_dir") or ".")
    candidates = {
        "gitleaks": artifact / "gitleaks.json",
        "coverage-py": artifact / "coverage.json",
        "jacoco": artifact / "jacoco.xml",
        "cobertura": artifact / "coverage.xml",
        "lcov": artifact / "lcov.info",
        "pit": artifact / "mutations.xml",
        "stryker": artifact / "mutation-report.json",
        "go-cover": artifact / "go-cover.out",
        "llvm-cov": artifact / "llvm-cov.json",
        "cargo-mutants": artifact / "outcomes.json",
        "bundle-size": artifact / "bundle-size.json",
        "pytest-benchmark": artifact / "benchmark.json",
        "web-runtime": artifact / "web-runtime.json",
    }
    input_path = candidates.get(kind, Path(check.get("stdout") or ""))
    if kind == "cobertura" and not input_path.is_file():
        input_path = next(artifact.rglob("coverage.cobertura.xml"), input_path)
    if not input_path.is_file() and Path(check.get("stdout") or "").is_file():
        input_path = Path(check["stdout"])
    if not input_path.is_file() or input_path.stat().st_size == 0:
        return {
            "schema_version": "1.0.0", "tool": kind, "findings": [], "dimensions": {},
            "limitations": [f"{check['id']} completed without a parseable {kind} report."],
        }
    try:
        return normalize(kind, input_path, root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "schema_version": "1.0.0", "tool": kind, "findings": [], "dimensions": {},
            "limitations": [f"{check['id']} output could not be normalized: {exc}"],
        }


def _matches(finding: dict[str, Any], decision: dict[str, Any]) -> bool:
    if decision.get("fingerprint"):
        return finding.get("fingerprint") == decision["fingerprint"]
    location = finding.get("locations", [{}])[0]
    return (
        finding.get("rule_id") == decision.get("rule_id")
        and location.get("file") == decision.get("file")
        and (decision.get("line") is None or location.get("line") == decision.get("line"))
    )


def _apply_review(
    findings: list[dict[str, Any]],
    decisions: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not decisions:
        return findings, []
    remaining = list(findings)
    notes: list[str] = []
    allowed_overrides = {"title", "severity", "confidence", "impact", "recommendation"}
    for decision in decisions:
        matches = [item for item in remaining if _matches(item, decision)]
        if not matches:
            notes.append(f"Semantic review decision did not match a finding: {decision.get('fingerprint') or decision.get('rule_id') or 'unknown'}.")
            continue
        action = decision.get("action")
        reason = str(decision.get("reason") or "").strip()
        if not reason:
            raise ValueError("semantic-review decisions require a non-empty reason")
        if action == "dismiss":
            remaining = [item for item in remaining if item not in matches]
            for item in matches:
                notes.append(f"Dismissed {item['rule_id']} at {item['locations'][0]['file']}: {reason or 'semantic review found no actionable issue'}.")
        elif action == "confirm":
            overrides = decision.get("overrides", {})
            unknown = set(overrides) - allowed_overrides
            if unknown:
                raise ValueError(f"unsupported semantic-review overrides: {sorted(unknown)}")
            for item in matches:
                item.update(overrides)
                item["evidence"].append({
                    "source_type": "llm",
                    "source": "semantic-review",
                    "message": reason or "The finding was confirmed after contextual review.",
                })
        else:
            raise ValueError("semantic-review action must be 'confirm' or 'dismiss'")
    return remaining, notes


def build(
    execution: dict[str, Any],
    fragments: list[dict[str, Any]],
    semantic_findings: list[dict[str, Any]] | None = None,
    semantic_review: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    root = Path(execution["root"])
    findings: list[dict[str, Any]] = list(semantic_findings or [])
    dimensions: dict[str, Any] = {}
    limitations: list[str] = []
    fragments_by_check: dict[str, dict[str, Any]] = {}

    for fragment in fragments:
        findings.extend(fragment.get("findings", []))
        _merge_dimensions(dimensions, fragment.get("dimensions", {}))
        limitations.extend(fragment.get("limitations", []))

    for check in execution["checks"]:
        fragment = _auto_fragment(check, root)
        if fragment:
            fragments_by_check[check["id"]] = fragment
            findings.extend(fragment.get("findings", []))
            _merge_dimensions(dimensions, fragment.get("dimensions", {}))
            limitations.extend(fragment.get("limitations", []))

    findings, review_notes = _apply_review(findings, semantic_review)
    limitations.extend(review_notes)

    tools = []
    required_incomplete = False
    gate_failed = False
    gates = []
    for check in execution["checks"]:
        status = check["status"]
        fragment = fragments_by_check.get(check["id"])
        if status == "passed" and fragment and fragment.get("findings"):
            status = "findings"
        if status == "findings" and not fragment and check.get("output_format") not in SUPPORTED_FORMATS:
            limitations.append(f"{check['id']}: findings remain only in raw output because {check.get('output_format', 'text')} has no adapter.")
        if check["required"] and status in {"failed", "timed_out", "skipped", "unavailable"}:
            required_incomplete = True
        is_gate = bool(check.get("gate", False))
        if is_gate:
            gates.append(status)
            if status in {"findings", "failed", "timed_out"}:
                gate_failed = True
        item = {
            "name": f"{check['id']} ({check['name']})",
            "status": status,
            "exit_code": check.get("exit_code"),
            "duration_ms": check.get("duration_ms", 0),
            "version": check.get("version", "unknown"),
            "gate": is_gate,
            "effective_scope": check.get("effective_scope", "repository"),
        }
        if check.get("command"):
            item["command"] = check["command"]
        if check.get("reason"):
            item["reason"] = check["reason"]
        if check.get("stdout"):
            item["report"] = check["stdout"]
        tools.append(item)
        if status in {"failed", "timed_out", "skipped", "unavailable"}:
            limitations.append(f"{check['id']}: {check.get('reason') or status}")

    blocker = any(item.get("severity") == "blocker" for item in findings)
    if blocker or gate_failed:
        outcome = "fail"
    elif required_incomplete:
        outcome = "incomplete"
    elif gates and all(status == "passed" for status in gates):
        outcome = "pass"
    else:
        outcome = "informational"
    counts = {
        severity: sum(1 for item in findings if item.get("severity") == severity)
        for severity in ("blocker", "high", "medium", "low")
    }
    dimensions["gates"] = {
        "configured": len(gates),
        "passed": sum(status == "passed" for status in gates),
        "failed": sum(status in {"findings", "failed", "timed_out"} for status in gates),
        "incomplete": sum(status in {"skipped", "unavailable"} for status in gates),
    }
    return {
        "schema_version": "1.0.0",
        "audit": {
            "repository": root.name,
            "profile": execution["profile"],
            "scope": execution["scope"],
            "mode": "audit",
            "generated_at": execution["generated_at"],
            "outcome": outcome,
        },
        "summary": {"finding_counts": counts, "dimensions": dimensions},
        "tools": tools,
        "findings": findings,
        "limitations": sorted(set(limitations)),
    }


def _load_fragments(paths: list[Path]) -> list[dict[str, Any]]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in paths]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("execution", type=Path)
    parser.add_argument("--fragment", type=Path, action="append", default=[])
    parser.add_argument("--semantic-findings", type=Path)
    parser.add_argument("--semantic-review", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        execution = json.loads(args.execution.read_text(encoding="utf-8"))
        semantic = None
        if args.semantic_findings:
            loaded = json.loads(args.semantic_findings.read_text(encoding="utf-8"))
            semantic = loaded.get("findings", loaded) if isinstance(loaded, dict) else loaded
        review = None
        if args.semantic_review:
            loaded = json.loads(args.semantic_review.read_text(encoding="utf-8"))
            review = loaded.get("decisions", loaded) if isinstance(loaded, dict) else loaded
            if not isinstance(review, list):
                raise ValueError("semantic review must contain a decisions array")
        report = build(execution, _load_fragments(args.fragment), semantic, review)
        staging = args.output_dir.parent / f".{args.output_dir.name}.canonical.json"
        if staging.exists():
            raise FileExistsError(f"staging file exists: {staging}")
        staging.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        try:
            destination = render(staging, Path(execution["root"]), args.output_dir)
        finally:
            if staging.exists():
                staging.unlink()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
