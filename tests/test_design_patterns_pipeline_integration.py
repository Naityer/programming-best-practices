"""End-to-end: plan_audit -> run_audit -> normalize -> build_report -> render,
for real, with a real subprocess running analyze_design_patterns.py against a
small repo — not mocked at any stage. This is the verification the plan
(design-patterns-module/03-plan.md) calls for before Fase 2 counts as done.
"""

from __future__ import annotations

import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests.helpers import SKILL, load_module

scripts = SKILL / "scripts"
sys.path.insert(0, str(scripts))
plan_audit = load_module("plan_audit", scripts / "plan_audit.py")
run_audit = load_module("run_audit", scripts / "run_audit.py")
build_report = load_module("build_report", scripts / "build_report.py")
render_report = load_module("render_report_pipeline_integration", scripts / "render_report.py")

ADAPTER_REPO = {
    "ports.py": """
        class PaymentGateway:
            def pay(self):
                raise NotImplementedError
    """,
    "legacy_client.py": """
        class LegacyGateway:
            def charge(self):
                return True
    """,
    "adapter.py": """
        from ports import PaymentGateway
        from legacy_client import LegacyGateway

        class LegacyGatewayAdapter(PaymentGateway):
            def __init__(self, legacy: LegacyGateway):
                self._legacy = legacy

            def pay(self):
                return self._legacy.charge()
    """,
    "calc.py": """
        class Calculator:
            def calculate(self, kind, x):
                if kind == "fast":
                    return x
                elif kind == "accurate":
                    return x * 2

            def validate(self, kind, x):
                if kind == "fast":
                    return True
                elif kind == "accurate":
                    return x > 0
    """,
}


def write_repo(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")


class DesignPatternsPipelineIntegrationTests(unittest.TestCase):
    def test_full_chain_finds_the_adapter_and_the_strategy_opportunity(self) -> None:
        with tempfile.TemporaryDirectory() as project_dir, tempfile.TemporaryDirectory() as work_dir:
            root = Path(project_dir)
            write_repo(root, ADAPTER_REPO)

            plan = plan_audit.create_plan(root, "standard")
            check = next(item for item in plan["checks"] if item["id"] == "universal.design-patterns")
            self.assertEqual("planned", check["status"], msg="python-runtime should always resolve in the test env")

            exec_dir = Path(work_dir) / "execution"
            execution = run_audit.execute_plan(
                plan, exec_dir, allow_project_writes=False, allow_network=False, allow_generated_code=False,
            )
            result = next(item for item in execution["checks"] if item["id"] == "universal.design-patterns")
            self.assertEqual("passed", result["status"], msg=result.get("reason") or result)
            self.assertEqual(0, result["exit_code"])

            artifact_path = Path(result["artifact_dir"]) / "design-patterns.json"
            self.assertTrue(artifact_path.is_file())
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            pattern_ids_by_status = {(p["pattern_id"], p["status"]) for p in artifact["patterns"]}
            self.assertIn(("adapter", "detected"), pattern_ids_by_status)
            self.assertIn(("strategy", "refactor-opportunity"), pattern_ids_by_status)

            report = build_report.build(execution, [])
            design_patterns = report["summary"]["dimensions"]["design_patterns"]
            self.assertGreaterEqual(design_patterns["detected"], 1)
            self.assertGreaterEqual(design_patterns["refactor_opportunities"], 1)
            opportunity_findings = [f for f in report["findings"] if f["rule_id"] == "pbp.pattern.strategy.opportunity"]
            self.assertEqual(1, len(opportunity_findings))
            self.assertEqual("low", opportunity_findings[0]["severity"])

            canonical_path = Path(work_dir) / "canonical.json"
            canonical_path.write_text(json.dumps(report), encoding="utf-8")
            destination = render_report.render(canonical_path, root, Path(work_dir) / "rendered")
            markdown = (destination / "report.md").read_text(encoding="utf-8")
            self.assertIn("## Design Patterns", markdown)
            self.assertIn("pbp.pattern.strategy.opportunity", markdown)

            sarif = json.loads((destination / "report.sarif").read_text(encoding="utf-8"))
            sarif_rule_ids = {rule["id"] for rule in sarif["runs"][0]["tool"]["driver"]["rules"]}
            self.assertIn("pbp.pattern.strategy.opportunity", sarif_rule_ids)

    def test_fast_profile_never_plans_or_runs_the_check(self) -> None:
        with tempfile.TemporaryDirectory() as project_dir:
            root = Path(project_dir)
            write_repo(root, ADAPTER_REPO)
            plan = plan_audit.create_plan(root, "fast")
            self.assertNotIn("universal.design-patterns", {item["id"] for item in plan["checks"]})

    def test_runs_without_project_write_or_network_authorization(self) -> None:
        """spec §16: NO network, NO project writes. The check must execute
        under the strictest defaults, not merely be capable of doing so."""
        with tempfile.TemporaryDirectory() as project_dir, tempfile.TemporaryDirectory() as work_dir:
            root = Path(project_dir)
            write_repo(root, {"plain.py": "class Plain:\n    def x(self):\n        return 1\n"})
            plan = plan_audit.create_plan(root, "standard")
            execution = run_audit.execute_plan(plan, Path(work_dir) / "execution")
            result = next(item for item in execution["checks"] if item["id"] == "universal.design-patterns")
            self.assertEqual("passed", result["status"])


if __name__ == "__main__":
    unittest.main()
