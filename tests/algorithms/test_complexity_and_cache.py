from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "skill" / "programming-best-practices" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from algorithms import analyze_repository


class ComplexityAndCacheTests(unittest.TestCase):
    def _complexity(self, source: str, function: str = "f") -> dict:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "case.py").write_text(source, encoding="utf-8")
            artifact = analyze_repository(root, use_cache=False)
        return next(item for item in artifact["analysis"]["units"][0]["functions"] if item["name"] == function)["complexity"]

    def test_required_structural_complexity_forms(self) -> None:
        self.assertEqual("O(n)", self._complexity("def f(xs):\n    for x in xs:\n        print(x)\n")["worst"])
        self.assertEqual("O(n*m)", self._complexity("def f(xs, ys):\n    for x in xs:\n        for y in ys:\n            print(x,y)\n")["worst"])
        self.assertEqual("O(n+m)", self._complexity("def f(xs, ys):\n    for x in xs: print(x)\n    for y in ys: print(y)\n")["worst"])
        self.assertEqual("O(log n)", self._complexity("def f(n):\n    while n > 1:\n        n //= 2\n")["worst"])
        sort = self._complexity("def f(xs):\n    return sorted(xs)\n")
        self.assertEqual("O(n log n)", sort["average"])
        self.assertEqual("implementation-dependent", sort["worst"])

    def test_cache_is_external_content_addressed_and_hits_on_second_run(self) -> None:
        with tempfile.TemporaryDirectory() as project, tempfile.TemporaryDirectory() as cache:
            root, cache_root = Path(project), Path(cache)
            (root / "case.py").write_text("def f(xs):\n    return min(xs)\n", encoding="utf-8")
            first = analyze_repository(root, cache_dir=cache_root)
            second = analyze_repository(root, cache_dir=cache_root)
        self.assertEqual(1, first["analysis"]["cache"]["misses"])
        self.assertEqual(1, second["analysis"]["cache"]["hits"])
        self.assertFalse(str(cache_root).startswith(str(root)))

    def test_catalog_mappings_extend_recognition_without_engine_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "case.py").write_text("def f(xs):\n    return min(xs)\n", encoding="utf-8")
            artifact = analyze_repository(root, use_cache=False)
        recognized = {(item["algorithm_id"], item["rule_id"]) for item in artifact["algorithms"]}
        self.assertIn(("selection.min", "pbp.algorithm.catalog-api.recognized"), recognized)


if __name__ == "__main__":
    unittest.main()

