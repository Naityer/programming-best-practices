#!/usr/bin/env python3
"""Preview or install the distributable skill into a local skill directory."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

SKILL_NAME = "programming-best-practices"


def source_skill() -> Path:
    return (Path(__file__).resolve().parents[1] / "skill" / SKILL_NAME).resolve()


def default_target(kind: str) -> Path:
    if kind == "codex":
        codex_home = os.environ.get("CODEX_HOME")
        base = Path(codex_home).expanduser() if codex_home else Path.home() / ".codex"
        return base / "skills"
    return Path.home() / ".agents" / "skills"


def _contains_symlink(root: Path) -> bool:
    return any(path.is_symlink() for path in root.rglob("*"))


def install(source: Path, target_root: Path, apply: bool, force: bool) -> tuple[Path, Path | None]:
    source = source.expanduser().resolve(strict=True)
    target_root = target_root.expanduser().resolve()
    destination = target_root / SKILL_NAME
    if not (source / "SKILL.md").is_file():
        raise ValueError(f"invalid skill source: {source}")
    if _contains_symlink(source):
        raise ValueError("skill source contains symbolic links")
    if source == destination or source in destination.parents:
        raise ValueError("source and destination overlap")
    if destination.exists() and not force:
        raise FileExistsError(f"destination exists: {destination}; use --force to back it up and replace it")
    if not apply:
        return destination, None

    target_root.mkdir(parents=True, exist_ok=True)
    staging = target_root / f".{SKILL_NAME}.installing-{os.getpid()}"
    if staging.exists():
        raise FileExistsError(f"staging path already exists: {staging}")
    backup: Path | None = None
    try:
        shutil.copytree(source, staging)
        if destination.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = target_root / f"{SKILL_NAME}.backup-{stamp}"
            suffix = 1
            while backup.exists():
                backup = target_root / f"{SKILL_NAME}.backup-{stamp}-{suffix}"
                suffix += 1
            destination.rename(backup)
        staging.rename(destination)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        if backup and backup.exists() and not destination.exists():
            backup.rename(destination)
        raise
    return destination, backup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("codex", "agents"), default="codex")
    parser.add_argument("--target-dir", type=Path, help="Override the parent skill directory")
    parser.add_argument("--apply", action="store_true", help="Perform the copy; default is preview only")
    parser.add_argument("--force", action="store_true", help="Back up and replace an existing installation")
    args = parser.parse_args()

    source = source_skill()
    target_root = args.target_dir if args.target_dir else default_target(args.target)
    try:
        destination, backup = install(source, target_root, args.apply, args.force)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    action = "installed" if args.apply else "preview"
    print(f"{action}: {source} -> {destination}")
    if backup:
        print(f"backup: {backup}")
    if not args.apply:
        print("No files changed. Re-run with --apply after approving this destination.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

