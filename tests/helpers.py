from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skill" / "programming-best-practices"


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def scripts_on_path() -> None:
    """Puts `skill/programming-best-practices/scripts` on sys.path so the
    `design_patterns` package (which uses real relative imports, unlike the
    flat sibling scripts `load_module` is for) can be imported normally:
    `import design_patterns.ir`.
    """
    scripts_dir = str(SKILL / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

