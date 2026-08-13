from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.helpers import ROOT, load_module

installer = load_module("install_skill", ROOT / "tools" / "install_skill.py")


class InstallSkillTests(unittest.TestCase):
    def test_preview_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            destination, backup = installer.install(installer.source_skill(), target, apply=False, force=False)
            self.assertFalse(destination.exists())
            self.assertIsNone(backup)

    def test_install_refuses_overwrite_and_force_creates_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            destination, _ = installer.install(installer.source_skill(), target, apply=True, force=False)
            self.assertTrue((destination / "SKILL.md").is_file())
            with self.assertRaises(FileExistsError):
                installer.install(installer.source_skill(), target, apply=True, force=False)
            new_destination, backup = installer.install(installer.source_skill(), target, apply=True, force=True)
            self.assertEqual(destination, new_destination)
            self.assertIsNotNone(backup)
            self.assertTrue((backup / "SKILL.md").is_file())

    def test_rejects_overlapping_source_and_destination(self) -> None:
        source = installer.source_skill()
        with self.assertRaises(ValueError):
            installer.install(source, source.parent, apply=False, force=True)


if __name__ == "__main__":
    unittest.main()

