#!/usr/bin/env python3
"""Normalize supported analyzer reports into evidence fragments for build_report.py."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable

SECRET_RE = re.compile(r"(?i)(secret|token|password|api[_-]?key)\s*[:=]\s*\S+")

# Rutas que NO son el código del proyecto: dependencias, cachés y salida
# generada. `SKILL.md` ordena en su paso 2 excluirlas ("Exclude generated,
# vendored, cache, dependency, and build-output directories unless the request
# targets them"), pero los escáneres que recorren el disco por su cuenta no lo
# hacían, y el resultado era una auditoría inservible: sobre este mismo
# repositorio, 263 hallazgos BLOQUEANTES de los cuales 260 estaban en `.venv/` y
# en datos generados, y los 3 restantes eran ficheros `.pyc` y un fixture de
# test con un token falso. Cero reales. Un informe así no se lee: se ignora, y
# con él se ignora el hallazgo verdadero del día que aparezca.
VENDORED_RE = re.compile(
    r"(^|/)("
    r"\.venv|venv|env|virtualenv"
    r"|node_modules|bower_components|vendor"
    r"|__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|\.tox"
    r"|site-packages|dist-info|egg-info"
    r"|dist|dist-[^/]+|build|out|target|coverage|htmlcov|\.vite[^/]*"
    r"|\.git|\.next|\.turbo|\.gradle|\.m2"
    r")(/|$)"
    r"|\.(pyc|pyo|min\.js|min\.css|map)$"
)


def _is_vendored(path: str) -> bool:
    return bool(VENDORED_RE.search(str(path or "").replace("\\", "/")))


def _git_ignored(paths: list[str], root: Path | None) -> set[str]:
    """Subconjunto de `paths` que el propio repositorio declara ignorado.

    `VENDORED_RE` cubre lo que es basura en cualquier proyecto, pero cada
    repositorio tiene además lo suyo — un directorio de datos, artefactos de un
    generador — y ya lo ha declarado en `.gitignore`. Preguntárselo a git es
    mejor que adivinar con una lista de nombres: no hay que codificar
    convenciones ajenas (`projects/`, `.audit/`) que en otro proyecto podrían
    ser código de verdad.

    Silencioso ante cualquier fallo: sin git, o fuera de un repositorio, queda
    solo el patrón estático, que es un mínimo razonable.
    """
    if not paths or root is None:
        return set()
    git = shutil.which("git")
    if not git:
        return set()
    # `-z` y bytes, no texto separado por saltos de línea. En Windows el modo
    # texto traduce `\n` a `\r\n`, git se come el `\r` como parte del nombre del
    # fichero y devuelve la ruta entrecomillada (`"generated/data.md\r"`), que
    # no casa con nada. Separar por NUL evita a la vez la traducción de saltos
    # y el entrecomillado de rutas con caracteres especiales.
    try:
        completed = subprocess.run(
            [git, "check-ignore", "-z", "--stdin"],
            input=b"\0".join(path.encode("utf-8") for path in paths),
            capture_output=True, cwd=str(root), timeout=60, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    return {
        chunk.decode("utf-8", errors="replace").replace("\\", "/")
        for chunk in completed.stdout.split(b"\0")
        if chunk
    }


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
    discriminator: str | int | None = None,
) -> dict[str, Any]:
    # `discriminator` distingue dos hallazgos que comparten herramienta, regla,
    # fichero y línea. Ocurre de verdad: dos secretos en la MISMA línea daban la
    # misma huella, dos ids iguales, y el validador rechazaba el informe entero
    # — la auditoría no producía nada. Suele ser la columna, y por eso se elige
    # ese dato y no un contador: la huella tiene que seguir siendo estable entre
    # ejecuciones para poder deduplicar y silenciar hallazgos.
    raw = f"{tool}|{rule}|{file}|{line or 0}|{title}"
    if discriminator is not None:
        raw = f"{raw}|{discriminator}"
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
            metadata.get("category") if metadata.get("category") in {"security", "performance", "correctness"} else "maintainability",
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
            discriminator=item.get("StartColumn"),
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
        elif re.fullmatch(r"S\d+", code):  # flake8-bandit; SIM*, SLF*, SLOT* no son de seguridad
            category, severity = "security", "high"
        elif code.startswith(("B", "PLE", "PLW")):
            category, severity = "correctness", "medium"
        else:
            category, severity = "maintainability", "low"
        message = item.get("message") or code
        if code == "B008" and re.search(r"`(Depends|Query|Body|Header|Path|Form|File|Cookie|Security)`", message):
            category, severity = "maintainability", "low"  # idioma de FastAPI, no un valor por defecto mutable
        fix = item.get("fix")
        recommendation = fix.get("message") if isinstance(fix, dict) and fix.get("message") else "Apply the smallest rule-specific correction and rerun Ruff."
        findings.append(_finding(
            "ruff", code, f"{code}: {message}", category, severity,
            _relative(item.get("filename"), root), location.get("row"), message,
            "The diagnostic identifies a concrete correctness, security, or maintainability defect.",
            recommendation, discriminator=location.get("column"),
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


_DESIGN_PATTERN_CATALOG_PATH = Path(__file__).resolve().parent.parent.parent / "references" / "design-patterns" / "catalog.json"


def _design_pattern_families() -> dict[str, str]:
    """pattern_id -> family, read straight from the bundled catalog.json
    rather than importing the design_patterns package — keeps this parser
    self-contained like every other one in this file."""
    try:
        data = json.loads(_DESIGN_PATTERN_CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        item["id"]: item["family"]
        for item in data.get("patterns", []) or []
        if isinstance(item, dict) and item.get("id") and item.get("family")
    }


def _design_pattern_finding(pattern: dict[str, Any], root: Path | None) -> dict[str, Any]:
    pattern_id = str(pattern.get("pattern_id") or "pattern")
    status = pattern.get("status")
    location = pattern.get("primary_location") or {}
    file_path = _relative(location.get("file"), root)
    line = location.get("line")
    confidence = pattern.get("confidence") or "low"
    evidence_text = "; ".join(
        str(item.get("description", "")) for item in pattern.get("evidence", []) or [] if isinstance(item, dict)
    ) or "structural evidence recorded by the design-pattern analyzer"
    refactoring = pattern.get("refactoring") or {}
    steps = [str(step) for step in refactoring.get("steps", []) if str(step).strip()]
    verification = str(refactoring.get("verification") or "").strip()
    structured_remediation = " ".join([
        *(f"Step {index}: {step}" for index, step in enumerate(steps, 1)),
        *([f"Verification: {verification}"] if verification else []),
    ])

    if status == "misimplemented":
        return _finding(
            "design-patterns", f"pbp.pattern.{pattern_id}.misimplemented",
            f"{pattern_id} appears misimplemented", "quality", "medium", file_path, line,
            evidence_text,
            f"The structure demonstrates {pattern_id}'s intent, but at least one of its invariants "
            f"is violated: {evidence_text}",
            structured_remediation or f"Review the {pattern_id} implementation and fix the violated invariant.",
            confidence=confidence,
        )
    # refactor-opportunity — the one status spec §19 turns into a finding
    # unconditionally, because it is itself already the observed-repetition
    # evidence (opportunities.py never fires on "I didn't find X").
    smell = refactoring.get("smell", "a repeated, observed design problem")
    sites = refactoring.get("sites") or list((pattern.get("roles") or {}).values())
    return _finding(
        "design-patterns", f"pbp.pattern.{pattern_id}.opportunity",
        f"Refactoring opportunity: {pattern_id}", "quality", "low", file_path, line,
        evidence_text,
        f"{smell.capitalize()}, found at {len(sites)} site(s): {', '.join(str(s) for s in sites) or evidence_text}.",
        f"Consider introducing {pattern_id} to remove the repeated {smell}.",
        confidence=confidence,
    )


def parse_design_patterns(data: Any, root: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    """Salida de `analyze_design_patterns.py`. Spec §19: `detected`/`partial`
    nunca son findings — solo alimentan `dimensions`; `ambiguous` tampoco,
    pasa a `dimensions` + una `limitation` que pide revisión humana (spec §10);
    `misimplemented`/`refactor-opportunity` sí, porque son los únicos dos
    estados con un problema concreto y accionable detrás.
    """
    findings: list[dict[str, Any]] = []
    limitations: list[str] = list(data.get("limitations", []) or [])
    families = _design_pattern_families()
    counts = {"detected": 0, "partial": 0, "misimplemented": 0, "refactor_opportunities": 0, "ambiguous": 0}
    by_family: dict[str, int] = {}
    # A per-pattern roster, not just aggregate counts: render_report.py's
    # Design Patterns table (spec §23) needs individual rows, but
    # audit-result.schema.json has no array for that — dimensions is the one
    # unrestricted object in the canonical report, so the roster travels
    # there instead of widening the schema.
    roster: list[dict[str, Any]] = []

    for pattern in data.get("patterns", []) or []:
        status = pattern.get("status")
        pattern_id = str(pattern.get("pattern_id") or "")
        location = pattern.get("primary_location") or {}
        roster.append({
            "pattern_id": pattern_id, "status": status, "confidence": pattern.get("confidence"),
            "file": _relative(location.get("file"), root), "line": location.get("line"),
            "participants": len(pattern.get("roles") or {}),
        })
        if status in {"detected", "partial"}:
            counts[status] += 1
            family = families.get(pattern_id, "unknown")
            by_family[family] = by_family.get(family, 0) + 1
        elif status == "ambiguous":
            counts["ambiguous"] += 1
            competitors = ", ".join(
                str(item.get("pattern_id", "?")) for item in pattern.get("contradictions", []) or []
            )
            limitations.append(
                f"{pattern_id} at {location.get('file', 'unknown')}:{location.get('line', '?')} is ambiguous "
                f"against {competitors or 'another pattern'} — needs human review (spec §10)."
            )
        elif status == "misimplemented":
            counts["misimplemented"] += 1
            findings.append(_design_pattern_finding(pattern, root))
        elif status == "refactor-opportunity":
            counts["refactor_opportunities"] += 1
            findings.append(_design_pattern_finding(pattern, root))

    dimensions = {"design_patterns": {**counts, "by_family": by_family, "patterns": roster}}
    return findings, dimensions, limitations



_NON_ACTIONABLE_ALGORITHM_STATES = {"recognized", "optimal", "acceptable", "ambiguous", "unknown"}


def parse_algorithms(data: Any, root: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    """Keep healthy algorithms as metrics; only actionable states become findings."""
    findings: list[dict[str, Any]] = []
    limitations: list[str] = list(data.get("limitations", []) or [])
    counts: dict[str, int] = {}
    by_family: dict[str, int] = {}
    roster: list[dict[str, Any]] = []
    for item in data.get("algorithms", []) or []:
        status = str(item.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
        family = str(item.get("family") or "unknown")
        by_family[family] = by_family.get(family, 0) + 1
        location = item.get("primary_location") or {}
        recommendation = item.get("recommendation") or {}
        complexity = item.get("complexity") or {}
        roster.append({
            "id": item.get("id"), "algorithm_id": item.get("algorithm_id"),
            "rule_id": item.get("rule_id"), "family": family, "status": status,
            "file": _relative(location.get("file"), root), "line": location.get("line"),
            "current_approach": item.get("current_approach"),
            "current_time": (complexity.get("current") or {}).get("time"),
            "expected_time": (complexity.get("expected") or {}).get("time"),
            "correction_level": recommendation.get("correction_level"),
        })
        if status in {"ambiguous", "unknown"}:
            limitations.append(
                f"Algorithm assessment {item.get('id', '?')} at {location.get('file', 'unknown')}:"
                f"{location.get('line', '?')} is {status}; human evidence is required."
            )
        if status in _NON_ACTIONABLE_ALGORITHM_STATES:
            continue
        category = "security" if status == "security-risk" else str(item.get("category") or "performance")
        severity = "high" if status in {"incorrect", "security-risk"} else "medium" if status == "suboptimal" else "low"
        evidence_text = "; ".join(
            str(evidence.get("description", "")) for evidence in item.get("evidence", []) if isinstance(evidence, dict)
        ) or "Static structural evidence recorded by Algorithm Intelligence."
        expected = (complexity.get("expected") or {}).get("time")
        current = (complexity.get("current") or {}).get("time")
        impact = f"The current approach is classified as {status} (observed {current or 'unknown'}; expected {expected or 'unknown'})."
        findings.append(_finding(
            "algorithms", str(item.get("rule_id") or "pbp.algorithm.finding"),
            f"Algorithm assessment: {item.get('algorithm_id', 'unknown')}", category, severity,
            _relative(location.get("file"), root), location.get("line"), evidence_text, impact,
            str(recommendation.get("summary") or "Review the algorithm and its stated preconditions."),
            confidence=str(item.get("confidence") or "low"),
        ))
    dimensions = {"algorithms": {"counts": counts, "by_family": by_family, "occurrences": roster}}
    return findings, dimensions, sorted(set(limitations))

_STRUCTURE_RECOMMENDATIONS = {
    "file-size": "Comprobar si el módulo reúne varias responsabilidades y separar la que tenga un motivo de cambio propio.",
    "function-length": "Extraer los tramos con nombre propio solo si cada uno tiene una sola razón de cambio; no trocear por trocear.",
    "cyclomatic-complexity": "Reducir ramas con cláusulas de guarda o tablas de decisión y cubrir cada rama con pruebas antes de refactorizar.",
    "parameters": "Agrupar los parámetros que viajan juntos en un objeto de valor si representan un concepto.",
    "nesting": "Aplanar con retornos tempranos o extraer el bloque interior.",
    "many-methods": "Revisar si la clase mezcla responsabilidades (SRP) y repartirlas por cohesión de datos.",
    "fan-out": "Revisar acoplamiento: un módulo con muchas dependencias suele hacer demasiado o conocer demasiado.",
    "duplication": "Extraer lo común solo si los dos usos cambian por la misma razón; si divergen, dejar la copia.",
    "import-cycle": "Romper el ciclo invirtiendo la dependencia (interfaz o parámetro) o moviendo lo compartido a un tercer módulo.",
    "swallowed-exception": "Registrar el error con contexto o propagarlo; si descartarlo es intencionado, decir por qué en un comentario.",
    "test-no-assertion": "Añadir la comprobación del resultado esperado; si es una prueba de humo (solo que no lance), decirlo en el nombre o con un comentario.",
    "test-tautological-assertion": "Sustituir la aserción por una comparación contra un valor esperado calculado a mano, no contra la propia expresión bajo prueba.",
}


def parse_structure(data: Any, root: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    """Métricas estructurales: umbrales de revisión, nunca un veredicto (confianza media/baja, severidad baja/media)."""
    findings: list[dict[str, Any]] = []
    by_rule: dict[str, int] = {}
    for item in data.get("items", []) or []:
        rule = str(item.get("rule_id") or "pbp.structure.finding")
        short = rule.rsplit(".", 1)[-1]
        by_rule[short] = by_rule.get(short, 0) + 1
        value, threshold = item.get("value") or 0, item.get("threshold") or 0
        severe = short == "cyclomatic-complexity" and value >= 2 * threshold
        weak_test = short.startswith("test-")
        findings.append(_finding(
            "structure", rule, str(item.get("title") or rule), "tests" if weak_test else "maintainability",
            "medium" if severe or short in {"swallowed-exception", "test-tautological-assertion"} else "low",
            str(item.get("file") or "unknown"), item.get("line"),
            f"{item.get('metric')}={value} (umbral de revisión {threshold}, configurable)",
            "Un módulo, función o clase por encima del umbral suele indicar varias responsabilidades o código difícil de probar.",
            _STRUCTURE_RECOMMENDATIONS.get(short, "Revisar el contexto antes de actuar."),
            confidence="medium" if short in {"swallowed-exception", "test-tautological-assertion"} else "low",
            metric=str(item.get("metric") or ""), value=value, discriminator=item.get("name"),
        ))
    dimensions = {"structure": {"files_analyzed": data.get("files_analyzed", 0), "by_rule": by_rule}}
    return findings, dimensions, list(data.get("limitations", []) or [])

JSON_PARSERS: dict[str, Callable[[Any, Path | None], tuple[list[dict[str, Any]], dict[str, Any], list[str]]]] = {
    "semgrep": parse_semgrep,
    "gitleaks": parse_gitleaks,
    "design-patterns": parse_design_patterns,
    "algorithms": parse_algorithms,
    "structure": parse_structure,
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


def normalize(tool: str, input_path: Path, root: Path | None = None, *, include_vendored: bool = False) -> dict[str, Any]:
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

    # Se descartan los hallazgos que caen en dependencias, cachés o salida
    # generada — ver `VENDORED_RE`. El recuento se declara como limitación en
    # vez de desaparecer en silencio: ocultar sin decirlo sería tan malo como
    # ahogar el informe en ruido.
    if not include_vendored:
        all_paths = sorted({loc.get("file", "") for f in findings for loc in f.get("locations", []) if loc.get("file")})
        ignored = _git_ignored(all_paths, root)
        kept = [
            f for f in findings
            if not any(
                _is_vendored(loc.get("file", "")) or loc.get("file", "").replace("\\", "/") in ignored
                for loc in f.get("locations", [])
            )
        ]
        dropped = len(findings) - len(kept)
        if dropped:
            limitations = [
                *limitations,
                f"{dropped} hallazgo(s) de {tool} en dependencias o ficheros generados "
                f"quedaron fuera del informe; usa --include-vendored para incluirlos.",
            ]
        findings = kept

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
    parser.add_argument("--include-vendored", action="store_true",
                        help="No excluir dependencias, cachés ni ficheros generados")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = normalize(args.tool, args.input, args.root, include_vendored=args.include_vendored)
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

