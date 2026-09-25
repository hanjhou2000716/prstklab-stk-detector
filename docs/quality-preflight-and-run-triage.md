# Quality preflight and failed-run triage

The quality workflow and local preflight use the same pinned checks. The local workflow syntax check needs actionlint 1.7.7 on `PATH` or Docker Desktop with its Linux engine available. After installing the locked development environment and Playwright Chromium, run:

```powershell
uv run python scripts/quality_preflight.py
```

The workflow runs the same entry point in two phases so workflow syntax, Ruff, and Mypy fail before the longer tests and browser setup. The test phase runs changed test files first when a base commit is available, then runs the full unit suite and both coverage thresholds. The full suite remains authoritative when a source change does not have a directly changed test file.

To classify a failed GitHub Actions email against the PR's current state, use its run ID:

```powershell
uv run python scripts/inspect_quality_run.py --repo hanjhou2000716/prstklab-stk-detector --run-id 36119891343
```

The command uses authenticated, read-only GitHub CLI requests. It compares the run's PR and commit with the PR's latest commit and quality run. Exit code `0` means the failure is superseded or the latest check passed; `1` means a current or unverified failure needs attention; `2` means the run could not be classified. It never reruns workflows or changes GitHub state.

The workflow summary records its run URL and attempt, PR head and base commits, tested commit, static and unit-test outcomes, and the read-only triage command. GitHub's normal failure emails remain enabled.
