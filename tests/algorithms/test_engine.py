from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "skill" / "programming-best-practices" / "scripts"
sys.path.insert(0, str(SCRIPTS))

package_dir = SCRIPTS / "algorithms"
spec = importlib.util.spec_from_file_location(
    "pbp_algorithm_intelligence", package_dir / "__init__.py",
    submodule_search_locations=[str(package_dir)],
)
assert spec and spec.loader
algorithm_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = algorithm_module
spec.loader.exec_module(algorithm_module)
analyze_repository = algorithm_module.analyze_repository
from normalize_tool_output import parse_algorithms


class AlgorithmEngineTests(unittest.TestCase):
    def test_full_sort_for_min_is_assisted_not_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.py").write_text("def f(xs):\n    return sorted(xs)[0]\n", encoding="utf-8")
            result = analyze_repository(root)
        item = result["algorithms"][0]
        self.assertEqual("suboptimal", item["status"])
        self.assertEqual("ASSISTED", item["recommendation"]["correction_level"])
        self.assertTrue(any(req["hard"] and req["state"] == "UNKNOWN" for req in item["requirements"]))

    def test_lexical_frontend_never_authorizes_correction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Sample.java").write_text("class Sample { void f() { Collections.sort(xs); } }", encoding="utf-8")
            result = analyze_repository(root)
        self.assertEqual("recognized", result["algorithms"][0]["status"])
        self.assertIsNone(result["algorithms"][0]["recommendation"])
        self.assertEqual("UNKNOWN", result["algorithms"][0]["requirements"][0]["state"])

    def test_normalizer_emits_only_actionable_states(self):
        data = {
            "algorithms": [
                {"id": "one", "algorithm_id": "x", "rule_id": "pbp.algorithm.x", "family": "search", "status": "recognized", "confidence": "low", "primary_location": {"file": "a.py", "line": 1}},
                {"id": "two", "algorithm_id": "y", "rule_id": "pbp.algorithm.y", "family": "selection", "status": "suboptimal", "confidence": "high", "primary_location": {"file": "b.py", "line": 2}, "complexity": {"current": {"time": "O(n log n)"}, "expected": {"time": "O(n)"}}, "evidence": [{"description": "fact"}], "recommendation": {"summary": "change", "correction_level": "ASSISTED"}},
            ]
        }
        findings, dimensions, _ = parse_algorithms(data, None)
        self.assertEqual(1, len(findings))
        self.assertEqual("pbp.algorithm.y", findings[0]["rule_id"])
        self.assertEqual(2, len(dimensions["algorithms"]["occurrences"]))


if __name__ == "__main__":
    unittest.main()
