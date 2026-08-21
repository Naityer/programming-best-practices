from __future__ import annotations

import unittest

from tests.helpers import scripts_on_path

scripts_on_path()

from design_patterns.catalog import load_catalog, validate_catalog  # noqa: E402


class CatalogTests(unittest.TestCase):
    def test_loads_all_22_gof_patterns(self) -> None:
        catalog = load_catalog()
        self.assertEqual(22, len(catalog))

    def test_every_conflicts_with_reference_exists(self) -> None:
        catalog = load_catalog()
        ids = set(catalog.ids())
        for spec in catalog:
            for conflict in spec.conflicts_with:
                self.assertIn(conflict, ids, f"{spec.id} conflicts_with unknown pattern {conflict!r}")

    def test_conflicts_with_is_declared_symmetrically_for_the_key_lookalike_trios(self) -> None:
        catalog = load_catalog()
        adapter, decorator, proxy = catalog.get("adapter"), catalog.get("decorator"), catalog.get("proxy")
        self.assertIn("decorator", adapter.conflicts_with)
        self.assertIn("proxy", adapter.conflicts_with)
        self.assertIn("adapter", decorator.conflicts_with)
        self.assertIn("adapter", proxy.conflicts_with)
        state, strategy = catalog.get("state"), catalog.get("strategy")
        self.assertIn("state", strategy.conflicts_with)
        self.assertIn("strategy", state.conflicts_with)

    def test_get_returns_none_for_unknown_id(self) -> None:
        self.assertIsNone(load_catalog().get("not-a-real-pattern"))

    def test_validate_catalog_rejects_missing_required_field(self) -> None:
        errors = validate_catalog({
            "schema_version": "1.0.0",
            "patterns": [{"id": "x", "name": "X", "family": "structural", "conflicts_with": []}],
        })
        self.assertTrue(any("roles" in e for e in errors))

    def test_validate_catalog_rejects_bad_family(self) -> None:
        errors = validate_catalog({
            "schema_version": "1.0.0",
            "patterns": [{
                "id": "x", "name": "X", "family": "nonsense",
                "roles": ["a"], "required_relations": [], "conflicts_with": [],
            }],
        })
        self.assertTrue(any("family" in e for e in errors))

    def test_validate_catalog_rejects_duplicate_id(self) -> None:
        pattern = {
            "id": "x", "name": "X", "family": "structural",
            "roles": ["a"], "required_relations": [], "conflicts_with": [],
        }
        errors = validate_catalog({"schema_version": "1.0.0", "patterns": [pattern, dict(pattern)]})
        self.assertTrue(any("duplicate id" in e for e in errors))

    def test_validate_catalog_rejects_conflicts_with_pointing_nowhere(self) -> None:
        errors = validate_catalog({
            "schema_version": "1.0.0",
            "patterns": [{
                "id": "x", "name": "X", "family": "structural",
                "roles": ["a"], "required_relations": [], "conflicts_with": ["ghost"],
            }],
        })
        self.assertTrue(any("unknown pattern id" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
