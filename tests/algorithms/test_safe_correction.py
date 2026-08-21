from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "skill" / "programming-best-practices" / "scripts"
PACKAGE = SCRIPTS / "algorithms"
SPEC = importlib.util.spec_from_file_location("pbp_algorithm_safe", PACKAGE / "__init__.py", submodule_search_locations=[str(PACKAGE)])
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class SafeCorrectionTests(unittest.TestCase):
    def analyze(self, expression: str, prefix: str = "") -> dict:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.py").write_text(f"{prefix}def f():\n    return {expression}\n", encoding="utf-8")
            result = MODULE.analyze_repository(root)
        return next(item for item in result["algorithms"] if item["rule_id"] == "pbp.algorithm.sort.full-sort-for-extreme")

    def test_nonempty_homogeneous_primitive_literals_get_a_verified_safe_patch(self) -> None:
        for expression in ("sorted([3, 1, 2, 1])[0]", "sorted([3.5, -1.0, 2.0])[-1]", "sorted(['b', 'a', 'a'])[0]"):
            with self.subTest(expression=expression):
                item = self.analyze(expression)
                self.assertEqual("SAFE", item["recommendation"]["correction_level"])
                self.assertTrue(all(req["state"] == "PROVEN" for req in item["requirements"] if req["hard"]))
                replacement = item["recommendation"]["patch"]["replacement"]
                self.assertEqual(eval(expression, {"__builtins__": {"sorted": sorted}}), eval(replacement, {"__builtins__": {"min": min, "max": max}}))

    def test_unknown_or_contradicted_hard_requirements_never_get_safe(self) -> None:
        variable = self.analyze("sorted(values)[0]", prefix="values = [3, 1]\n")
        empty = self.analyze("sorted([])[0]")
        shadowed = self.analyze("sorted([3, 1])[0]", prefix="sorted = lambda value: value\n")
        self.assertEqual({"ASSISTED"}, {item["recommendation"]["correction_level"] for item in (variable, empty, shadowed)})
        self.assertTrue(all(any(req["hard"] and req["state"] == "UNKNOWN" for req in item["requirements"]) for item in (variable, empty, shadowed)))


if __name__ == "__main__":
    unittest.main()
