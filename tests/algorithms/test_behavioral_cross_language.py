from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "skill" / "programming-best-practices" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from algorithms import analyze_repository


class BehavioralCrossLanguageTests(unittest.TestCase):
    def test_repeated_membership_has_one_problem_signature_in_seven_ecosystems(self) -> None:
        fixtures = {
            "case.py": "def f(available, requested):\n    for item in requested:\n        if item in available:\n            print(item)\n",
            "Case.java": "class Case { void f(java.util.List<Integer> available, java.util.List<Integer> requested) { for (int item : requested) { if (available.contains(item)) System.out.println(item); } } }",
            "case.ts": "function f(available: number[], requested: number[]) { for (const item of requested) { if (available.includes(item)) console.log(item); } }",
            "Case.cs": "class Case { void F(List<int> available, List<int> requested) { foreach (var item in requested) { if (available.Contains(item)) Console.WriteLine(item); } } }",
            "case.go": "package main\nimport \"slices\"\nfunc f(available, requested []int) { for _, item := range requested { if slices.Contains(available, item) { println(item) } } }",
            "case.rs": "fn f(available: &[i32], requested: &[i32]) { for item in requested { if available.contains(item) { println!(\"{}\", item); } } }",
            "case.cpp": "#include <algorithm>\n#include <vector>\nvoid f(std::vector<int> available, std::vector<int> requested) { for (int item : requested) { if (std::find(available.begin(), available.end(), item) != available.end()) {} } }",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, source in fixtures.items():
                (root / name).write_text(source, encoding="utf-8")
            artifact = analyze_repository(root, use_cache=False)
        rule = "pbp.algorithm.search.repeated-linear-membership"
        findings = [item for item in artifact["algorithms"] if item["rule_id"] == rule]
        self.assertEqual(set(fixtures), {item["primary_location"]["file"] for item in findings})
        self.assertEqual({"repeated-membership"}, {item["problem_signature"]["problem"] for item in findings})
        for item in findings:
            self.assertEqual("ASSISTED", item["recommendation"]["correction_level"])
            self.assertTrue(any(req["hard"] and req["state"] == "UNKNOWN" for req in item["requirements"]))


if __name__ == "__main__":
    unittest.main()

