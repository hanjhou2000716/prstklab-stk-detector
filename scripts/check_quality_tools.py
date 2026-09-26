"""Enforce pinned workflow linters and an executable ShellCheck regression."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIONLINT_VERSION = "1.7.7"
SHELLCHECK_VERSION = "0.11.0"


def _version(binary: str, args: list[str]) -> str:
    path = shutil.which(binary)
    if not path:
        raise RuntimeError(f"required_quality_tool_missing:{binary}")
    result = subprocess.run([path, *args], cwd=ROOT, check=False, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"quality_tool_version_failed:{binary}")
    return f"{result.stdout}\n{result.stderr}"


def main() -> int:
    try:
        actionlint = _version("actionlint", ["-version"])
        shellcheck = _version("shellcheck", ["--version"])
        if ACTIONLINT_VERSION not in actionlint or f"version: {SHELLCHECK_VERSION}" not in shellcheck:
            raise RuntimeError("quality_tool_version_mismatch")
        binary = shutil.which("shellcheck")
        assert binary is not None
        bad = subprocess.run(
            [binary, str(ROOT / "tests" / "fixtures" / "shellcheck" / "sc2129_bad.sh")],
            cwd=ROOT, check=False, capture_output=True, text=True,
        )
        if bad.returncode == 0 or "SC2129" not in f"{bad.stdout}\n{bad.stderr}":
            raise RuntimeError("shellcheck_sc2129_regression_not_detected")
        good = subprocess.run(
            [binary, str(ROOT / "tests" / "fixtures" / "shellcheck" / "sc2129_grouped.sh")],
            cwd=ROOT, check=False, capture_output=True, text=True,
        )
        if good.returncode:
            raise RuntimeError("shellcheck_grouped_append_fixture_failed")
    except (OSError, RuntimeError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"PASS: actionlint {ACTIONLINT_VERSION}, ShellCheck {SHELLCHECK_VERSION}, SC2129 regression")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
