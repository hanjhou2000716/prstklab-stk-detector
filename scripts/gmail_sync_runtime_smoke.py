"""Prove the Gmail CLI imports with only its locked runtime dependencies."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GMAIL_MOCK_TESTS = (
    "tests/test_gmail_history_sync.py",
    "tests/test_gmail_ingress.py",
)


def _credential_free_environment() -> dict[str, str]:
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith(("GMAIL_", "SUPABASE_", "TELEGRAM_")):
            env.pop(key, None)
    env["NOTIFY"] = "false"
    return env


def main() -> int:
    uv = shutil.which("uv")
    if not uv:
        print("Gmail runtime smoke requires the pinned uv executable.", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix=".codex-gmail-runtime-", dir=ROOT) as temporary:
        temporary_path = Path(temporary)
        env = _credential_free_environment()
        env["UV_PROJECT_ENVIRONMENT"] = str(temporary_path / "gmail-sync-venv")
        env["UV_CACHE_DIR"] = str(temporary_path / "uv-cache")
        install = subprocess.run(
            [uv, "sync", "--locked", "--only-group", "gmail-sync", "--no-install-project"],
            cwd=ROOT, env=env, check=False, timeout=240,
        )
        if install.returncode:
            print("The clean Gmail-only locked environment could not be installed.", file=sys.stderr)
            return install.returncode
        cli_check = subprocess.run(
            [uv, "run", "--project", str(ROOT), "--no-sync", "python",
             str(ROOT / "scripts" / "sync_gmail_supabase.py"), "--help"],
            cwd=ROOT, env=env, check=False, timeout=60,
        )
        if cli_check.returncode:
            print("The Gmail CLI failed to import in its production no-sync environment.", file=sys.stderr)
            return cli_check.returncode

    with tempfile.TemporaryDirectory(prefix=".codex-gmail-pytest-", dir=ROOT) as temporary:
        mocks = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--no-cov", "--basetemp",
             str(Path(temporary) / "pytest"), *GMAIL_MOCK_TESTS],
            cwd=ROOT, env=_credential_free_environment(), check=False, timeout=300,
        )
        if mocks.returncode:
            print("Mock Gmail/storage synchronization or parser contract tests failed.", file=sys.stderr)
        return mocks.returncode


if __name__ == "__main__":
    raise SystemExit(main())
