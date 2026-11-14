"""Enumeración de ficheros fuente que respeta `.gitignore` y poda directorios excluidos.

`Path.rglob("*")` recorre `node_modules/`, `.venv/` y los worktrees de agentes (`.trabajo/`) ANTES de filtrar:
en un monorrepo la auditoría moría por tiempo (design-patterns agotó 300 s en karajan) y luego el informe
descartaba como «generado» lo que el analizador había tardado minutos en leer. Aquí se poda al bajar y,
si la raíz es un repo git, se aplica además lo que el propio repo declara ignorado.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _git_visible(root: Path) -> set[str] | None:
    """Rutas (posix, relativas a `root`) rastreadas o sin rastrear pero no ignoradas; `None` si no hay git."""
    try:
        done = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True, timeout=60, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return {item.decode("utf-8", "replace") for item in done.stdout.split(b"\0") if item}


def project_files(root: Path, excluded_dirs: set[str] | frozenset[str]) -> list[Path]:
    """Ficheros bajo `root`, ordenados, sin directorios excluidos ni rutas ignoradas por git."""
    root = Path(root)
    visible = _git_visible(root)
    found: list[Path] = []
    for current, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in excluded_dirs)
        base = Path(current)
        for name in sorted(names):
            path = base / name
            if visible is not None and path.relative_to(root).as_posix() not in visible:
                continue
            found.append(path)
    return sorted(found)
