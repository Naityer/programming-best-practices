import tempfile
import unittest
from pathlib import Path

from tests.helpers import SKILL, load_module, scripts_on_path


scripts_on_path()
analyzer = load_module(
    "analyze_design_patterns_language_scope",
    SKILL / "scripts" / "analyze_design_patterns.py",
)


class LanguageScopeTests(unittest.TestCase):
    def test_non_python_sources_are_reported_instead_of_silently_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.ts").write_text("export class Service {}\n", encoding="utf-8")
            (root / "Main.java").write_text("class Main {}\n", encoding="utf-8")

            result = analyzer.analyze(root)

            self.assertEqual(0, result.files_scanned)
            self.assertEqual([], result.languages)
            self.assertTrue(any("TypeScript" in item and "1 source" in item for item in result.limitations))
            self.assertTrue(any("Java" in item and "1 source" in item for item in result.limitations))

    def test_excluded_dependency_sources_do_not_create_limitations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dependency = root / "node_modules" / "pkg"
            dependency.mkdir(parents=True)
            (dependency / "index.ts").write_text("export const x = 1;\n", encoding="utf-8")

            result = analyzer.analyze(root)

            self.assertEqual([], result.limitations)


if __name__ == "__main__":
    unittest.main()
