# programming-best-practices

Source repository for the distributable `programming-best-practices` Codex skill.

The runtime skill lives in `skill/programming-best-practices/`. Tests, fixtures, evaluation cases, and the local installer intentionally remain outside that directory.

## Audit pipeline\n\nThe planner is read-only and writes its plan outside the audited repository. Execution requires an explicit acknowledgement and separate permissions for project writes, network use, and generated code.\n\n```powershell\npython skill\programming-best-practices\scripts\plan_audit.py --root C:\path\to\repo --profile standard --output C:\temp\plan.json\npython skill\programming-best-practices\scripts\run_audit.py C:\temp\plan.json --output-dir C:\temp\execution --execute\npython skill\programming-best-practices\scripts\build_report.py C:\temp\execution\execution.json --output-dir C:\temp\report\n```\n\n## Validate

```powershell
python -m unittest discover -s tests -v
python C:\Users\tiand\.codex\skills\.system\skill-creator\scripts\quick_validate.py skill\programming-best-practices
```

## Preview installation

```powershell
python tools\install_skill.py
```

The installer is dry-run by default. After reviewing the destination, run it with `--apply`. Existing installations are rejected unless `--force` is supplied; forced replacement creates a timestamped backup.


## Production release gate (Python)

With the sibling `audit_code` repository available:

```powershell
python skill\programming-best-practices\scripts\verify_design_patterns_release.py `
  --audit-code-repo C:\path\to\audit_code `
  --output-dir C:\temp\design-pattern-release
```

The command requires every test, the bidirectional review E2E, frontend checks, build, functional index, and validation against both real repositories to pass.
