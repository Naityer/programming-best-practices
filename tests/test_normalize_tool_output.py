from __future__ import annotations

import json
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

if __name__ == "__main__":
    unittest.main()

