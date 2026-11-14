"""External, content-addressed cache for per-file algorithm analysis."""

from __future__ import annotations

import hashlib
import json
import os
import platform
from importlib.metadata import PackageNotFoundError, version
import tempfile
from pathlib import Path
from typing import Any

# Se sube con CUALQUIER cambio en lo que detectan los analizadores: la caché está en el disco del usuario y se indexa por esta versión y por el
# contenido del fichero, así que sin subirla se seguirían sirviendo los resultados del detector anterior hasta que el fichero cambiase.
ENGINE_VERSION = "0.5.0"


def frontend_fingerprint(language: str) -> str:
    if language == "python":
        return f"python-ast-{platform.python_version()}"
    try:
        tree_sitter_version = version("tree-sitter")
        language_pack_version = version("tree-sitter-language-pack")
    except PackageNotFoundError:
        return "tree-sitter-unavailable"
    return f"tree-sitter-{tree_sitter_version}-language-pack-{language_pack_version}"

def default_cache_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
    return base / "programming-best-practices" / "algorithm-ir-cache"


class FileAnalysisCache:
    def __init__(self, root: Path | None, *, enabled: bool = True) -> None:
        self.root = (root or default_cache_dir()).resolve()
        self.enabled = enabled
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key(language: str, text: str) -> str:
        payload = f"{ENGINE_VERSION}\0{language}\0{text}".encode("utf-8", errors="replace")
        return hashlib.sha256(payload).hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        if not self.enabled:
            self.misses += 1
            return None
        path = self.root / f"{key}.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            self.misses += 1
            return None
        self.hits += 1
        return value

    def put(self, key: str, value: dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            target = self.root / f"{key}.json"
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False), encoding="utf-8")
            temporary.replace(target)
        except OSError:
            # Caching is an optimization and must never make analysis fail.
            return

    def summary(self) -> dict[str, Any]:
        return {
            "engine_version": ENGINE_VERSION,
            "enabled": self.enabled,
            "hits": self.hits,
            "misses": self.misses,
            "location": str(self.root) if self.enabled else None,
            "outside_project_required": True,
        }

