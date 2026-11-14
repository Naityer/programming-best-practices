from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import SKILL, load_module

sys.path.insert(0, str(SKILL / "scripts"))
structure = load_module("analyze_structure_t", SKILL / "scripts" / "analyze_structure.py")
normalize = load_module("normalize_structure_t", SKILL / "scripts" / "normalize_tool_output.py")

BIG_PY = """
def decide(a, b, c, d, e, f, g, h):
    if a:
        if b:
            if c:
                if d:
                    if e:
                        if f:
                            return 1
    for x in a:
        if x and b or c:
            pass
    try:
        pass
    except Exception:
        pass
    return 0
"""


class StructureTests(unittest.TestCase):
    def _run(self, files: dict[str, str], **override):
        limits = dict(structure.DEFAULTS, **override)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for rel, text in files.items():
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text(text, encoding="utf-8")
            return structure.analyze(root, limits)

    def test_python_metrics_are_reported_with_lines(self) -> None:
        result = self._run({"m.py": BIG_PY}, complexity=5, nesting=3)
        rules = {i["rule_id"].rsplit(".", 1)[-1] for i in result["items"]}
        self.assertTrue({"cyclomatic-complexity", "parameters", "nesting", "swallowed-exception"} <= rules, rules)
        self.assertTrue(all(i["line"] >= 1 for i in result["items"]))

    def test_clean_code_and_vendored_dirs_produce_nothing(self) -> None:
        result = self._run({"ok.py": "def f(x):\n    return x\n", "node_modules/a/b.js": "try{}catch(e){}\n"})
        self.assertEqual([], result["items"])
        self.assertEqual(1, result["files_analyzed"])

    def test_js_file_size_empty_catch_and_fan_out(self) -> None:
        imports = "".join(f"import a{i} from 'mod{i}';\n" for i in range(4))
        result = self._run({"a.ts": imports + "try { f() } catch (e) {}\n"}, file_lines=3, imports=3)
        rules = {i["rule_id"].rsplit(".", 1)[-1] for i in result["items"]}
        self.assertEqual({"file-size", "fan-out", "swallowed-exception"}, rules)

    def test_normalizer_turns_items_into_reviewable_findings(self) -> None:
        result = self._run({"m.py": BIG_PY}, complexity=5)
        findings, dimensions, limitations = normalize.parse_structure(result, None)
        self.assertEqual(len(result["items"]), len(findings))
        self.assertTrue(all(f["severity"] in {"low", "medium"} and f["confidence"] in {"low", "medium"} for f in findings))
        self.assertIn("structure", dimensions)
        self.assertTrue(limitations)


if __name__ == "__main__":
    unittest.main()


class GeneratedFilesTests(unittest.TestCase):
    def test_bundles_and_compiled_siblings_are_not_measured(self) -> None:
        limits = dict(structure.DEFAULTS, file_lines=3)
        big = "x = 1;\n" * 10
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for rel, text in {
                "dist-atlas/server.mjs": big, "src/a.ts": big, "src/a.js": big,
                "src/gen.js": "// @generated\n" + big, "src/own.ts": big,
            }.items():
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text(text, encoding="utf-8")
            result = structure.analyze(root, limits)
        self.assertEqual({"src/a.ts", "src/own.ts"}, {i["file"] for i in result["items"]})
