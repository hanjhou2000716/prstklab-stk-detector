# Quality preflight tools

The local preflight and CI use the same required versions:
- actionlint 1.7.7
- ShellCheck 0.11.0
- Ruff and Mypy from the repository's locked uv environment

On Windows PowerShell, run:

    .\scripts\bootstrap_quality_tools.ps1

The helper downloads only official GitHub release artifacts, validates
actionlint against the official release checksum manifest, validates the
ShellCheck archive against its published SHA-256, and places the executables
under .quality-tools. It adds that directory to PATH for the current
PowerShell session. Then run:

    uv run python scripts/quality_preflight.py --static

The preflight fails if either workflow linter is missing or has a different
version. It also executes the ShellCheck SC2129 regression pair: the original
repeated append must fail with SC2129 and the grouped append must pass. The
workflow-syntax check uses the pinned actionlint binary with pinned ShellCheck
available on PATH, so embedded shell is checked too. Docker fallback and
unverified shell-check skipping are not accepted as a complete result.
