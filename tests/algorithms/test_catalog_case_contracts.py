from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "skill" / "programming-best-practices" / "references" / "algorithms" / "catalog.json"
CASES = ROOT / "evals" / "algorithms" / "catalog-case-contracts.json"
_KNOWLEDGE = ROOT / "skill" / "programming-best-practices" / "scripts" / "algorithms" / "knowledge.py"
_SPEC = importlib.util.spec_from_file_location("pbp_algorithm_knowledge_test", _KNOWLEDGE)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("cannot load catalog knowledge evaluator")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
evaluate_catalog_case = _MODULE.evaluate_catalog_case


class CatalogCaseContractTests(unittest.TestCase):
    def test_every_catalog_entry_has_all_five_atlas_case_classes(self) -> None:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        cases = json.loads(CASES.read_text(encoding="utf-8"))
        by_id = {item["algorithm_id"]: item for item in cases["algorithms"]}
        expected = {"positive", "negative", "misuse", "alternative", "edge"}
        self.assertGreaterEqual(len(catalog["algorithms"]), 100)
        self.assertEqual({item["id"] for item in catalog["algorithms"]}, set(by_id))
        for algorithm_id, item in by_id.items():
            with self.subTest(algorithm_id=algorithm_id):
                self.assertEqual(expected, {case["kind"] for case in item["cases"]})

    def test_all_catalog_contracts_execute_to_their_expected_state(self) -> None:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        contracts = json.loads(CASES.read_text(encoding="utf-8"))
        entries = {item["id"]: item for item in catalog["algorithms"]}
        executed = 0
        for group in contracts["algorithms"]:
            entry = entries[group["algorithm_id"]]
            for case in group["cases"]:
                with self.subTest(algorithm_id=entry["id"], kind=case["kind"]):
                    self.assertEqual(case["expected"], evaluate_catalog_case(entry, case))
                executed += 1
        self.assertEqual(len(entries) * 5, executed)
    def test_every_recipe_is_validation_gated_and_security_never_implements_crypto(self) -> None:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        for entry in catalog["algorithms"]:
            self.assertTrue(entry["recipes"], entry["id"])
            for recipe in entry["recipes"]:
                self.assertTrue(recipe.get("validation"), entry["id"])
            if entry["family"] == "security":
                strategies = " ".join(recipe["strategy"].lower() for recipe in entry["recipes"])
                self.assertIn("library", strategies)
                self.assertNotIn("implement aes", strategies)
                self.assertNotIn("implement rsa", strategies)


if __name__ == "__main__":
    unittest.main()

