from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

SCRIPTS = Path(__file__).resolve().parents[2] / "skill" / "programming-best-practices" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from algorithms import analyze_repository


class UniversalIRTests(unittest.TestCase):
    def test_python_materializes_cfg_dfg_operation_index_and_complexity(self) -> None:
        source = """def f(xs, ys):
    out = []
    for x in xs:
        for y in ys:
            if x.id == y.id:
                out.append((x, y))
    return out
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.py").write_text(source, encoding="utf-8")
            artifact = analyze_repository(root, use_cache=False)
        analysis = artifact["analysis"]
        self.assertGreater(analysis["metrics"]["cfg_nodes"], 0)
        self.assertGreater(analysis["metrics"]["data_flow_facts"], 0)
        self.assertIn("iterate", analysis["operation_index"])
        function = next(item for item in analysis["units"][0]["functions"] if item["name"] == "f")
        self.assertEqual("O(n*m)", function["complexity"]["worst"])

    def test_standard_propagates_direct_callee_and_deep_propagates_multi_hop(self) -> None:
        source = """def contains(xs, value):
    return value in xs

def wrapper(xs, value):
    return contains(xs, value)

def direct(xs, queries):
    for query in queries:
        if contains(xs, query):
            pass

def indirect(xs, queries):
    for query in queries:
        if wrapper(xs, query):
            pass
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.py").write_text(source, encoding="utf-8")
            standard = analyze_repository(root, profile="standard", use_cache=False)
            deep = analyze_repository(root, profile="deep", use_cache=False)
        rule = "pbp.algorithm.search.repeated-linear-membership"
        standard_names = {item["primary_location"].get("qualified_name") for item in standard["algorithms"] if item["rule_id"] == rule}
        deep_names = {item["primary_location"].get("qualified_name") for item in deep["algorithms"] if item["rule_id"] == rule}
        self.assertIn("direct", standard_names)
        self.assertNotIn("indirect", standard_names)
        self.assertIn("indirect", deep_names)

    def test_fast_omits_costly_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = analyze_repository(Path(directory), profile="fast")
        self.assertEqual([], result["algorithms"])
        self.assertEqual(0, result["files_scanned"])


if __name__ == "__main__":
    unittest.main()

