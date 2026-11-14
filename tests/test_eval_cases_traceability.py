"""`evals/cases.json` no tiene runner: son prompts con expectativas en texto. Este test comprueba al menos que cada
expectativa se puede rastrear hasta la documentación de la skill (cada palabra, por raíz de 4 letras, aparece en SKILL.md o en
sus referencias). No prueba el comportamiento del agente, solo que lo esperado está escrito en algún sitio."""

from __future__ import annotations

import json
import re
import unittest

from tests.helpers import ROOT, SKILL

STOP = {"and", "of", "the", "skill", "should", "not", "trigger"}


class EvalCaseTraceability(unittest.TestCase):
    def test_every_expectation_is_documented(self) -> None:
        corpus = " ".join(
            path.read_text(encoding="utf-8", errors="ignore").lower()
            for path in [SKILL / "SKILL.md", *SKILL.glob("references/**/*.md")]
        )
        cases = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))["cases"]
        missing = []
        for case in cases:
            for expectation in case["expected"]:
                for word in re.findall(r"[a-z]+", expectation.lower()):
                    if word not in STOP and word[:4] not in corpus:
                        missing.append((case["name"], expectation, word))
        self.assertEqual([], missing)

    def test_cases_cover_the_documented_modes(self) -> None:
        names = {case["name"] for case in json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))["cases"]}
        self.assertTrue({"audit-default-read-only", "authorized-refactor", "negative-trigger"} <= names)


if __name__ == "__main__":
    unittest.main()
