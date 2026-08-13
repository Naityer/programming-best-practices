from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.helpers import SKILL, load_module

import sys
sys.path.insert(0, str(SKILL / "scripts"))
plan_test_pipeline = load_module("plan_test_pipeline", SKILL / "scripts" / "plan_test_pipeline.py")


class TestPipelineTests(unittest.TestCase):
    def test_oracle_requirements_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("value = 1\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                plan_test_pipeline.create_test_pipeline(root, "app", "specification")
            with self.assertRaises(ValueError):
                plan_test_pipeline.create_test_pipeline(root, "app", "property")

    def test_pipeline_contains_all_gates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("value = 1\n", encoding="utf-8")
            result = plan_test_pipeline.create_test_pipeline(
                root, "app", "property", oracle_rule="output is deterministic"
            )
            self.assertEqual(["generate", "semantic-review", "integration", "validate-strength"], [item["id"] for item in result["stages"]])
            self.assertTrue(result["authorization_required"]["test_generation"])
            self.assertTrue(result["authorization_required"]["generated_code_execution"])


if __name__ == "__main__":
    unittest.main()

