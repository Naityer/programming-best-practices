from __future__ import annotations

import json
import unittest

from tests.helpers import ROOT, SKILL


class ContractTests(unittest.TestCase):
    def test_skill_has_only_supported_frontmatter_fields(self) -> None:
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        frontmatter = text.split("---", 2)[1]
        keys = {line.split(":", 1)[0] for line in frontmatter.splitlines() if ":" in line}
        self.assertEqual({"name", "description"}, keys)
        self.assertLess(len(text.splitlines()), 500)

    def test_openai_metadata_matches_skill(self) -> None:
        text = (SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn('display_name: "Programming Best Practices"', text)
        self.assertIn("$programming-best-practices", text)
        self.assertIn("Audita y mejora la calidad del código", text)

    def test_references_are_direct_and_present(self) -> None:
        skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        expected = {
            "core-principles.md", "code-quality.md", "testing.md", "security.md", "automation.md",
            "profiles.md", "tooling-matrix.md", "reporting.md", "audit-result.schema.json",
            "performance.md",
        }
        self.assertEqual(expected, {path.name for path in (SKILL / "references").iterdir()})
        for name in expected:
            self.assertIn(name, skill_text)

    def test_json_contracts_are_parseable(self) -> None:
        schema = json.loads((SKILL / "references" / "audit-result.schema.json").read_text(encoding="utf-8"))
        evals = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))
        fixtures = json.loads((ROOT / "tests" / "fixtures" / "stack-manifests.json").read_text(encoding="utf-8"))
        self.assertEqual("object", schema["type"])
        self.assertFalse(schema["properties"]["summary"]["additionalProperties"])
        self.assertEqual(6, len(evals["cases"]))
        self.assertEqual(7, len(fixtures["cases"]))


if __name__ == "__main__":
    unittest.main()



