#!/usr/bin/env python3
"""Audita en una COPIA DESECHABLE: permite ejecutar build, tests y cobertura sin escribir en el repositorio real.

El proyecto original solo se lee. Se copian los ficheros que git ve (rastreados + sin rastrear no ignorados; sin git,
todo menos directorios excluidos) y, con `--copy-deps`, los directorios de dependencias (`node_modules`, `.venv`) que
los tests necesitan. Después se planifica y ejecuta con `--allow-project-writes` SOLO dentro de la copia (nunca red ni
código generado salvo que se pidan) y se construye el informe y `verdict.json` en `--output-dir`.

Límite: los tests pueden tocar recursos externos al repo (puertos, bases de datos fuera de la carpeta, servicios);
la copia no los aísla. Revisa los scripts de test antes de usarlo sobre un proyecto desconocido.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from analysis_core.files import project_files  # noqa: E402

PRUNE = {".git", ".quality-audit", ".trabajo", "__pycache__"}
DEPS = ("node_modules", ".venv", "venv")


def _long(path: Path) -> str:
    """Prefijo largo en Windows: node_modules supera los 260 caracteres de ruta."""
    text = str(path.resolve())
    prefix = chr(92) * 2 + "?" + chr(92)
    return prefix + text if os.name == "nt" and not text.startswith(prefix) else text


def _dependency_dirs(root: Path, max_depth: int = 3) -> list[Path]:
    """`node_modules`/`.venv` del proyecto y de sus subpaquetes (sin entrar en ellos ni en .git/.trabajo)."""
    found: list[Path] = []
    for current, dirs, _ in os.walk(root):
        depth = len(Path(current).relative_to(root).parts)
        keep = []
        for name in dirs:
            if name in DEPS:
                found.append(Path(current) / name)
            elif name not in PRUNE and depth < max_depth:
                keep.append(name)
        dirs[:] = keep
    return sorted(found)


def copy_project(root: Path, destination: Path, *, copy_deps: bool = False, max_file_mb: int = 50) -> dict:
    """Copia los ficheros visibles del proyecto. Devuelve recuento y omisiones."""
    copied = skipped_big = 0
    for path in project_files(root, PRUNE | set(DEPS)):
        if path.stat().st_size > max_file_mb * 1024 * 1024:
            skipped_big += 1
            continue
        target = destination / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied += 1
    deps = []
    if copy_deps:
        for source in _dependency_dirs(root):
            relative = source.relative_to(root)
            shutil.copytree(_long(source), _long(destination / relative), symlinks=True, ignore_dangling_symlinks=True)
            deps.append(relative.as_posix())
    return {"files": copied, "skipped_over_limit": skipped_big, "deps": deps}


def _init_git(copy: Path) -> None:
    """Repositorio git propio de la copia (los tests de flujos git lo necesitan; no toca el original)."""
    for command in (["init", "-q"], ["add", "-A"], ["-c", "user.name=pbp", "-c", "user.email=pbp@invalid", "commit", "-qm", "copia de auditoría", "--no-gpg-sign"]):
        subprocess.run(["git", "-C", str(copy), *command], capture_output=True, timeout=300)


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], capture_output=True, text=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audita una copia desechable del proyecto (el original no se modifica).")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True, help="Directorio NUEVO fuera del proyecto (copia + salidas)")
    parser.add_argument("--profile", choices=["fast", "standard", "deep"], default="standard")
    parser.add_argument("--copy-deps", action="store_true", help="Copia también node_modules/.venv")
    parser.add_argument("--allow-network", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    workdir = args.workdir.resolve()
    if workdir == root or root in workdir.parents:
        print("--workdir debe estar fuera del proyecto", file=sys.stderr)
        return 2
    if workdir.exists() and any(workdir.iterdir()):
        print(f"--workdir ya existe y no está vacío: {workdir}", file=sys.stderr)
        return 2
    copy = workdir / "copy" / root.name
    copy.mkdir(parents=True)
    summary = copy_project(root, copy, copy_deps=args.copy_deps)
    _init_git(copy)
    plan = workdir / "plan.json"
    steps = [
        ["plan_audit.py", "--root", str(copy), "--profile", args.profile, "--scope", "repository", "--output", str(plan)],
        ["run_audit.py", str(plan), "--output-dir", str(workdir / "execution"), "--execute", "--allow-project-writes",
         *(["--allow-network"] if args.allow_network else [])],
    ]
    for step in steps:
        done = _run([str(SCRIPTS / step[0]), *step[1:]])
        if done.returncode not in (0, 1):  # run_audit usa 1 cuando hay hallazgos/fallos de checks
            print(done.stderr or done.stdout, file=sys.stderr)
            return 2
    report_dir = workdir / "report"
    done = _run([str(SCRIPTS / "build_report.py"), str(workdir / "execution" / "execution.json"), "--output-dir", str(report_dir)])
    if done.returncode != 0:
        print(done.stderr, file=sys.stderr)
        return 2
    _run([str(SCRIPTS / "export_verdict.py"), str(report_dir)])
    print(json.dumps({"copy": summary, "report": str(report_dir), "original_modified": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
