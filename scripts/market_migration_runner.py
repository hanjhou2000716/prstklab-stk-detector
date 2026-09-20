"""Run Supabase market migrations with a safe preflight/apply contract.

The workflow deliberately delegates all state decisions to this module.  CLI
output is captured in memory and discarded; the only persisted result is a
redacted JSON document containing statuses, migration versions and stable
error codes.  Preflight failures return zero so they cannot create a red
production-failure notification.  Apply failures return non-zero only after
the diagnostic document has been written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from scripts.validate_supabase_migrations import compare
from src.market_backup_verification import (
    VerificationError,
    verify_market_backup,
)

PROJECT_REF_RE = re.compile(r"^[a-z0-9]{20}$")
RUN_ID_RE = re.compile(r"^[0-9]+$")
ERROR_CODES = {
    "none",
    "credential_missing",
    "token_unauthorized",
    "token_database_write_denied",
    "project_ref_mismatch",
    "database_password_invalid",
    "migration_history_diverged",
    "migration_dry_run_failed",
    "migration_apply_failed",
    "schema_verification_failed",
    "rls_verification_failed",
    "backup_smoke_failed",
    "preflight_reference_missing",
    "preflight_reference_invalid",
    "preflight_reference_expired",
    "confirmation_required",
    "apply_requires_main",
    "main_ref_changed",
    "supabase_cli_unavailable",
    "runner_internal_error",
}


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


CommandRunner = Callable[[list[str], Path, dict[str, str]], CommandResult]


def _run_command(command: list[str], cwd: Path, env: dict[str, str]) -> CommandResult:
    """Run a command without exposing its output to the workflow log."""
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return CommandResult(127)
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)


def project_ref_fingerprint(project_ref: str) -> str:
    """Return a non-reversible project identifier for diagnostics."""
    return hashlib.sha256(project_ref.strip().encode("utf-8")).hexdigest()[:16]


def _safe_versions(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return sorted({str(item) for item in value if re.fullmatch(r"20\d{10}", str(item))})


def _base_diagnostic(*, mode: str, head_sha: str, project_ref: str, run_id: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "status": "running",
        "alert_class": "diagnostic_only" if mode == "preflight" else "production_failure",
        "stage": "credentials",
        "error_code": "none",
        "failed_checks": [],
        "head_sha": head_sha,
        "run_id": run_id,
        "project_ref_fingerprint": project_ref_fingerprint(project_ref) if project_ref else "unknown",
        "pending_migrations": [],
        "registered_migrations": [],
        "schema_status": "not_verified",
        "rls_status": "not_verified",
        "service_role_read_status": "not_verified",
        "service_role_write_status": "not_verified",
        "canary_cleanup_status": "not_verified",
        "verified_at": None,
    }


class MigrationRunner:
    """Orchestrate one non-concurrent migration decision."""

    def __init__(
        self,
        *,
        mode: str,
        repo_root: Path,
        artifact_dir: Path,
        preflight_dir: Path | None = None,
        head_sha: str,
        ref: str,
        run_id: str,
        preflight_run_id: str = "",
        confirmation: str = "",
        current_main_sha_file: Path | None = None,
        environment: dict[str, str] | None = None,
        command_runner: CommandRunner = _run_command,
        session: requests.Session | None = None,
        now: datetime | None = None,
    ) -> None:
        self.mode = mode
        self.repo_root = repo_root
        self.artifact_dir = artifact_dir
        self.preflight_dir = preflight_dir or (repo_root / "preflight-input")
        self.head_sha = head_sha
        self.ref = ref
        self.run_id = run_id
        self.preflight_run_id = preflight_run_id.strip()
        self.confirmation = confirmation
        self.current_main_sha_file = current_main_sha_file
        self.env = dict(environment or os.environ)
        self.command_runner = command_runner
        self.session = session or requests.Session()
        self.current_time = now or _now()
        self.local_versions = self._local_versions()
        self.diagnostic = _base_diagnostic(
            mode=mode,
            head_sha=head_sha,
            project_ref=self.env.get("SUPABASE_PROJECT_ID", ""),
            run_id=run_id,
        )

    def _local_versions(self) -> tuple[str, ...]:
        versions = {
            path.name.split("_", 1)[0]
            for path in (self.repo_root / "supabase" / "migrations").glob("*.sql")
            if re.fullmatch(r"20\d{10}", path.name.split("_", 1)[0])
        }
        return tuple(sorted(versions))

    def _write(self) -> None:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        path = self.artifact_dir / "verification.json"
        path.write_text(
            json.dumps(self.diagnostic, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _finish(self, *, status: str, stage: str, error_code: str = "none", failed_checks: tuple[str, ...] = ()) -> int:
        if error_code not in ERROR_CODES:
            error_code = "runner_internal_error"
        self.diagnostic.update(
            status=status,
            stage=stage,
            error_code=error_code,
            failed_checks=sorted(set(failed_checks)),
            verified_at=_iso(self.current_time) if status in {"ready_no_changes", "ready_apply_required", "already_verified", "applied"} else None,
        )
        if self.mode == "preflight":
            self.diagnostic["alert_class"] = "diagnostic_only"
        elif status not in {"already_verified", "applied"}:
            self.diagnostic["alert_class"] = "production_failure"
        else:
            self.diagnostic["alert_class"] = "diagnostic_only"
        self._write()
        print(json.dumps(self.diagnostic, ensure_ascii=False, sort_keys=True))
        return 0 if self.mode == "preflight" else (0 if status in {"already_verified", "applied"} else 1)

    def _warning(self, stage: str, code: str, *checks: str) -> int:
        return self._finish(status="warning_blocked", stage=stage, error_code=code, failed_checks=checks)

    def _failure(self, stage: str, code: str, *checks: str) -> int:
        return self._finish(status="failed", stage=stage, error_code=code, failed_checks=checks)

    def _required_credentials(self) -> tuple[str, ...]:
        return (
            "SUPABASE_ACCESS_TOKEN",
            "SUPABASE_DB_PASSWORD",
            "SUPABASE_PROJECT_ID",
            "SUPABASE_URL",
            "SUPABASE_SERVICE_ROLE_KEY",
        )

    def _validate_credentials(self) -> tuple[bool, str]:
        missing = tuple(name for name in self._required_credentials() if not self.env.get(name, "").strip())
        if missing:
            return False, "credential_missing"
        if not PROJECT_REF_RE.fullmatch(self.env["SUPABASE_PROJECT_ID"].strip()):
            return False, "project_ref_mismatch"
        return True, "none"

    def _validate_project_access(self) -> tuple[bool, str]:
        project_ref = self.env["SUPABASE_PROJECT_ID"].strip()
        try:
            response = self.session.get(
                f"https://api.supabase.com/v1/projects/{project_ref}",
                headers={
                    "Authorization": f"Bearer {self.env['SUPABASE_ACCESS_TOKEN'].strip()}",
                    "Accept": "application/json",
                },
                timeout=30,
            )
        except requests.RequestException:
            return False, "token_unauthorized"
        if response.status_code in {401, 403} or not response.ok:
            return False, "token_unauthorized"
        try:
            payload = response.json()
        except ValueError:
            return False, "token_unauthorized"
        if isinstance(payload, dict):
            identity = str(payload.get("id") or payload.get("ref") or payload.get("project_ref") or "")
            if identity and identity != project_ref:
                return False, "project_ref_mismatch"
        return True, "none"

    def _run_cli(self, command: list[str]) -> CommandResult:
        child_env = dict(self.env)
        # The CLI reads the token from the environment.  It is never included
        # in the command line or in the diagnostic file.
        return self.command_runner(command, self.repo_root, child_env)

    @staticmethod
    def _cli_failure_code(result: CommandResult, default: str) -> str:
        if result.returncode == 127:
            return "supabase_cli_unavailable"
        # Inspect only for classification; command output is never persisted.
        output = f"{result.stdout}\n{result.stderr}".lower()
        if any(token in output for token in ("permission denied", "forbidden", "unauthorized", "access denied")):
            return "token_database_write_denied"
        return default

    def _validate_preflight_reference(self) -> tuple[bool, str]:
        if not self.preflight_run_id or not RUN_ID_RE.fullmatch(self.preflight_run_id):
            return False, "preflight_reference_missing"
        if self.confirmation != "APPLY":
            return False, "confirmation_required"
        if self.ref != "refs/heads/main":
            return False, "apply_requires_main"

        reference_dir = self.preflight_dir
        metadata_path = reference_dir / "run-metadata.json"
        if not metadata_path.exists():
            return False, "preflight_reference_missing"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False, "preflight_reference_invalid"
        if not isinstance(metadata, dict):
            return False, "preflight_reference_invalid"
        if (
            str(metadata.get("run_id") or "") != self.preflight_run_id
            or str(metadata.get("repository") or "") != "hanjhou2000716/prstklab-stk-detector"
            or str(metadata.get("workflow_path") or "") != ".github/workflows/migrate-market-observations.yml"
            or str(metadata.get("head_sha") or "") != self.head_sha
            or str(metadata.get("head_branch") or "") != "main"
            or str(metadata.get("event") or "") != "workflow_dispatch"
            or str(metadata.get("conclusion") or "") != "success"
        ):
            return False, "preflight_reference_invalid"
        try:
            if int(metadata.get("run_attempt") or 0) < 1:
                return False, "preflight_reference_invalid"
        except (TypeError, ValueError):
            return False, "preflight_reference_invalid"
        created_at = _parse_iso(metadata.get("created_at"))
        if created_at is None or created_at > self.current_time + timedelta(minutes=5):
            return False, "preflight_reference_invalid"
        if self.current_time - created_at > timedelta(hours=2):
            return False, "preflight_reference_expired"

        if self.current_main_sha_file is not None:
            try:
                current_main_sha = self.current_main_sha_file.read_text(encoding="utf-8").strip()
            except OSError:
                return False, "preflight_reference_invalid"
            if not current_main_sha or current_main_sha != self.head_sha:
                return False, "main_ref_changed"

        candidates = list(reference_dir.rglob("verification.json")) if reference_dir.exists() else []
        if not candidates:
            return False, "preflight_reference_missing"
        try:
            reference = json.loads(candidates[0].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False, "preflight_reference_invalid"
        if reference.get("mode") != "preflight":
            return False, "preflight_reference_invalid"
        if str(reference.get("run_id") or "") != self.preflight_run_id:
            return False, "preflight_reference_invalid"
        if reference.get("head_sha") != self.head_sha:
            return False, "preflight_reference_invalid"
        if reference.get("project_ref_fingerprint") != self.diagnostic.get("project_ref_fingerprint"):
            return False, "preflight_reference_invalid"
        if reference.get("status") not in {"ready_no_changes", "ready_apply_required"}:
            return False, "preflight_reference_invalid"
        verified_at = _parse_iso(reference.get("verified_at"))
        if verified_at is None or verified_at > self.current_time + timedelta(minutes=5):
            return False, "preflight_reference_invalid"
        if self.current_time - verified_at > timedelta(hours=2):
            return False, "preflight_reference_expired"
        self.diagnostic["preflight_run_id"] = self.preflight_run_id
        return True, "none"

    def _verification(self, expected: tuple[str, ...]) -> tuple[bool, str]:
        try:
            result = verify_market_backup(
                project_ref=self.env["SUPABASE_PROJECT_ID"],
                access_token=self.env["SUPABASE_ACCESS_TOKEN"],
                supabase_url=self.env["SUPABASE_URL"],
                service_role_key=self.env["SUPABASE_SERVICE_ROLE_KEY"],
                session=self.session,
                expected_migrations=expected,
            )
        except VerificationError as exc:
            return False, exc.code
        self.diagnostic.update(
            schema_status=result.get("schema_status", "not_verified"),
            rls_status=result.get("rls_status", "not_verified"),
            service_role_read_status=result.get("service_role_read_status", "not_verified"),
            service_role_write_status=result.get("service_role_write_status", "not_verified"),
            canary_cleanup_status=result.get("canary_cleanup_status", "not_verified"),
            registered_migrations=_safe_versions(result.get("registered_migrations")),
        )
        return True, "none"

    def run(self) -> int:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        try:
            valid, code = self._validate_credentials()
            if not valid:
                return self._warning("credentials", code) if self.mode == "preflight" else self._failure("credentials", code)

            valid, code = self._validate_project_access()
            if not valid:
                return self._warning("credentials", code) if self.mode == "preflight" else self._failure("credentials", code)

            if self.mode == "apply":
                valid, code = self._validate_preflight_reference()
                if not valid:
                    return self._failure("preflight_reference", code)

            linked = self._run_cli([
                "supabase", "link", "--project-ref", self.env["SUPABASE_PROJECT_ID"],
                "--password", self.env["SUPABASE_DB_PASSWORD"],
            ])
            if linked.returncode != 0:
                code = self._cli_failure_code(linked, "database_password_invalid")
                return self._warning("link", code) if self.mode == "preflight" else self._failure("link", code)

            listed = self._run_cli(["supabase", "migration", "list", "--linked"])
            if listed.returncode != 0:
                code = self._cli_failure_code(listed, "migration_history_diverged")
                return self._warning("history", code) if self.mode == "preflight" else self._failure("history", code)
            comparison = compare(self.repo_root, listed.stdout + "\n" + listed.stderr)
            (self.artifact_dir / "migration-comparison.json").write_text(
                json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            registered = _safe_versions(
                [
                    version
                    for version in self.local_versions
                    if version not in _safe_versions(comparison.get("pending_local_versions"))
                ]
            )
            pending = _safe_versions(comparison.get("pending_local_versions"))
            self.diagnostic["registered_migrations"] = registered
            self.diagnostic["pending_migrations"] = pending
            if comparison.get("status") != "ready":
                return self._warning("history", "migration_history_diverged") if self.mode == "preflight" else self._failure("history", "migration_history_diverged")

            dry_run = self._run_cli(["supabase", "db", "push", "--dry-run"])
            if dry_run.returncode != 0:
                code = self._cli_failure_code(dry_run, "migration_dry_run_failed")
                return self._warning("dry_run", code) if self.mode == "preflight" else self._failure("dry_run", code)

            expected_for_current_schema = tuple(registered) if pending else self.local_versions
            verified, code = self._verification(expected_for_current_schema)
            if not verified:
                if self.mode == "preflight":
                    return self._warning("schema", code)
                return self._failure("schema", code)

            if self.mode == "preflight":
                return self._finish(
                    status="ready_apply_required" if pending else "ready_no_changes",
                    stage="complete",
                )

            if not pending:
                return self._finish(status="already_verified", stage="complete")

            applied = self._run_cli(["supabase", "db", "push"])
            if applied.returncode != 0:
                code = self._cli_failure_code(applied, "migration_apply_failed")
                return self._failure("apply", code)
            verified, code = self._verification(self.local_versions)
            if not verified:
                return self._failure("schema", code)
            return self._finish(status="applied", stage="complete")
        except (KeyError, OSError, ValueError, requests.RequestException):
            return self._warning("runner", "runner_internal_error") if self.mode == "preflight" else self._failure("runner", "runner_internal_error")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("preflight", "apply"), default="preflight")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--artifact-dir", type=Path, default=Path("migration-diagnostics"))
    parser.add_argument("--preflight-dir", type=Path, default=Path("preflight-input"))
    parser.add_argument("--head-sha", default=os.getenv("GITHUB_SHA", ""))
    parser.add_argument("--ref", default=os.getenv("GITHUB_REF", ""))
    parser.add_argument("--run-id", default=os.getenv("GITHUB_RUN_ID", ""))
    parser.add_argument("--preflight-run-id", default=os.getenv("PREFLIGHT_RUN_ID", ""))
    parser.add_argument("--confirmation", default=os.getenv("MIGRATION_CONFIRMATION", ""))
    parser.add_argument("--current-main-sha-file", type=Path, default=None)
    return parser


def main() -> int:
    args = _parser().parse_args()
    runner = MigrationRunner(
        mode=args.mode,
        repo_root=args.repo_root.resolve(),
        artifact_dir=args.artifact_dir.resolve(),
        preflight_dir=(args.preflight_dir.resolve() if args.preflight_dir else None),
        head_sha=args.head_sha,
        ref=args.ref,
        run_id=args.run_id,
        preflight_run_id=args.preflight_run_id,
        confirmation=args.confirmation,
        current_main_sha_file=(args.current_main_sha_file.resolve() if args.current_main_sha_file else None),
    )
    return runner.run()


if __name__ == "__main__":
    raise SystemExit(main())
