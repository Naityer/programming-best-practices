from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import ROOT, SKILL, load_module

detect_project = load_module("detect_project", SKILL / "scripts" / "detect_project.py")


class DetectProjectTests(unittest.TestCase):
    def test_detects_every_supported_stack_fixture(self) -> None:
        manifest = json.loads((ROOT / "tests" / "fixtures" / "stack-manifests.json").read_text(encoding="utf-8"))
        for case in manifest["cases"]:
            with self.subTest(case=case["name"]), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for relative, content in case["files"].items():
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8")
                result = detect_project.detect(root)
                ecosystems = {item["name"] for item in result["ecosystems"]}
                languages = {item["name"] for item in result["languages"]}
                self.assertIn(case["ecosystem"], ecosystems)
                self.assertIn(case["language"], languages)
                self.assertEqual("repository", result["default_scope"]["type"])

    def test_detects_mixed_monorepo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {
                "api/pyproject.toml": "[project]\nname='api'\n",
                "api/main.py": "print('ok')\n",
                "web/package.json": '{"scripts":{"test":"jest"}}',
                "web/src/main.ts": "export {}",
                "service/go.mod": "module example.test\n",
                "service/main.go": "package main\n",
            }
            for relative, content in files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            result = detect_project.detect(root)
            self.assertEqual(
                {"python", "javascript-typescript", "go"},
                {item["name"] for item in result["ecosystems"]},
            )
            self.assertEqual(sorted(result["configurations"]), result["configurations"])

    @unittest.skipUnless(shutil.which("git"), "git is required")
    def test_changed_files_become_default_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            tracked = root / "app.py"
            tracked.write_text("value = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=root, check=True, capture_output=True)
            subprocess.run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "initial"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            tracked.write_text("value = 2\n", encoding="utf-8")
            result = detect_project.detect(root)
            self.assertEqual("changed-files", result["default_scope"]["type"])
            self.assertEqual(["app.py"], result["default_scope"]["files"])

    def test_ignores_dependency_and_build_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in ("node_modules/bad.ts", "target/Bad.java", ".venv/bad.py"):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("ignored", encoding="utf-8")
            result = detect_project.detect(root)
            self.assertEqual([], result["languages"])


if __name__ == "__main__":
    unittest.main()



class ProjectVirtualenvTests(unittest.TestCase):
    """El interprete del repositorio manda sobre el del PATH."""

    def test_a_project_virtualenv_wins_over_the_one_on_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
            (root / "app.py").write_text("value = 1\n", encoding="utf-8")
            # Un venv del proyecto, en el layout de la plataforma que toque.
            for relative in (Path(".venv") / "Scripts" / "python.exe", Path(".venv") / "bin" / "python"):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("", encoding="utf-8")

            inventory = detect_project.detect(root)
            command = inventory["tools"]["python"]["command"]
            self.assertTrue(
                Path(command).is_relative_to(root),
                f"deberia usar el venv del proyecto, no {command}",
            )

    def test_project_tools_win_over_a_different_project_on_path(self) -> None:
        """El caso que de verdad hace dano: auditar con las herramientas de OTRO repo."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
            (root / "app.py").write_text("value = 1\n", encoding="utf-8")
            scripts_dir = root / ".venv" / "Scripts"
            scripts_dir.mkdir(parents=True)
            bin_dir = root / ".venv" / "bin"
            bin_dir.mkdir(parents=True)
            for name in ("ruff", "mypy", "coverage", "pytest"):
                (scripts_dir / f"{name}.exe").write_text("", encoding="utf-8")
                (bin_dir / name).write_text("", encoding="utf-8")

            inventory = detect_project.detect(root)
            for name in ("ruff", "mypy", "coverage", "pytest"):
                entry = inventory["tools"][name]
                self.assertEqual(entry["status"], "available", name)
                self.assertTrue(
                    Path(entry["command"]).is_relative_to(root),
                    f"{name} deberia salir del proyecto, no de {entry['command']}",
                )

    def test_node_tools_are_taken_from_node_modules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text('{"scripts":{}}', encoding="utf-8")
            (root / "index.js").write_text("x=1\n", encoding="utf-8")
            node_bin = root / "node_modules" / ".bin"
            node_bin.mkdir(parents=True)
            (node_bin / "eslint.cmd").write_text("", encoding="utf-8")
            (node_bin / "eslint").write_text("", encoding="utf-8")

            entry = detect_project.detect(root)["tools"]["eslint"]
            self.assertEqual(entry["status"], "available")
            self.assertTrue(Path(entry["command"]).is_relative_to(root))

    def test_without_a_project_virtualenv_it_falls_back_to_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
            (root / "app.py").write_text("value = 1\n", encoding="utf-8")
            inventory = detect_project.detect(root)
            entry = inventory["tools"]["python"]
            # Hay un Python ejecutando este test, asi que debe encontrarlo.
            self.assertEqual(entry["status"], "available")
            self.assertFalse(Path(entry["command"]).is_relative_to(root))
