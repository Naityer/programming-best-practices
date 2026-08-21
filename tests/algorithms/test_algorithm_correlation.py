from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "skill" / "programming-best-practices" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from algorithms import analyze_repository


class AlgorithmCorrelationTests(unittest.TestCase):
    SOURCE = "def f(xs, queries):\n    for q in queries:\n        if q in xs:\n            print(q)\n"

    def _run(self, **kwargs):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "case.py").write_text(self.SOURCE, encoding="utf-8")
            return analyze_repository(root, use_cache=False, **kwargs)

    def test_quadratic_shape_is_not_security_by_default(self) -> None:
        item = self._run()["algorithms"][0]
        self.assertEqual("performance", item["category"])
        self.assertNotEqual("security-risk", item["status"])

    def test_external_control_and_amplification_are_both_required(self) -> None:
        partial = {"locations": [{"file": "case.py", "line": 3, "externally_controlled": True}]}
        item = self._run(security_evidence=partial)["algorithms"][0]
        self.assertEqual("performance", item["category"])
        complete = {"locations": [{"file": "case.py", "line": 3, "externally_controlled": True, "attack_amplifiable": True}]}
        item = self._run(security_evidence=complete)["algorithms"][0]
        self.assertEqual("security-risk", item["status"])
        self.assertEqual("security", item["category"])

    def test_profiling_adds_evidence_without_changing_permission(self) -> None:
        profiling = {"locations": [{"file": "case.py", "line": 3, "hot": True, "samples": 1200}]}
        item = self._run(profiling_evidence=profiling)["algorithms"][0]
        self.assertTrue(any(evidence["kind"] == "profiling" for evidence in item["evidence"]))
        self.assertEqual("ASSISTED", item["recommendation"]["correction_level"])


if __name__ == "__main__":
    unittest.main()

