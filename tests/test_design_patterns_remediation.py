import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "skill" / "programming-best-practices" / "scripts" / "normalize_tool_output.py"
spec = importlib.util.spec_from_file_location("normalize_tool_output_for_remediation", MODULE)
normalize = importlib.util.module_from_spec(spec)
spec.loader.exec_module(normalize)

class StructuredRemediationTests(unittest.TestCase):
    def test_misimplementation_steps_and_verification_reach_finding(self):
        data = {"patterns": [{
            "pattern_id": "adapter", "status": "misimplemented", "confidence": "medium",
            "primary_location": {"file": "adapter.py", "line": 10},
            "roles": {"adapter": "BrokenAdapter", "target": "Target", "adaptee": "Legacy"},
            "evidence": [{"kind": "hard", "description": "adaptee is stored but not delegated to"}],
            "contradictions": [],
            "refactoring": {
                "steps": ["Map target operations to the adaptee.", "Keep conversion at the boundary."],
                "verification": "Run target-contract tests.",
            },
        }]}
        findings, _, _ = normalize.parse_design_patterns(data, None)
        recommendation = findings[0]["recommendation"]
        self.assertIn("Step 1:", recommendation)
        self.assertIn("Step 2:", recommendation)
        self.assertIn("Verification:", recommendation)

if __name__ == "__main__": unittest.main()
