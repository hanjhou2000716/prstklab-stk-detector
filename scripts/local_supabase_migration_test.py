"""Exercise every repository migration against a disposable local Supabase stack.

This command is intentionally isolated from the checked-out project and never
accepts production credentials.  It proves that migrations apply from an empty
database, are idempotent on a second push, and expose only the service-role
paths required by the private market backup store.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.validate_supabase_migrations import compare  # noqa: E402


class LocalSupabaseError(RuntimeError):
    """A safe local integration failure."""

    def __init__(
        self,
        code: str,
        *,
        stage: str = "unknown",
        exit_code: int | None = None,
        diagnostic: str = "",
        cleanup: str = "not_attempted",
    ) -> None:
        super().__init__(code)
        self.code = code
        self.stage = stage
        self.exit_code = exit_code
        self.diagnostic = diagnostic
        self.cleanup = cleanup

    def as_result(self) -> dict[str, Any]:
        return {
            "status": "failed",
            "stage": self.stage,
            "error_code": self.code,
            "command_exit_code": self.exit_code,
            "diagnostic": self.diagnostic,
            "cleanup": self.cleanup,
            "production_credentials_used": False,
        }


_SECRET_VALUE_RE = re.compile(
    r"(?i)(\b(?:authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"password|passwd|secret|service[_-]?role[_-]?key|jwt)\b\s*[:=]\s*)([^\s,;]+)"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
_URL_CREDENTIALS_RE = re.compile(r"(?i)(https?://)[^/@\s]+:[^/@\s]+@")
_URL_QUERY_SECRET_RE = re.compile(r"(?i)([?&](?:token|key|secret|password)=)[^&\s]+")
_SECRET_ENV_LINE_RE = re.compile(
    r"(?i)^\s*(?:export\s+)?[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|SERVICE_ROLE_KEY|ACCESS_KEY)\s*=.*$"
)


def _safe_excerpt(value: str | bytes | None, *, max_chars: int = 1400) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    lines: list[str] = []
    for line in value.splitlines():
        if _SECRET_ENV_LINE_RE.match(line):
            lines.append("[redacted environment value]")
            continue
        line = _SECRET_VALUE_RE.sub(r"\1[redacted]", line)
        line = _BEARER_RE.sub("Bearer [redacted]", line)
        line = _JWT_RE.sub("[redacted JWT]", line)
        line = _URL_CREDENTIALS_RE.sub(r"\1[redacted]@", line)
        line = _URL_QUERY_SECRET_RE.sub(r"\1[redacted]", line)
        lines.append(line)
    return "\n".join(lines[-20:])[-max_chars:]


def _command_stage(command: list[str]) -> str:
    executable = Path(command[0]).name.lower() if command else "unknown"
    if executable.startswith("supabase"):
        safe_parts = [part for part in command[1:3] if re.fullmatch(r"[a-zA-Z0-9_-]+", part)]
        return ":".join(["supabase", *safe_parts])
    return executable


def _run(command: list[str], cwd: Path, *, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        diagnostic = _safe_excerpt(exc.stderr) or _safe_excerpt(exc.stdout)
        raise LocalSupabaseError(
            "command_timed_out",
            stage=_command_stage(command),
            diagnostic=diagnostic,
        ) from exc
    except OSError as exc:
        raise LocalSupabaseError(
            "command_unavailable",
            stage=_command_stage(command),
            diagnostic=type(exc).__name__,
        ) from exc
    except subprocess.SubprocessError as exc:
        raise LocalSupabaseError(
            "command_failed_to_run",
            stage=_command_stage(command),
            diagnostic=type(exc).__name__,
        ) from exc


def _check(command: list[str], cwd: Path, *, timeout: int = 600) -> str:
    result = _run(command, cwd, timeout=timeout)
    if result.returncode != 0:
        diagnostic = _safe_excerpt(result.stderr) or _safe_excerpt(result.stdout)
        raise LocalSupabaseError(
            "command_failed",
            stage=_command_stage(command),
            exit_code=result.returncode,
            diagnostic=diagnostic,
        )
    return result.stdout


def _capture_start_diagnostics(cli: str, cwd: Path, project_id: str) -> dict[str, Any]:
    disk = shutil.disk_usage(cwd)
    result: dict[str, Any] = {"free_disk_bytes": disk.free, "project_id": project_id}
    for label, command in (
        ("supabase_version", [cli, "--version"]),
        ("docker_server_version", ["docker", "version", "--format", "{{.Server.Version}}"]),
        (
            "project_containers",
            [
                "docker", "ps", "-a", "--filter", f"name={project_id}",
                "--format", "{{.Names}}|{{.State}}|{{.Status}}",
            ],
        ),
    ):
        try:
            output = _run(command, cwd, timeout=20)
            result[label] = {
                "exit_code": output.returncode,
                "output": _safe_excerpt(output.stdout if output.returncode == 0 else output.stderr),
            }
        except LocalSupabaseError as exc:
            result[label] = {"error_code": exc.code, "stage": exc.stage, "diagnostic": exc.diagnostic}
    return result


def _status_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", line.strip())
        if not match:
            continue
        values[match.group(1)] = shlex.split(match.group(2))[0] if match.group(2) else ""
    return values


def _psql(cwd: Path, db_url: str, query: str) -> str:
    if not db_url:
        raise LocalSupabaseError("local_db_url_missing")
    return _check(["psql", db_url, "-Atqc", query], cwd, timeout=60).strip()


def _rest(
    session: requests.Session,
    *,
    base_url: str,
    key: str,
    method: str,
    path: str,
    **kwargs: Any,
) -> requests.Response:
    extra_headers = kwargs.pop("headers", {})
    response = session.request(
        method,
        f"{base_url.rstrip('/')}{path}",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if "json" in kwargs else {}),
            **extra_headers,
        },
        timeout=30,
        **kwargs,
    )
    return response


def _verify_schema(cwd: Path, db_url: str) -> None:
    query = """
    select case when
      to_regclass('public.market_observations') is not null
      and to_regclass('public.market_source_state') is not null
      and (select relrowsecurity from pg_class where oid = 'public.market_observations'::regclass)
      and (select relrowsecurity from pg_class where oid = 'public.market_source_state'::regclass)
      and not has_table_privilege('anon', 'public.market_observations', 'SELECT')
      and not has_table_privilege('authenticated', 'public.market_observations', 'SELECT')
      and not has_table_privilege('anon', 'public.market_source_state', 'SELECT')
      and not has_table_privilege('authenticated', 'public.market_source_state', 'SELECT')
      and has_table_privilege('service_role', 'public.market_observations', 'SELECT')
      and has_table_privilege('service_role', 'public.market_observations', 'INSERT')
      and has_table_privilege('service_role', 'public.market_observations', 'UPDATE')
      and has_table_privilege('service_role', 'public.market_source_state', 'SELECT')
      and has_table_privilege('service_role', 'public.market_source_state', 'INSERT')
      and has_table_privilege('service_role', 'public.market_source_state', 'UPDATE')
      and not has_function_privilege('anon', 'public.purge_expired_market_observations()', 'EXECUTE')
      and not has_function_privilege('authenticated', 'public.purge_expired_market_observations()', 'EXECUTE')
      and has_function_privilege('service_role', 'public.purge_expired_market_observations()', 'EXECUTE')
      and exists (
        select 1 from pg_constraint
        where conrelid = 'public.market_observations'::regclass
          and contype = 'u'
          and pg_get_constraintdef(oid) like '%(instrument_id, provider, market_date, quote_basis)%'
      )
      and to_regprocedure('public.verify_market_backup_canary()') is not null
      and not has_function_privilege('anon', 'public.verify_market_backup_canary()', 'EXECUTE')
      and not has_function_privilege('authenticated', 'public.verify_market_backup_canary()', 'EXECUTE')
      and has_function_privilege('service_role', 'public.verify_market_backup_canary()', 'EXECUTE')
    then 'ok' else 'failed' end;
    """
    if _psql(cwd, db_url, query) != "ok":
        raise LocalSupabaseError("schema_or_rls_contract_failed")


def _verify_rest(cwd: Path, env: dict[str, str]) -> None:
    base_url = env.get("API_URL", "")
    service_key = env.get("SERVICE_ROLE_KEY", "")
    anon_key = env.get("ANON_KEY", "")
    if not base_url or not service_key or not anon_key:
        raise LocalSupabaseError("local_api_credentials_missing")

    session = requests.Session()
    instrument = "healthcheck:local-migration"
    observation = {
        "instrument_id": instrument,
        "ticker": "HEALTHCHECK",
        "provider": "healthcheck",
        "source_tier": "backup",
        "market_date": "2099-01-02",
        "price": 1,
        "quote_basis": "healthcheck",
        "quality_status": "verified",
        "payload_hash": "local-migration-test",
        "parser_version": "local-migration-test-v1",
        "expires_at": "2099-01-03T00:00:00Z",
    }
    try:
        created = _rest(
            session, base_url=base_url, key=service_key, method="POST",
            path="/rest/v1/market_observations?select=instrument_id,price",
            json=observation, headers={"Prefer": "return=representation"},
        )
        if created.status_code not in {200, 201}:
            raise LocalSupabaseError("service_role_insert_failed")
        selected = _rest(
            session, base_url=base_url, key=service_key, method="GET",
            path="/rest/v1/market_observations?instrument_id=eq.healthcheck%3Alocal-migration&select=instrument_id,price",
        )
        if selected.status_code != 200 or not isinstance(selected.json(), list) or not selected.json():
            raise LocalSupabaseError("service_role_read_failed")
        updated = _rest(
            session, base_url=base_url, key=service_key, method="PATCH",
            path="/rest/v1/market_observations?instrument_id=eq.healthcheck%3Alocal-migration",
            json={"price": 2}, headers={"Prefer": "return=representation"},
        )
        if updated.status_code not in {200, 204}:
            raise LocalSupabaseError("service_role_update_failed")
        state = _rest(
            session, base_url=base_url, key=service_key, method="POST",
            path="/rest/v1/market_source_state?on_conflict=instrument_id",
            json={
                "instrument_id": instrument, "status": "healthy",
                "consecutive_failures": 0, "fallback_used": False, "circuit_state": "closed",
            }, headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
        )
        if state.status_code not in {200, 201, 204}:
            raise LocalSupabaseError("service_role_state_write_failed")

        anon = _rest(
            session, base_url=base_url, key=anon_key, method="GET",
            path="/rest/v1/market_observations?select=instrument_id&limit=1",
        )
        if anon.status_code in {200, 206}:
            body = anon.json()
            if body:
                raise LocalSupabaseError("anon_read_not_rejected")

        rpc = _rest(
            session, base_url=base_url, key=service_key, method="POST",
            path="/rest/v1/rpc/verify_market_backup_canary", json={},
        )
        if rpc.status_code != 200:
            raise LocalSupabaseError("canary_rpc_failed")
        payload = rpc.json()
        if not isinstance(payload, dict) or payload.get("status") != "rolled_back":
            raise LocalSupabaseError("canary_contract_failed")
        residual = _rest(
            session, base_url=base_url, key=service_key, method="GET",
            path="/rest/v1/market_observations?instrument_id=eq.healthcheck%3Amarket-backup&select=instrument_id",
        )
        if residual.status_code != 200 or residual.json():
            raise LocalSupabaseError("canary_cleanup_failed")
    finally:
        _rest(
            session, base_url=base_url, key=service_key, method="DELETE",
            path="/rest/v1/market_observations?instrument_id=eq.healthcheck%3Alocal-migration",
        )
        _rest(
            session, base_url=base_url, key=service_key, method="DELETE",
            path="/rest/v1/market_source_state?instrument_id=eq.healthcheck%3Alocal-migration",
        )


def run(repo_root: Path) -> dict[str, Any]:
    cli = shutil.which("supabase")
    if not cli:
        raise LocalSupabaseError("supabase_cli_missing")
    migration_source = repo_root / "supabase" / "migrations"
    with tempfile.TemporaryDirectory(prefix="prstk-supabase-") as raw_dir:
        root = Path(raw_dir)
        _check([cli, "init", "--force"], root)
        target = root / "supabase" / "migrations"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(migration_source, target)
        config_path = root / "supabase" / "config.toml"
        config = config_path.read_text(encoding="utf-8")
        project_id = f"prstk-migration-{root.name.removeprefix('prstk-supabase-')}"
        if not re.fullmatch(r"[a-z0-9-]+", project_id):
            raise LocalSupabaseError("temporary_project_id_invalid", stage="supabase:init")
        if not re.search(r"(?m)^project_id\s*=\s*", config):
            raise LocalSupabaseError("temporary_project_id_missing", stage="supabase:init")
        config_path.write_text(
            re.sub(r'(?m)^project_id\s*=\s*"[^"]*"', f'project_id = "{project_id}"', config, count=1),
            encoding="utf-8",
        )

        failure: LocalSupabaseError | None = None
        start_diagnostics: dict[str, Any] | None = None
        cleanup = "not_attempted"
        success_result: dict[str, Any] | None = None
        try:
            start_time = time.monotonic()
            _check([cli, "start"], root, timeout=900)
            _check([cli, "db", "reset", "--local", "--no-seed"], root, timeout=900)
            _check([cli, "db", "push", "--local"], root, timeout=900)
            status = _status_env(_check([cli, "status", "-o", "env"], root, timeout=120))
            _verify_schema(root, status.get("DB_URL", ""))
            _verify_rest(root, status)
            comparison = compare(root, _check([cli, "migration", "list", "--local"], root, timeout=120))
            if comparison["status"] != "ready" or comparison["pending_count"] != 0:
                raise LocalSupabaseError("second_run_has_pending_migrations")
            success_result = {
                "status": "passed",
                "first_run": "applied",
                "second_run": "no_changes",
                "schema": "verified",
                "rls": "verified",
                "service_role": "read_write_verified",
                "canary": "rolled_back_and_clean",
                "production_credentials_used": False,
            }
        except LocalSupabaseError as exc:
            failure = exc
            if exc.stage == "supabase:start":
                start_diagnostics = _capture_start_diagnostics(cli, root, project_id)
                start_diagnostics["elapsed_seconds"] = round(time.monotonic() - start_time, 2)
        finally:
            try:
                stopped = _run([cli, "stop", "--no-backup"], root, timeout=300)
                cleanup = "stopped" if stopped.returncode == 0 else "stop_failed"
                if cleanup == "stop_failed":
                    cleanup = f"stop_failed:{_safe_excerpt(stopped.stderr) or _safe_excerpt(stopped.stdout)}"
            except LocalSupabaseError as exc:
                cleanup = f"cleanup_command_failed:{exc.code}:{exc.stage}:{exc.diagnostic}"

        if failure is not None:
            failure.cleanup = cleanup
            if start_diagnostics:
                failure.diagnostic = json.dumps(
                    {"command_output": failure.diagnostic, "environment": start_diagnostics},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            raise failure
        if cleanup != "stopped":
            raise LocalSupabaseError("temporary_stack_cleanup_failed", stage="supabase:stop", diagnostic=cleanup)
        if success_result is None:
            raise LocalSupabaseError("migration_test_completed_without_result")
        return success_result


def main() -> int:
    try:
        result = run(Path(__file__).resolve().parents[1])
    except LocalSupabaseError as exc:
        result = exc.as_result()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
