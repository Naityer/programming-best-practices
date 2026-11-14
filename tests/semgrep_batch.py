"""Ejecuta semgrep UNA vez sobre muchos fragmentos de código: arrancarlo cuesta unos 3 s, y con un arranque por caso la suite tardaba minutos."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path

AVAILABLE = shutil.which("semgrep") is not None


def scan(rules: Path, cases: dict[str, tuple[str, str]]) -> dict[str, set[str]]:
    """`cases`: nombre → (ruta relativa del fichero, código). Devuelve, por caso, los ids cortos de las reglas que saltaron.

    Cada caso va en su propia carpeta, así que las reglas con `paths` (excluir tests, solo Dockerfile…) ven la ruta relativa que se les da."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        folders: dict[str, str] = {}
        for index, (name, (relative, source)) in enumerate(cases.items()):
            folder = f"c{index:03d}"
            folders[folder] = name
            target = root / folder / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(textwrap.dedent(source), encoding="utf-8")
        done = subprocess.run(
            ["semgrep", "scan", "--metrics=off", "--quiet", "--disable-version-check", "--json", "--config", str(rules), str(root)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300, cwd=directory, env={**os.environ, "PYTHONUTF8": "1"},
        )
        found: dict[str, set[str]] = {name: set() for name in cases}
        for item in json.loads(done.stdout)["results"]:
            folder = Path(item["path"]).as_posix().replace(root.as_posix() + "/", "").split("/")[0]
            if folder in folders:
                found[folders[folder]].add(item["check_id"].rsplit(".", 1)[-1])
        return found
