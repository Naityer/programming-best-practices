from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import SKILL, load_module

normalize_tool_output = load_module("normalize_tool_output", SKILL / "scripts" / "normalize_tool_output.py")


class NormalizeToolOutputTests(unittest.TestCase):
    def _json(self, data):
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "input.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return directory, path

    def test_semgrep_and_gitleaks_become_canonical_findings(self) -> None:
        semgrep = {"results": [{"check_id": "C.Users.example.rules.pbp.python.rule-one", "path": "app.py", "start": {"line": 2}, "extra": {"message": "bad", "severity": "ERROR", "metadata": {"category": "security", "confidence": "HIGH"}}}], "errors": []}
        directory, path = self._json(semgrep)
        try:
            result = normalize_tool_output.normalize("semgrep", path)
            self.assertEqual("high", result["findings"][0]["severity"])
            self.assertEqual("security", result["findings"][0]["category"])
            self.assertEqual("pbp.python.rule-one", result["findings"][0]["rule_id"])
        finally:
            directory.cleanup()

        leak = [{"RuleID": "generic-api-key", "Description": "token=actual-secret-value", "File": "config.py", "StartLine": 1, "Secret": "actual-secret-value"}]
        directory, path = self._json(leak)
        try:
            result = normalize_tool_output.normalize("gitleaks", path)
            text = json.dumps(result)
            self.assertEqual("blocker", result["findings"][0]["severity"])
            self.assertNotIn("actual-secret-value", text)
        finally:
            directory.cleanup()

    def test_osv_trivy_coverage_and_mutation_metrics(self) -> None:
        osv = {"results": [{"source": {"path": "requirements.txt"}, "packages": [{"package": {"name": "demo"}, "vulnerabilities": [{"id": "OSV-1", "summary": "Known issue", "database_specific": {"severity": "HIGH"}}]}]}]}
        directory, path = self._json(osv)
        try:
            self.assertEqual("OSV-1", normalize_tool_output.normalize("osv-scanner", path)["findings"][0]["rule_id"])
        finally:
            directory.cleanup()

        coverage = {"totals": {"percent_covered": 81.5, "covered_lines": 81, "num_statements": 100, "covered_branches": 8, "num_branches": 10}}
        directory, path = self._json(coverage)
        try:
            dimensions = normalize_tool_output.normalize("coverage-py", path)["dimensions"]
            self.assertEqual(81.5, dimensions["coverage"]["line_percent"])
        finally:
            directory.cleanup()

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mutations.xml"
            path.write_text("<mutations><mutation status='KILLED'/><mutation status='SURVIVED'><sourceFile>A.java</sourceFile><lineNumber>3</lineNumber><mutator>NEGATE</mutator><description>negated</description></mutation></mutations>", encoding="utf-8")
            result = normalize_tool_output.normalize("pit", path)
            self.assertEqual(50.0, result["dimensions"]["mutation"]["score_percent"])
            self.assertEqual(1, len(result["findings"]))

    def test_go_llvm_and_cargo_mutation_formats(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "go-cover.out"
            path.write_text("""mode: set
example.go:1.1,2.1 2 1
example.go:3.1,4.1 1 0
""", encoding="utf-8")
            coverage = normalize_tool_output.normalize("go-cover", path)["dimensions"]["coverage"]
            self.assertEqual(66.67, coverage["line_percent"])

        llvm = {"data": [{"totals": {"lines": {"count": 10, "covered": 8, "percent": 80.0}, "branches": {"count": 4, "covered": 3, "percent": 75.0}}}]}
        directory, path = self._json(llvm)
        try:
            coverage = normalize_tool_output.normalize("llvm-cov", path)["dimensions"]["coverage"]
            self.assertEqual(75.0, coverage["branches_percent"])
        finally:
            directory.cleanup()

        cargo = {"outcomes": [{"outcome": "Caught"}, {"outcome": "Missed", "scenario": {"mutant": {"file": "src/lib.rs", "line": 7, "function": "add"}}}]}
        directory, path = self._json(cargo)
        try:
            result = normalize_tool_output.normalize("cargo-mutants", path)
            self.assertEqual(50.0, result["dimensions"]["mutation"]["score_percent"])
            self.assertEqual(1, len(result["findings"]))
        finally:
            directory.cleanup()

    def test_trivy_and_mutmut_are_redacted_and_measured(self) -> None:
        trivy = {"Results": [{"Target": "requirements.txt", "Vulnerabilities": [{"VulnerabilityID": "CVE-1", "PkgName": "demo", "Severity": "CRITICAL", "Title": "token=do-not-emit", "FixedVersion": "2"}]}]}
        directory, path = self._json(trivy)
        try:
            result = normalize_tool_output.normalize("trivy", path)
            self.assertEqual("high", result["findings"][0]["severity"])
            self.assertNotIn("do-not-emit", json.dumps(result))
        finally:
            directory.cleanup()

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mutmut.txt"
            path.write_text("killed 8 survived 2 timeout 0 suspicious 0 skipped 0", encoding="utf-8")
            mutation = normalize_tool_output.normalize("mutmut", path)["dimensions"]["mutation"]
            self.assertEqual(80.0, mutation["score_percent"])

    def test_ruff_json_findings_are_preserved(self) -> None:
        data = [{
            "code": "F821", "message": "Undefined name x", "filename": "app.py",
            "location": {"row": 3, "column": 1}, "fix": None,
        }]
        directory, path = self._json(data)
        try:
            finding = normalize_tool_output.normalize("ruff-json", path)["findings"][0]
            self.assertEqual("F821", finding["rule_id"])
            self.assertEqual("correctness", finding["category"])
            self.assertEqual("high", finding["severity"])
            self.assertEqual(3, finding["locations"][0]["line"])
        finally:
            directory.cleanup()

class DesignPatternsParserTests(unittest.TestCase):
    """spec §19: detected/partial -> only dimensions; ambiguous -> dimensions
    + a limitation asking for human review; misimplemented/refactor-opportunity
    -> findings."""

    def _report(self, patterns: list[dict], limitations: list[str] | None = None) -> dict:
        return {
            "schema_version": "1.0.0", "files_scanned": 3, "languages": ["python"],
            "patterns": patterns, "limitations": limitations or [],
        }

    def test_detected_and_partial_never_become_findings(self) -> None:
        data = self._report([
            {"pattern_id": "adapter", "status": "detected", "confidence": "medium",
             "primary_location": {"file": "a.py", "line": 5}, "roles": {"target": "T", "adapter": "A", "adaptee": "D"},
             "evidence": [], "contradictions": []},
            {"pattern_id": "builder", "status": "partial", "confidence": "low",
             "primary_location": {"file": "b.py", "line": 9}, "roles": {"builder": "B"},
             "evidence": [], "contradictions": []},
        ])
        findings, dimensions, limitations = normalize_tool_output.parse_design_patterns(data, None)
        self.assertEqual([], findings)
        self.assertEqual([], limitations)
        design_patterns = dimensions["design_patterns"]
        self.assertEqual(1, design_patterns["detected"])
        self.assertEqual(1, design_patterns["partial"])
        self.assertEqual({"structural": 1, "creational": 1}, design_patterns["by_family"])
        self.assertEqual(2, len(design_patterns["patterns"]))

    def test_ambiguous_becomes_a_limitation_not_a_finding(self) -> None:
        data = self._report([{
            "pattern_id": "decorator", "status": "ambiguous", "confidence": "low",
            "primary_location": {"file": "svc.py", "line": 12},
            "roles": {"component": "Service", "concrete_component": "RealService", "decorator": "CachingProxy"},
            "evidence": [], "contradictions": [{"pattern_id": "proxy", "reason": "same structure"}],
        }])
        findings, dimensions, limitations = normalize_tool_output.parse_design_patterns(data, None)
        self.assertEqual([], findings)
        self.assertEqual(1, dimensions["design_patterns"]["ambiguous"])
        self.assertEqual(1, len(limitations))
        self.assertIn("proxy", limitations[0])
        self.assertIn("human review", limitations[0])

    def test_misimplemented_becomes_a_medium_severity_quality_finding(self) -> None:
        data = self._report([{
            "pattern_id": "singleton", "status": "misimplemented", "confidence": "medium",
            "primary_location": {"file": "registry.py", "line": 20}, "roles": {"singleton": "Registry"},
            "evidence": [{"kind": "hard", "description": "the cache is not guarded against concurrent access"}],
            "contradictions": [],
        }])
        findings, dimensions, _ = normalize_tool_output.parse_design_patterns(data, None)
        self.assertEqual(1, len(findings))
        finding = findings[0]
        self.assertEqual("pbp.pattern.singleton.misimplemented", finding["rule_id"])
        self.assertEqual("quality", finding["category"])
        self.assertEqual("medium", finding["severity"])
        self.assertEqual("medium", finding["confidence"])
        self.assertEqual("registry.py", finding["locations"][0]["file"])
        self.assertEqual(1, dimensions["design_patterns"]["misimplemented"])

    def test_refactor_opportunity_becomes_a_low_severity_quality_finding(self) -> None:
        data = self._report([{
            "pattern_id": "strategy", "status": "refactor-opportunity", "confidence": "medium",
            "primary_location": {"file": "calc.py", "line": 4},
            "roles": {"discriminator_site_1": "Calculator.calculate", "discriminator_site_2": "Calculator.validate"},
            "evidence": [{"kind": "hard", "description": "shared discriminator across 2 methods"}],
            "contradictions": [],
            "refactoring": {"smell": "repeated conditional dispatch", "candidate_pattern": "strategy",
                             "sites": ["Calculator.calculate", "Calculator.validate"]},
        }])
        findings, dimensions, _ = normalize_tool_output.parse_design_patterns(data, None)
        self.assertEqual(1, len(findings))
        finding = findings[0]
        self.assertEqual("pbp.pattern.strategy.opportunity", finding["rule_id"])
        self.assertEqual("low", finding["severity"])
        self.assertEqual(1, dimensions["design_patterns"]["refactor_opportunities"])

    def test_a_pattern_with_no_evidence_still_produces_a_valid_finding(self) -> None:
        data = self._report([{
            "pattern_id": "adapter", "status": "misimplemented", "confidence": "low",
            "primary_location": {"file": "a.py", "line": 1}, "roles": {}, "evidence": [], "contradictions": [],
        }])
        findings, _, _ = normalize_tool_output.parse_design_patterns(data, None)
        self.assertEqual(1, len(findings))
        self.assertTrue(findings[0]["impact"])
        self.assertTrue(findings[0]["evidence"])

    def test_full_pipeline_via_normalize(self) -> None:
        directory = tempfile.TemporaryDirectory()
        try:
            path = Path(directory.name) / "design-patterns.json"
            path.write_text(json.dumps(self._report([{
                "pattern_id": "observer", "status": "detected", "confidence": "medium",
                "primary_location": {"file": "bus.py", "line": 3},
                "roles": {"subject": "EventBus", "observer": "Handler"},
                "evidence": [], "contradictions": [],
            }])), encoding="utf-8")
            result = normalize_tool_output.normalize("design-patterns", path)
            self.assertEqual([], result["findings"])
            self.assertEqual(1, result["dimensions"]["design_patterns"]["detected"])
        finally:
            directory.cleanup()


if __name__ == "__main__":
    unittest.main()



class FingerprintUniquenessTests(unittest.TestCase):
    """Dos hallazgos distintos nunca pueden compartir id."""

    def test_two_secrets_on_the_same_line_get_different_ids(self) -> None:
        # Caso real: una linea con dos tokens. Antes producian la misma huella,
        # el mismo id, y el validador rechazaba el informe COMPLETO -- es decir,
        # la auditoria no entregaba nada.
        data = [
            {"RuleID": "notion-api-token", "Description": "Notion token",
             "File": "notes.md", "StartLine": 158, "StartColumn": 10},
            {"RuleID": "notion-api-token", "Description": "Notion token",
             "File": "notes.md", "StartLine": 158, "StartColumn": 70},
        ]
        findings, _, _ = normalize_tool_output.parse_gitleaks(data, None)
        self.assertEqual(len(findings), 2)
        self.assertNotEqual(findings[0]["id"], findings[1]["id"])
        self.assertNotEqual(findings[0]["fingerprint"], findings[1]["fingerprint"])

    def test_the_fingerprint_is_stable_across_runs(self) -> None:
        """Debe poder deduplicarse y silenciarse: no vale un contador."""
        data = [{"RuleID": "aws-key", "Description": "AWS", "File": "a.py",
                 "StartLine": 3, "StartColumn": 12}]
        first, _, _ = normalize_tool_output.parse_gitleaks(data, None)
        second, _, _ = normalize_tool_output.parse_gitleaks(data, None)
        self.assertEqual(first[0]["fingerprint"], second[0]["fingerprint"])


class VendoredExclusionTests(unittest.TestCase):
    """SKILL.md paso 2: excluir dependencias, cache y salida generada."""

    def _gitleaks(self, *paths: str):
        return [{"RuleID": "generic-api-key", "Description": "key", "File": p,
                 "StartLine": 1, "StartColumn": 1} for p in paths]

    def test_dependencies_and_generated_files_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "gitleaks.json"
            report.write_text(json.dumps(self._gitleaks(
                ".venv/Lib/site-packages/pkg/config.py",
                "node_modules/lib/index.js",
                "tests/__pycache__/test_x.cpython-312.pyc",
                "src/app/settings.py",                      # este SI es codigo
            )), encoding="utf-8")
            result = normalize_tool_output.normalize("gitleaks", report)
            files = [f["locations"][0]["file"] for f in result["findings"]]
            self.assertEqual(files, ["src/app/settings.py"])

    def test_paths_the_repository_itself_ignores_are_excluded(self) -> None:
        """Cada repo declara lo suyo en .gitignore; se le pregunta a git."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / ".gitignore").write_text("generated/" + chr(10), encoding="utf-8")
            (root / "generated").mkdir()
            report = root / "gitleaks.json"
            report.write_text(json.dumps(self._gitleaks(
                "generated/data.md", "src/app.py",
            )), encoding="utf-8")
            result = normalize_tool_output.normalize("gitleaks", report, root)
            files = [f["locations"][0]["file"] for f in result["findings"]]
            self.assertEqual(files, ["src/app.py"])

    def test_what_was_excluded_is_declared_not_hidden(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "gitleaks.json"
            report.write_text(json.dumps(self._gitleaks(".venv/x.py")), encoding="utf-8")
            result = normalize_tool_output.normalize("gitleaks", report)
            self.assertEqual(result["findings"], [])
            self.assertTrue(any("quedaron fuera" in item for item in result["limitations"]))

    def test_the_exclusion_can_be_turned_off(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "gitleaks.json"
            report.write_text(json.dumps(self._gitleaks(".venv/x.py")), encoding="utf-8")
            result = normalize_tool_output.normalize("gitleaks", report, include_vendored=True)
            self.assertEqual(len(result["findings"]), 1)
