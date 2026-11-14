from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import SKILL, load_module

sys.path.insert(0, str(SKILL / "scripts"))
structure = load_module("analyze_structure_extra_t", SKILL / "scripts" / "analyze_structure.py")


class DuplicationAndCycles(unittest.TestCase):
    def test_duplicate_blocks_and_cycles_are_found(self) -> None:
        block = "".join(f"value_{i} = compute_something({i}) + other\n" for i in range(15))
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "pkg").mkdir()
            (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
            (root / "pkg" / "a.py").write_text("from pkg import b\n" + block, encoding="utf-8")
            (root / "pkg" / "b.py").write_text("from pkg import a\n" + block, encoding="utf-8")
            (root / "x.ts").write_text("import { y } from './y';\n", encoding="utf-8")
            (root / "y.ts").write_text("import { x } from './x';\n", encoding="utf-8")
            (root / "z.ts").write_text("import { x } from './x';\n", encoding="utf-8")
            result = structure.analyze(root, dict(structure.DEFAULTS))
        rules = [i["rule_id"].rsplit(".", 1)[-1] for i in result["items"]]
        self.assertEqual(1, rules.count("duplication"))
        self.assertEqual(2, rules.count("import-cycle"))  # pkg.a<->pkg.b y x<->y; z no participa

    def test_short_repeated_lines_are_not_duplication(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            for name in ("a.py", "b.py"):
                (Path(d) / name).write_text("x = 1\n" * 40, encoding="utf-8")
            result = structure.analyze(Path(d), dict(structure.DEFAULTS))
        self.assertEqual([], result["items"])

    def test_acyclic_graph_has_no_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a.py").write_text("import b\n", encoding="utf-8")
            (Path(d) / "b.py").write_text("x = 1\n", encoding="utf-8")
            result = structure.analyze(Path(d), dict(structure.DEFAULTS))
        self.assertEqual([], [i for i in result["items"] if "cycle" in i["rule_id"]])


if __name__ == "__main__":
    unittest.main()
