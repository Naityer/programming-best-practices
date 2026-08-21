#!/usr/bin/env python3
"""Joint fail-closed release gate for patterns, algorithms and audit_code."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPTS.parent
QUICK_VALIDATE = Path.home() / ".codex" / "skills" / ".system" / "skill-creator" / "scripts" / "quick_validate.py"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-code-repo", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    audit_repo = args.audit_code_repo.resolve(strict=True)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    audit_python = next((path for path in (audit_repo / ".venv/Scripts/python.exe", audit_repo / ".venv/bin/python") if path.is_file()), Path(sys.executable))
    pnpm = shutil.which("pnpm")
    env = {**os.environ, "CI": "1", "NO_COLOR": "1", "PYTHONDONTWRITEBYTECODE": "1", "PROGRAMMING_BEST_PRACTICES_REPO": str(REPO_ROOT)}
    steps: list[tuple[str, list[str], Path]] = []
    if QUICK_VALIDATE.is_file():
        steps.append(("skill structure validation", [sys.executable, str(QUICK_VALIDATE), str(SKILL_ROOT)], REPO_ROOT))
    else:
        steps.append(("skill structure validation", [sys.executable, "-c", "raise SystemExit('quick_validate.py unavailable')"], REPO_ROOT))
    steps.extend([
        ("skill regression", [sys.executable, "-m", "unittest", "discover", "-s", "tests"], REPO_ROOT),
        ("algorithm empirical metrics", [sys.executable, str(SCRIPTS / "evaluate_algorithms.py"), str(REPO_ROOT / "evals/algorithms/empirical-cases.json"), "--output", str(output / "algorithm-empirical-evaluation.json")], REPO_ROOT),
        ("algorithm functional index", [sys.executable, str(SCRIPTS / "measure_algorithm_functionality.py"), "--output", str(output / "algorithm-functional-index.json")], REPO_ROOT),
        ("STANDARD self-repository analysis", [sys.executable, str(SCRIPTS / "analyze_algorithms.py"), "--root", str(REPO_ROOT), "--output", str(output / "programming-best-practices-algorithms.json"), "--profile", "standard"], REPO_ROOT),
        ("DEEP audit_code repository analysis", [sys.executable, str(SCRIPTS / "analyze_algorithms.py"), "--root", str(audit_repo), "--output", str(output / "audit-code-algorithms.json"), "--profile", "deep"], REPO_ROOT),
        ("audit_code regression and bidirectional E2E", [str(audit_python), "-m", "pytest", "-q"], audit_repo),
    ])
    if pnpm:
        steps.extend([
            ("frontend lint", [pnpm, "--dir", "web", "run", "lint"], audit_repo),
            ("frontend typecheck", [pnpm, "--dir", "web", "run", "typecheck"], audit_repo),
            ("frontend production build", [pnpm, "--dir", "web", "run", "build"], audit_repo),
        ])
    else:
        steps.append(("frontend tooling", [sys.executable, "-c", "raise SystemExit('pnpm unavailable')"], audit_repo))
    results = []
    for name, command, cwd in steps:
        completed = subprocess.run(command, cwd=cwd, env=env, check=False)
        results.append({"name": name, "exit_code": completed.returncode, "status": "passed" if completed.returncode == 0 else "failed"})
    passed = all(item["status"] == "passed" for item in results)
    document = {
        "schema_version": "1.0.0", "status": "passed" if passed else "failed",
        "production_ready": passed,
        "evidence": {"offline": True, "atlas_written": False, "repositories": [str(REPO_ROOT), str(audit_repo)]},
        "steps": results,
    }
    (output / "joint-production-readiness.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(document, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

