from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "skill" / "programming-best-practices" / "scripts"
_SPEC = importlib.util.spec_from_file_location("pbp_algorithm_advisor_test", SCRIPTS / "algorithms" / "advisor.py")
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("cannot load advisor")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
rank_alternatives = _MODULE.rank_alternatives


class AdvisorRankingTests(unittest.TestCase):
    def test_big_o_never_overrides_exactness_order_or_determinism(self) -> None:
        candidates = [
            {"algorithm_id": "approx.fast", "hard_requirements": {"exactness": "approximate"}, "time_rank": 10, "simplicity": 1},
            {"algorithm_id": "exact.stable", "hard_requirements": {"exactness": "exact", "ordering": "preserved", "determinism": True}, "time_rank": 3, "simplicity": 2},
        ]
        ranked = rank_alternatives(
            {"problem": "cardinality", "properties": {}}, candidates,
            {"exactness": "exact", "ordering": "preserved", "determinism": True, "input_size": 1000},
        )
        self.assertEqual("exact.stable", ranked[0]["algorithm_id"])
        rejected = next(item for item in ranked if item["algorithm_id"] == "approx.fast")
        self.assertFalse(rejected["eligible"])
        self.assertEqual("CONTRADICTED", rejected["requirements"][0]["state"])

    def test_missing_memory_fact_rejects_candidate_instead_of_guessing(self) -> None:
        ranked = rank_alternatives(
            {"problem": "membership", "properties": {}},
            [{"algorithm_id": "hash", "hard_requirements": {"memory": "extra-ok"}, "time_rank": 8}],
            {"input_size": 1000},
        )
        self.assertFalse(ranked[0]["eligible"])
        self.assertEqual("UNKNOWN", ranked[0]["requirements"][0]["state"])

    def test_tiny_inputs_prefer_the_simpler_adequate_candidate(self) -> None:
        candidates = [
            {"algorithm_id": "linear", "hard_requirements": {}, "time_rank": 1, "simplicity": 3, "memory_cost": 0},
            {"algorithm_id": "hash", "hard_requirements": {}, "time_rank": 5, "simplicity": 0, "memory_cost": 2},
        ]
        ranked = rank_alternatives({"problem": "membership", "properties": {}}, candidates, {"input_size": 5})
        self.assertEqual("linear", ranked[0]["algorithm_id"])


if __name__ == "__main__":
    unittest.main()

