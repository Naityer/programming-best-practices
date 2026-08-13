#!/usr/bin/env python3
"""Normalize a canonical audit result and render Markdown, JSON, and SARIF 2.1.0."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_report import validate_report

SEVERITY_ORDER = {"blocker": 0, "high": 1, "medium": 2, "low": 3}
CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}
SARIF_LEVEL = {"blocker": "error", "high": "error", "medium": "warning", "low": "note"}
SOURCE_ORDER = {"tool": 0, "specification": 1, "property": 1, "llm": 2}
SECRET_KEY = re.compile(r"(secret|token|password|passwd|api[_-]?key|credential|private[_-]?key)", re.I)
SECRET_PATTERNS = [
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?i)(secret|token|password|api[_-]?key)\s*[:=]\s*['\"]?[^\s,'\"}]{6,}"),
]


def _redact_text(value: str) -> str:
    result = value
    for pattern in SECRET_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


def _redact(value: Any, key: str = "") -> Any:
    if SECRET_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        return {item_key: _redact(item_value, item_key) for item_key, item_value in value.items()}
    return value


def _fingerprint(finding: dict[str, Any]) -> str:
    location = finding.get("locations", [{}])[0]
    raw = "|".join(
        str(item)
        for item in (
            finding.get("rule_id", ""),
            finding.get("category", ""),
            location.get("file", ""),
            location.get("line", ""),
            finding.get("title", ""),
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _normalize(data: dict[str, Any]) -> dict[str, Any]:
    normalized = _redact(copy.deepcopy(data))
    by_fingerprint: dict[str, dict[str, Any]] = {}
    for finding in normalized["findings"]:
        fingerprint = finding.get("fingerprint") or _fingerprint(finding)
        finding["fingerprint"] = fingerprint
        current = by_fingerprint.get(fingerprint)
        if current is None:
            finding["evidence"] = sorted(
                finding["evidence"],
                key=lambda item: (SOURCE_ORDER.get(item["source_type"], 9), item["source"], item["message"]),
            )
            by_fingerprint[fingerprint] = finding
            continue
        combined = current["evidence"] + finding["evidence"]
        unique: dict[str, dict[str, Any]] = {}
        for evidence in combined:
            key = json.dumps(evidence, sort_keys=True, ensure_ascii=False)
            unique[key] = evidence
        current["evidence"] = sorted(
            unique.values(),
            key=lambda item: (SOURCE_ORDER.get(item["source_type"], 9), item["source"], item["message"]),
        )
        if SEVERITY_ORDER[finding["severity"]] < SEVERITY_ORDER[current["severity"]]:
            current["severity"] = finding["severity"]
        if CONFIDENCE_ORDER[finding["confidence"]] < CONFIDENCE_ORDER[current["confidence"]]:
            current["confidence"] = finding["confidence"]

    findings = sorted(
        by_fingerprint.values(),
        key=lambda item: (
            SEVERITY_ORDER[item["severity"]],
            CONFIDENCE_ORDER[item["confidence"]],
            item["locations"][0]["file"],
            item["locations"][0].get("line", 0),
            item["rule_id"],
        ),
    )
    normalized["findings"] = findings
    normalized["summary"]["finding_counts"] = {
        severity: sum(1 for finding in findings if finding["severity"] == severity)
        for severity in ("blocker", "high", "medium", "low")
    }
    normalized["tools"] = sorted(normalized["tools"], key=lambda item: item["name"].lower())
    normalized["limitations"] = sorted(set(normalized["limitations"]))
    return normalized


def _markdown(data: dict[str, Any]) -> str:
    audit = data["audit"]
    counts = data["summary"]["finding_counts"]
    lines = [
        "# Code quality audit",
        "",
        f"- Repository: `{audit['repository']}`",
        f"- Profile: **{audit['profile'].upper()}**",
        f"- Scope: `{audit['scope']}`",
        f"- Mode: `{audit['mode']}`",
        f"- Outcome: **{audit['outcome'].upper()}**",
        f"- Generated: {audit['generated_at']}",
        "",
        "## Summary",
        "",
        "| Blocker | High | Medium | Low |",
        "| ---: | ---: | ---: | ---: |",
        f"| {counts['blocker']} | {counts['high']} | {counts['medium']} | {counts['low']} |",
    ]
    dimensions = data["summary"].get("dimensions")
    if dimensions:
        lines.extend(["", "### Dimensions", ""])
        for name, value in sorted(dimensions.items()):
            lines.append(f"- {name}: {json.dumps(value, sort_keys=True, ensure_ascii=False)}")

    lines.extend(["", "## Findings", ""])
    if not data["findings"]:
        lines.append("No actionable findings were recorded. This does not prove the repository is defect-free.")
    for finding in data["findings"]:
        location = finding["locations"][0]
        suffix = f":{location['line']}" if location.get("line") else ""
        lines.extend([
            f"### [{finding['severity'].upper()}] {finding['title']}",
            "",
            f"- Rule: `{finding['rule_id']}`",
            f"- Category: `{finding['category']}`",
            f"- Confidence: `{finding['confidence']}`",
            f"- Location: `{location['file']}{suffix}`",
            f"- Fingerprint: `{finding['fingerprint']}`",
            "",
            f"Impact: {finding['impact']}",
            "",
            f"Recommendation: {finding['recommendation']}",
            "",
            "Evidence:",
            "",
        ])
        for evidence in finding["evidence"]:
            metric = ""
            if evidence.get("metric"):
                metric = f" ({evidence['metric']}={evidence.get('value')})"
            lines.append(f"- **{evidence['source_type']} / {evidence['source']}**{metric}: {evidence['message']}")
        if finding.get("oracle"):
            oracle = finding["oracle"]
            detail = oracle.get("source") or oracle.get("rule") or ""
            lines.extend(["", f"Oracle: `{oracle['type']}`{f' — {detail}' if detail else ''}"])
        lines.append("")

    lines.extend(["## Tool execution", "", "| Tool | Status | Gate | Effective scope | Version | Command/reason |", "| --- | --- | --- | --- | --- | --- |"])
    for tool in data["tools"]:
        detail = tool.get("command") or tool.get("reason") or ""
        lines.append(f"| {tool['name']} | {tool['status']} | {str(tool.get('gate', False)).lower()} | {tool.get('effective_scope', 'repository')} | {tool.get('version', '')} | `{detail}` |")

    lines.extend(["", "## Limitations", ""])
    if data["limitations"]:
        lines.extend(f"- {item}" for item in data["limitations"])
    else:
        lines.append("- None recorded.")
    lines.append("")
    return "\n".join(lines)


def _sarif(data: dict[str, Any]) -> dict[str, Any]:
    rules: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    for finding in data["findings"]:
        rule_id = finding["rule_id"]
        rules.setdefault(
            rule_id,
            {
                "id": rule_id,
                "name": re.sub(r"[^A-Za-z0-9]+", "_", rule_id).strip("_") or "quality_rule",
                "shortDescription": {"text": finding["title"]},
                "properties": {"category": finding["category"]},
            },
        )
        locations = []
        for location in finding["locations"]:
            region: dict[str, int] = {}
            if location.get("line"):
                region["startLine"] = location["line"]
            if location.get("column"):
                region["startColumn"] = location["column"]
            physical: dict[str, Any] = {
                "artifactLocation": {"uri": location["file"].replace("\\", "/")}
            }
            if region:
                physical["region"] = region
            locations.append({"physicalLocation": physical})
        results.append(
            {
                "ruleId": rule_id,
                "level": SARIF_LEVEL[finding["severity"]],
                "message": {
                    "text": f"{finding['title'].rstrip('.')}. Impact: {finding['impact']} Recommendation: {finding['recommendation']}"
                },
                "locations": locations,
                "partialFingerprints": {"primaryLocationLineHash": finding["fingerprint"]},
                "properties": {
                    "severity": finding["severity"],
                    "confidence": finding["confidence"],
                    "category": finding["category"],
                    "evidenceSources": [f"{item['source_type']}:{item['source']}" for item in finding["evidence"]],
                    "impact": finding["impact"],
                    "recommendation": finding["recommendation"],
                },
            }
        )
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "programming-best-practices",
                        "rules": sorted(rules.values(), key=lambda item: item["id"]),
                    }
                },
                "invocations": [
                    {
                        "executionSuccessful": all(
                            item["status"] not in {"failed", "timed_out"} for item in data["tools"]
                        ),
                        "properties": {
                            "profile": data["audit"]["profile"],
                            "scope": data["audit"]["scope"],
                            "outcome": data["audit"]["outcome"],
                        },
                    }
                ],
                "results": results,
            }
        ],
    }


def _new_output_dir(root: Path, generated_at: str, explicit: Path | None) -> Path:
    if explicit:
        candidate = explicit.expanduser().resolve()
        if candidate.exists():
            raise FileExistsError(f"output directory already exists: {candidate}")
        candidate.mkdir(parents=True)
        return candidate
    try:
        timestamp = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError:
        timestamp = datetime.now(timezone.utc)
    stem = timestamp.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = root / ".quality-audit"
    base.mkdir(parents=True, exist_ok=True)
    candidate = base / stem
    counter = 1
    while candidate.exists():
        candidate = base / f"{stem}-{counter}"
        counter += 1
    candidate.mkdir()
    return candidate


def render(input_path: Path, root: Path, output_dir: Path | None = None) -> Path:
    data = json.loads(input_path.read_text(encoding="utf-8"))
    for finding in data.get("findings", []):
        finding.setdefault("fingerprint", _fingerprint(finding))
        finding.setdefault("id", f"PBP-{finding['fingerprint'][:12].upper()}")
    initial_errors = validate_report(data)
    if initial_errors:
        raise ValueError("\n".join(initial_errors))
    normalized = _normalize(data)
    errors = validate_report(normalized)
    if errors:
        raise ValueError("\n".join(errors))
    destination = _new_output_dir(root.expanduser().resolve(strict=True), normalized["audit"]["generated_at"], output_dir)
    (destination / "report.json").write_text(
        json.dumps(normalized, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (destination / "report.md").write_text(_markdown(normalized), encoding="utf-8")
    (destination / "report.sarif").write_text(
        json.dumps(_sarif(normalized), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    try:
        output = render(args.report, args.root, args.output_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


