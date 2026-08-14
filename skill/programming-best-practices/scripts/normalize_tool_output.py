#!/usr/bin/env python3
"""Normalize supported analyzer reports into evidence fragments for build_report.py."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable

SECRET_RE = re.compile(r"(?i)(secret|token|password|api[_-]?key)\s*[:=]\s*\S+")


def _redact(text: Any) -> str:
    return SECRET_RE.sub("[REDACTED]", str(text or ""))


def _severity(value: Any, *, security: bool = False) -> str:
    name = str(value or "").upper()
    if name in {"BLOCKER"}:
        return "blocker"
    if name in {"CRITICAL", "ERROR", "HIGH"}:
        return "high"
    if name in {"WARNING", "WARN", "MEDIUM", "MODERATE"}:
        return "medium"
    if name in {"INFO", "LOW", "NOTE"}:
        return "low"
    return "medium" if security else "low"


def _relative(path: Any, root: Path | None) -> str:
    value = Path(str(path or "unknown"))
    if root:
        try:
            value = value.resolve().relative_to(root.resolve())
        except (OSError, ValueError):
            pass
    return value.as_posix()


def _finding(
    tool: str,
    rule: str,
    title: str,
    category: str,
    severity: str,
    file: str,
    line: int | None,
    message: str,
    impact: str,
    recommendation: str,
    *,
    confidence: str = "high",
    metric: str | None = None,
    value: Any = None,
) -> dict[str, Any]:
    raw = f"{tool}|{rule}|{file}|{line or 0}|{title}"
    fingerprint = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    evidence: dict[str, Any] = {"source_type": "tool", "source": tool, "message": _redact(message)}
    if metric:
        evidence.update(metric=metric, value=value)
    location: dict[str, Any] = {"file": file or "unknown"}
    if line and int(line) > 0:
        location["line"] = int(line)
    return {
        "id": f"PBP-{fingerprint[:12].upper()}",
        "fingerprint": fingerprint,
        "rule_id": str(rule or f"{tool}.finding"),
        "title": _redact(title),
        "category": category,
        "severity": severity,
        "confidence": confidence,
        "locations": [location],
        "evidence": [evidence],
        "impact": impact,
        "recommendation": recommendation,
    }


def parse_semgrep(data: Any, root: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    findings = []
    for item in data.get("results", []):
        extra = item.get("extra", {})
        metadata = extra.get("metadata", {})
        severity = _severity(extra.get("severity"))
        rule_id = str(item.get("check_id", "semgrep.finding"))
        stable_rule = re.search(r"(pbp[.].+)$", rule_id)
        if stable_rule:
            rule_id = stable_rule.group(1)
        confidence = str(metadata.get("confidence", "HIGH")).lower()
        if confidence not in {"high", "medium", "low"}:
            confidence = "medium"
        findings.append(_finding(
            "semgrep", rule_id, extra.get("message", "Semgrep finding"),
            "security" if metadata.get("category") == "security" else "maintainability",
            severity, _relative(item.get("path"), root), item.get("start", {}).get("line"),
            extra.get("message", ""), metadata.get("impact") or "The matched construct requires contextual review before treating it as exploitable.",
            metadata.get("fix") or metadata.get("recommendation") or "Review the data flow and apply the rule-specific remediation.",
            confidence=confidence,
        ))
    errors = data.get("errors", [])
    limitations = [f"Semgrep parser reported: {_redact(item.get('message', item))}" for item in errors]
    return findings, {}, limitations


def parse_gitleaks(data: Any, root: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    items = data if isinstance(data, list) else data.get("findings", [])
    findings = []
    for item in items:
        findings.append(_finding(
            "gitleaks", item.get("RuleID", "gitleaks.secret"), item.get("Description", "Credential-like value detected"),
            "security", "blocker", _relative(item.get("File"), root), item.get("StartLine"),
            "A credential-like value was detected; the value is redacted.",
            "If valid, repository access may enable credential compromise.",
            "Revoke or rotate the credential, remove it from source and authorized history, and use a secret store.",
        ))
    return findings, {}, []


def parse_trivy(data: Any, root: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    findings = []
    for result in data.get("Results", []):
        target = _relative(result.get("Target"), root)
        for item in result.get("Secrets") or []:
            findings.append(_finding(
                "trivy", item.get("RuleID", "trivy.secret"), item.get("Title", "Secret detected"),
                "security", "blocker", target, item.get("StartLine"), "Trivy detected a redacted secret.",
                "A valid secret in source or an artifact can be reused by an attacker.",
                "Rotate it, remove it from source/history as authorized, and use a secret store.",
            ))
        for item in result.get("Vulnerabilities") or []:
            vuln = item.get("VulnerabilityID", "trivy.vulnerability")
            pkg = item.get("PkgName", "dependency")
            findings.append(_finding(
                "trivy", vuln, f"{vuln} affects {pkg}", "dependency-security",
                _severity(item.get("Severity"), security=True), target, None,
                item.get("Title") or item.get("Description") or vuln,
                "A deployed dependency may contain a known vulnerability.",
                f"Review reachability and upgrade to {item.get('FixedVersion') or 'a fixed compatible version'}.",
            ))
        for item in result.get("Misconfigurations") or []:
            findings.append(_finding(
                "trivy", item.get("ID", "trivy.misconfiguration"), item.get("Title", "Configuration weakness"),
                "security", _severity(item.get("Severity"), security=True), target,
                item.get("CauseMetadata", {}).get("StartLine"), item.get("Message") or item.get("Description"),
                "The deployment or infrastructure configuration may weaken a security boundary.",
                item.get("Resolution") or "Apply the documented secure configuration.",
            ))
    return findings, {}, []


def parse_osv(data: Any, root: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    findings = []
    for result in data.get("results", []):
        source = result.get("source", {})
        source_path = _relative(source.get("path") or source.get("target"), root)
        for package in result.get("packages", []):
            package_info = package.get("package", {})
            name = package_info.get("name") or package_info.get("purl") or "dependency"
            for vuln in package.get("vulnerabilities", []):
                vuln_id = vuln.get("id", "osv.vulnerability")
                db_severity = vuln.get("database_specific", {}).get("severity")
                findings.append(_finding(
                    "osv-scanner", vuln_id, f"{vuln_id} affects {name}", "dependency-security",
                    _severity(db_severity, security=True), source_path, None,
                    vuln.get("summary") or vuln.get("details") or vuln_id,
                    "The resolved dependency matches a known vulnerability record.",
                    "Review reachability and upgrade to an unaffected compatible version.",
                ))
    return findings, {}, []


def parse_ruff(data: Any, root: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    findings = []
    for item in data if isinstance(data, list) else data.get("diagnostics", []):
        code = str(item.get("code") or "ruff.finding")
        location = item.get("location", {})
        if code in {"E999", "F821", "F822", "F823"}:
            category, severity = "correctness", "high"
        elif code.startswith("S"):
            category, severity = "security", "high"
        elif code.startswith(("B", "PLE", "PLW")):
            category, severity = "correctness", "medium"
        else:
            category, severity = "maintainability", "low"
        message = item.get("message") or code
        fix = item.get("fix")
        recommendation = fix.get("message") if isinstance(fix, dict) and fix.get("message") else "Apply the smallest rule-specific correction and rerun Ruff."
        findings.append(_finding(
            "ruff", code, f"{code}: {message}", category, severity,
            _relative(item.get("filename"), root), location.get("row"), message,
            "The diagnostic identifies a concrete correctness, security, or maintainability defect.",
            recommendation,
        ))
    return findings, {}, []

def parse_coverage_py(data: Any, root: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    totals = data.get("totals", {})
    dimensions = {
        "coverage": {
            "line_percent": totals.get("percent_covered"),
            "covered_lines": totals.get("covered_lines"),
            "num_statements": totals.get("num_statements"),
            "covered_branches": totals.get("covered_branches"),
            "num_branches": totals.get("num_branches"),
        }
    }
    return [], dimensions, []


def parse_cobertura(root_xml: ET.Element, root: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    line_rate = float(root_xml.attrib.get("line-rate", 0)) * 100
    branch_rate = float(root_xml.attrib.get("branch-rate", 0)) * 100
    return [], {"coverage": {"line_percent": line_rate, "branch_percent": branch_rate}}, []


def parse_jacoco(root_xml: ET.Element, root: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    dimensions: dict[str, Any] = {"coverage": {}}
    for counter in root_xml.findall("counter"):
        kind = counter.attrib.get("type", "").lower()
        covered = int(counter.attrib.get("covered", 0))
        missed = int(counter.attrib.get("missed", 0))
        total = covered + missed
        dimensions["coverage"][f"{kind}_percent"] = round(covered * 100 / total, 2) if total else None
        dimensions["coverage"][f"{kind}_covered"] = covered
        dimensions["coverage"][f"{kind}_total"] = total
    return [], dimensions, []


def parse_lcov(text: str, root: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    values: dict[str, int] = {}
    for line in text.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            if key in {"LF", "LH", "BRF", "BRH"}:
                values[key] = values.get(key, 0) + int(value or 0)
    line_percent = round(values.get("LH", 0) * 100 / values["LF"], 2) if values.get("LF") else None
    branch_percent = round(values.get("BRH", 0) * 100 / values["BRF"], 2) if values.get("BRF") else None
    return [], {"coverage": {"line_percent": line_percent, "branch_percent": branch_percent}}, []


def parse_go_cover(text: str, root: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    statements = covered = 0
    for line in text.splitlines():
        if not line or line.startswith("mode:"):
            continue
        parts = line.rsplit(" ", 2)
        if len(parts) != 3:
            continue
        try:
            count, hits = int(parts[1]), int(parts[2])
        except ValueError:
            continue
        statements += count
        if hits > 0:
            covered += count
    percent = round(covered * 100 / statements, 2) if statements else None
    return [], {"coverage": {"line_percent": percent, "covered_statements": covered, "statements": statements}}, []


def parse_llvm_cov(data: Any, root: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    totals = ((data.get("data") or [{}])[0]).get("totals", {})
    coverage: dict[str, Any] = {}
    for key in ("lines", "branches", "functions", "regions"):
        metric = totals.get(key, {})
        if metric:
            coverage[f"{key}_percent"] = metric.get("percent")
            coverage[f"{key}_covered"] = metric.get("covered")
            coverage[f"{key}_count"] = metric.get("count")
    return [], {"coverage": coverage}, []


def parse_cargo_mutants(data: Any, root: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    outcomes = data.get("outcomes", data if isinstance(data, list) else [])
    findings = []
    killed = survived = 0
    for item in outcomes:
        outcome = str(item.get("outcome") or item.get("status") or "").lower()
        if outcome in {"caught", "killed"}:
            killed += 1
        elif outcome in {"missed", "survived", "timeout"}:
            survived += 1
            scenario = item.get("scenario", {})
            mutation = scenario.get("mutant", scenario) if isinstance(scenario, dict) else {}
            findings.append(_finding(
                "cargo-mutants", mutation.get("function") or mutation.get("name") or "cargo-mutants.survived",
                "Survived Rust mutation", "test-quality", "medium",
                _relative(mutation.get("file") or item.get("file"), root),
                mutation.get("line") or item.get("line"),
                mutation.get("description") or item.get("description") or f"Mutation outcome: {outcome}.",
                "Tests may not detect a plausible incorrect behavior change.",
                "Add a contract-backed assertion for the affected behavior.",
            ))
    total = killed + survived
    score = round(killed * 100 / total, 2) if total else None
    return findings, {"mutation": {"tool": "cargo-mutants", "killed": killed, "survived": survived, "total": total, "score_percent": score}}, []


def parse_mutmut(text: str, root: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    counts = {name: 0 for name in ("killed", "survived", "timeout", "suspicious", "skipped")}
    for name in counts:
        match = re.search(rf"(?i)\b{name}\b\s*[:=]?\s*(\d+)", text)
        if match:
            counts[name] = int(match.group(1))
    total = sum(counts.values())
    weak = counts["survived"] + counts["timeout"] + counts["suspicious"]
    score = round(counts["killed"] * 100 / total, 2) if total else None
    limitations = [] if total else ["mutmut output did not expose parseable aggregate counts."]
    return [], {"mutation": {"tool": "mutmut", **counts, "total": total, "score_percent": score}}, limitations

def parse_pit(root_xml: ET.Element, root: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    mutations = root_xml.findall(".//mutation")
    killed = sum(1 for item in mutations if item.attrib.get("status") == "KILLED" or item.findtext("status") == "KILLED")
    survived = [item for item in mutations if item.attrib.get("status") == "SURVIVED" or item.findtext("status") == "SURVIVED"]
    findings = []
    for item in survived:
        file = item.findtext("sourceFile") or "unknown"
        line = item.findtext("lineNumber")
        findings.append(_finding(
            "pit", item.findtext("mutator") or "pit.survived-mutant", "Survived mutation",
            "test-quality", "medium", file, int(line) if line and line.isdigit() else None,
            item.findtext("description") or "A mutation survived the test suite.",
            "The tests may execute this code without detecting an incorrect behavior change.",
            "Add a behavior-, specification-, or property-backed assertion that kills this mutant.",
        ))
    total = len(mutations)
    score = round(killed * 100 / total, 2) if total else None
    return findings, {"mutation": {"tool": "pit", "killed": killed, "survived": len(survived), "total": total, "score_percent": score}}, []


def parse_stryker(data: Any, root: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    findings = []
    total = killed = survived = 0
    for filename, file_data in data.get("files", {}).items():
        for mutant in file_data.get("mutants", []):
            total += 1
            status = mutant.get("status")
            killed += status == "Killed"
            if status in {"Survived", "NoCoverage"}:
                survived += 1
                findings.append(_finding(
                    "stryker", mutant.get("mutatorName", "stryker.survived-mutant"),
                    f"{status} mutation", "test-quality", "medium", _relative(filename, root),
                    mutant.get("location", {}).get("start", {}).get("line"),
                    mutant.get("description") or f"Mutation status: {status}.",
                    "Tests may not detect a plausible incorrect change.",
                    "Add a behavior-focused assertion for the affected branch.",
                ))
    score = round(killed * 100 / total, 2) if total else None
    return findings, {"mutation": {"tool": "stryker", "killed": killed, "survived": survived, "total": total, "score_percent": score}}, []


def parse_bundle_size(data: Any, root: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    """Salida de `measure_artifacts.py`.

    No produce hallazgos: un tamaño no es un defecto sin algo con lo que
    compararlo, y fabricar un presupuesto aquí sería justo el umbral inventado
    que `SKILL.md` prohíbe. Se registra como dimensión para que
    `compare_perf_baseline.py` pueda contrastarlo con la línea base del propio
    repositorio.
    """
    dimensions = {
        "performance": {
            "bundle": {
                "root": data.get("root"),
                "total_bytes": data.get("total_bytes"),
                "file_count": data.get("file_count"),
                "by_extension": data.get("by_extension", {}),
                "largest": data.get("largest", [])[:10],
            }
        }
    }
    return [], dimensions, []


def parse_pytest_benchmark(data: Any, root: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    """Salida de `pytest --benchmark-json`. Igual que arriba: mide, no juzga."""
    benchmarks = {}
    for item in data.get("benchmarks", []) or []:
        stats = item.get("stats", {}) or {}
        benchmarks[item.get("fullname") or item.get("name") or "?"] = {
            "mean_seconds": stats.get("mean"),
            "median_seconds": stats.get("median"),
            "stddev_seconds": stats.get("stddev"),
            "rounds": stats.get("rounds"),
            "ops_per_second": stats.get("ops"),
        }
    return [], {"performance": {"benchmarks": benchmarks}}, []


def parse_web_runtime(data: Any, root: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    """Salida de `probe_web_runtime.py`.

    Aquí SÍ se emite un hallazgo, a diferencia del resto de adaptadores de
    rendimiento, y por una razón concreta: "la página pide fotogramas sin parar
    estando en reposo" no necesita una línea base con la que compararse. Es un
    defecto en términos absolutos —el trabajo no produce nada— igual que lo es
    un secreto en el código. El umbral no se inventa: cero es lo correcto, y se
    exige un margen amplio para no confundirlo con una animación de entrada
    todavía en marcha.

    Los tamaños y tiempos, en cambio, no se juzgan: van como dimensiones y los
    compara `compare_perf_baseline.py`.
    """
    findings: list[dict[str, Any]] = []
    targets = data.get("targets", {}) or {}
    for label, target in targets.items():
        if not target.get("reachable"):
            continue
        idle_fps = target.get("idle_frames_per_second") or 0
        # 5 fps de margen: por debajo puede ser una transición terminando; por
        # encima es un bucle que no descansa.
        if idle_fps > 5:
            findings.append(_finding(
                "web-runtime", "performance.idle_render_loop",
                f"El bucle de render de «{label}» no descansa",
                "performance", "medium" if idle_fps < 30 else "high",
                target.get("url", label), None,
                f"{target.get('idle_frames')} fotogramas en {target.get('idle_seconds')} s "
                f"sin interacción ({idle_fps}/s).",
                "Consume CPU y batería de forma permanente mientras la pestaña esté "
                "abierta, sin producir ningún cambio visible.",
                "Haz que el bucle se detenga cuando no haya nada que animar: pide un "
                "fotograma solo ante un cambio real (invalidación) y deja que la "
                "simulación converja y pare.",
                metric="idle_frames_per_second", value=idle_fps,
            ))

    dimensions = {
        "performance": {
            "web_runtime": {
                label: {
                    key: target.get(key)
                    for key in (
                        "reachable", "idle_frames", "idle_frames_per_second", "idle_requests",
                        "long_tasks", "dom_interactive_ms", "load_ms", "request_count",
                        "transferred_bytes", "dom_nodes",
                    )
                    if key in target
                }
                for label, target in targets.items()
            }
        }
    }
    return findings, dimensions, list(data.get("limitations", []) or [])


JSON_PARSERS: dict[str, Callable[[Any, Path | None], tuple[list[dict[str, Any]], dict[str, Any], list[str]]]] = {
    "semgrep": parse_semgrep,
    "gitleaks": parse_gitleaks,
    "trivy": parse_trivy,
    "osv-scanner": parse_osv,
    "coverage-py": parse_coverage_py,
    "ruff-json": parse_ruff,
    "llvm-cov": parse_llvm_cov,
    "cargo-mutants": parse_cargo_mutants,
    "stryker": parse_stryker,
    "bundle-size": parse_bundle_size,
    "pytest-benchmark": parse_pytest_benchmark,
    "web-runtime": parse_web_runtime,
}


def normalize(tool: str, input_path: Path, root: Path | None = None) -> dict[str, Any]:
    if tool in JSON_PARSERS:
        data = json.loads(input_path.read_text(encoding="utf-8-sig"))
        findings, dimensions, limitations = JSON_PARSERS[tool](data, root)
    elif tool in {"jacoco", "cobertura", "pit"}:
        xml = ET.parse(input_path).getroot()
        parser = {"jacoco": parse_jacoco, "cobertura": parse_cobertura, "pit": parse_pit}[tool]
        findings, dimensions, limitations = parser(xml, root)
    elif tool in {"lcov", "go-cover", "mutmut"}:
        text = input_path.read_text(encoding="utf-8", errors="replace")
        parser = {"lcov": parse_lcov, "go-cover": parse_go_cover, "mutmut": parse_mutmut}[tool]
        findings, dimensions, limitations = parser(text, root)
    else:
        raise ValueError(f"unsupported tool: {tool}")
    return {
        "schema_version": "1.0.0",
        "tool": tool,
        "findings": findings,
        "dimensions": dimensions,
        "limitations": limitations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", required=True, choices=sorted([*JSON_PARSERS, "jacoco", "cobertura", "lcov", "go-cover", "mutmut", "pit"]))
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = normalize(args.tool, args.input, args.root)
    except (OSError, ValueError, json.JSONDecodeError, ET.ParseError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    payload = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

