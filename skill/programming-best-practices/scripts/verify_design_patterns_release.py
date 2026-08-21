#!/usr/bin/env python3
"""Run the production gate for the Python design-pattern feature."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = Path(__file__).resolve().parent


def _audit_python(audit_repo: Path) -> str:
    candidates = [
        audit_repo / ".venv" / "Scripts" / "python.exe",
        audit_repo / ".venv" / "bin" / "python",
    ]
    return str(next((item for item in candidates if item.is_file()), Path(sys.executable)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-code-repo", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    audit_repo = args.audit_code_repo.expanduser().resolve(strict=True)
    output = args.output_dir.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    pnpm = shutil.which("pnpm")
    if not pnpm:
        print("pnpm is required for the frontend production gate", file=sys.stderr)
        return 2

    steps: list[dict[str, object]] = []
    environment = {
        **os.environ,
        "CI": "1",
        "NO_COLOR": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PROGRAMMING_BEST_PRACTICES_REPO": str(REPO_ROOT),
    }

    def run(name: str, argv: list[str], cwd: Path) -> bool:
        started = time.monotonic()
        completed = subprocess.run(argv, cwd=cwd, env=environment, check=False)
        steps.append({
            "name": name,
            "status": "passed" if completed.returncode == 0 else "failed",
            "exit_code": completed.returncode,
            "duration_seconds": round(time.monotonic() - started, 2),
        })
        return completed.returncode == 0

    python = sys.executable
    audit_python = _audit_python(audit_repo)
    commands = [
        ("skill regression suite", [python, "-m", "unittest", "discover", "-s", "tests"], REPO_ROOT),
        (
            "functional index",
            [python, str(SCRIPTS / "measure_design_pattern_functionality.py"), "--output", str(output / "functional-index.json")],
            REPO_ROOT,
        ),
        ("audit_code regression suite and feedback E2E", [audit_python, "-m", "pytest", "-q"], audit_repo),
        ("frontend typecheck", [pnpm, "typecheck"], audit_repo / "web"),
        ("frontend lint", [pnpm, "exec", "eslint", "src", "--max-warnings=0"], audit_repo / "web"),
        ("frontend build", [pnpm, "build"], audit_repo / "web"),
    ]
    ok = all(run(name, argv, cwd) for name, argv, cwd in commands)

    corpus: list[dict[str, object]] = []
    for name, repository in (("programming-best-practices", REPO_ROOT), ("audit_code", audit_repo)):
        artifact_dir = output / "corpus" / name
        artifact = artifact_dir / "design-patterns.json"
        analyze_ok = run(
            f"analyze corpus: {name}",
            [
                python, str(SCRIPTS / "analyze_design_patterns.py"), "--root", str(repository),
                "--output", str(artifact), "--uml-dir", str(artifact_dir / "uml"),
            ],
            REPO_ROOT,
        )
        validate_ok = analyze_ok and run(
            f"validate corpus artifact: {name}",
            [python, str(SCRIPTS / "validate_design_patterns.py"), str(artifact)],
            REPO_ROOT,
        )
        ok = ok and analyze_ok and validate_ok
        if artifact.is_file():
            data = json.loads(artifact.read_text(encoding="utf-8"))
            corpus.append({
                "repository": name,
                "files_scanned": data["files_scanned"],
                "patterns": len(data["patterns"]),
                "statuses": {
                    status: sum(item["status"] == status for item in data["patterns"])
                    for status in sorted({item["status"] for item in data["patterns"]})
                },
                "limitations": data["limitations"],
            })

    summary = {
        "schema_version": "1.0.0",
        "scope": "production gate for the Python design-pattern frontend",
        "status": "passed" if ok else "failed",
        "steps": steps,
        "corpus": corpus,
    }
    (output / "production-readiness.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
