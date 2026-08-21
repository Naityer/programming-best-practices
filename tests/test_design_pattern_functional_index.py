import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "skill" / "programming-best-practices" / "scripts" / "measure_design_pattern_functionality.py"
spec = importlib.util.spec_from_file_location("functional_index", MODULE)
functional_index = importlib.util.module_from_spec(spec)
spec.loader.exec_module(functional_index)

class FunctionalIndexTests(unittest.TestCase):
    def test_verified_suite_exceeds_target_and_exposes_limitations(self):
        result = functional_index.compute_index(suite_passed=True)
        self.assertGreater(result["functional_global_index"], 80)
        self.assertTrue(result["target_met"])
        self.assertLess(result["detection"]["score"], 100)
        self.assertIn("Python", result["limitations"][0])

    def test_failed_suite_cannot_claim_target(self):
        result = functional_index.compute_index(suite_passed=False)
        self.assertFalse(result["target_met"])
        self.assertLess(result["functional_global_index"], 80)

if __name__ == "__main__": unittest.main()
