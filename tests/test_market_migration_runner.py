from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from scripts.market_migration_runner import CommandResult, MigrationRunner, project_ref_fingerprint

ROOT = Path(__file__).resolve().parents[1]
PROJECT_REF = "jpsohtutyaondeyvcjls"


class Response:
    status_code = 200
    ok = True

    def json(self):
        return {"id": PROJECT_REF}


class Session:
    def get(self, *_args, **_kwargs):
        return Response()


def _environment() -> dict[str, str]:
    return {
        "SUPABASE_ACCESS_TOKEN": "access-token-is-not-in-diagnostic",
        "SUPABASE_DB_PASSWORD": "db-password-is-not-in-diagnostic",
        "SUPABASE_PROJECT_ID": PROJECT_REF,
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "service-role-is-not-in-diagnostic",
    }


def _command_runner(command, _cwd, _env):
    if command[:2] == ["supabase", "link"]:
        return CommandResult(0)
    if command[:3] == ["supabase", "migration", "list"]:
        versions = sorted(
            path.name.split("_", 1)[0]
            for path in (ROOT / "supabase" / "migrations").glob("*.sql")
        )
        return CommandResult(0, "\n".join(versions))
    if command[:3] == ["supabase", "db", "push"]:
        return CommandResult(0)
    raise AssertionError(command)


def _verified(**_kwargs):
    return {
        "migration_status": "verified",
        "schema_status": "verified",
        "rls_status": "verified",
        "service_role_read_status": "verified",
        "service_role_write_status": "verified",
        "canary_cleanup_status": "rolled_back",
        "registered_migrations": [],
    }


def test_preflight_missing_credentials_is_warning_and_writes_safe_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.market_migration_runner.verify_market_backup", _verified)
    environment = _environment()
    environment["SUPABASE_ACCESS_TOKEN"] = ""
    runner = MigrationRunner(
        mode="preflight",
        repo_root=ROOT,
        artifact_dir=tmp_path,
        head_sha="abc123",
        ref="refs/heads/main",
        run_id="100",
        environment=environment,
        command_runner=_command_runner,
        session=Session(),
    )

    assert runner.run() == 0
    payload = json.loads((tmp_path / "verification.json").read_text(encoding="utf-8"))
    assert payload["status"] == "warning_blocked"
    assert payload["alert_class"] == "diagnostic_only"
    assert payload["error_code"] == "credential_missing"
    serialized = json.dumps(payload)
    assert "access-token-is-not-in-diagnostic" not in serialized
    assert "db-password-is-not-in-diagnostic" not in serialized
    assert "service-role-is-not-in-diagnostic" not in serialized


def test_preflight_ready_no_changes_is_green_and_has_no_production_alert(monkeypatch, tmp_path):
    monkeypatch.setattr("scripts.market_migration_runner.verify_market_backup", _verified)
    runner = MigrationRunner(
        mode="preflight",
        repo_root=ROOT,
        artifact_dir=tmp_path,
        head_sha="abc123",
        ref="refs/heads/main",
        run_id="101",
        environment=_environment(),
        command_runner=_command_runner,
        session=Session(),
    )

    assert runner.run() == 0
    payload = json.loads((tmp_path / "verification.json").read_text(encoding="utf-8"))
    assert payload["status"] == "ready_no_changes"
    assert payload["alert_class"] == "diagnostic_only"
    assert payload["error_code"] == "none"
    assert payload["pending_migrations"] == []


def test_apply_requires_confirmation_before_any_cli_write(tmp_path):
    calls = []

    def command_runner(command, cwd, env):
        calls.append(command)
        return _command_runner(command, cwd, env)

    runner = MigrationRunner(
        mode="apply",
        repo_root=ROOT,
        artifact_dir=tmp_path,
        head_sha="abc123",
        ref="refs/heads/main",
        run_id="102",
        preflight_run_id="100",
        confirmation="NO",
        environment=_environment(),
        command_runner=command_runner,
        session=Session(),
    )

    assert runner.run() == 1
    payload = json.loads((tmp_path / "verification.json").read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["error_code"] == "confirmation_required"
    assert calls == []


def test_apply_rejects_missing_preflight_without_calling_db_push(tmp_path):
    calls = []

    def command_runner(command, cwd, env):
        calls.append(command)
        return _command_runner(command, cwd, env)

    runner = MigrationRunner(
        mode="apply",
        repo_root=ROOT,
        artifact_dir=tmp_path,
        head_sha="abc123",
        ref="refs/heads/main",
        run_id="103",
        preflight_run_id="999",
        confirmation="APPLY",
        environment=_environment(),
        command_runner=command_runner,
        session=Session(),
    )

    assert runner.run() == 1
    payload = json.loads((tmp_path / "verification.json").read_text(encoding="utf-8"))
    assert payload["error_code"] == "preflight_reference_missing"
    assert calls == []


def test_apply_with_ready_preflight_reports_already_verified_without_db_push(monkeypatch, tmp_path):
    monkeypatch.setattr("scripts.market_migration_runner.verify_market_backup", _verified)
    now = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
    reference_dir = tmp_path / "preflight"
    reference_dir.mkdir()
    (reference_dir / "run-metadata.json").write_text(
        json.dumps({
            "run_id": "100",
            "repository": "hanjhou2000716/prstklab-stk-detector",
            "workflow_path": ".github/workflows/migrate-market-observations.yml",
            "head_sha": "abc123",
            "head_branch": "main",
            "event": "workflow_dispatch",
            "run_attempt": 1,
            "conclusion": "success",
            "created_at": now.isoformat(),
        }),
        encoding="utf-8",
    )
    (reference_dir / "verification.json").write_text(
        json.dumps({
            "mode": "preflight",
            "status": "ready_no_changes",
            "alert_class": "diagnostic_only",
            "run_id": "100",
            "head_sha": "abc123",
            "project_ref_fingerprint": project_ref_fingerprint(PROJECT_REF),
            "verified_at": now.isoformat(),
        }),
        encoding="utf-8",
    )
    calls = []

    def command_runner(command, cwd, env):
        calls.append(command)
        return _command_runner(command, cwd, env)

    runner = MigrationRunner(
        mode="apply",
        repo_root=ROOT,
        artifact_dir=tmp_path / "output",
        preflight_dir=reference_dir,
        head_sha="abc123",
        ref="refs/heads/main",
        run_id="104",
        preflight_run_id="100",
        confirmation="APPLY",
        environment=_environment(),
        command_runner=command_runner,
        session=Session(),
        now=now,
    )

    assert runner.run() == 0
    payload = json.loads((tmp_path / "output" / "verification.json").read_text(encoding="utf-8"))
    assert payload["status"] == "already_verified"
    assert ["supabase", "db", "push"] not in calls
    assert ["supabase", "db", "push", "--dry-run"] in calls


def test_apply_rejects_preflight_when_current_main_changed(tmp_path):
    now = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
    reference_dir = tmp_path / "preflight"
    reference_dir.mkdir()
    (reference_dir / "run-metadata.json").write_text(json.dumps({
        "run_id": "100",
        "repository": "hanjhou2000716/prstklab-stk-detector",
        "workflow_path": ".github/workflows/migrate-market-observations.yml",
        "head_sha": "abc123",
        "head_branch": "main",
        "event": "workflow_dispatch",
        "run_attempt": 1,
        "conclusion": "success",
        "created_at": now.isoformat(),
    }), encoding="utf-8")
    (reference_dir / "verification.json").write_text(json.dumps({
        "mode": "preflight",
        "status": "ready_no_changes",
        "run_id": "100",
        "head_sha": "abc123",
        "project_ref_fingerprint": project_ref_fingerprint(PROJECT_REF),
        "verified_at": now.isoformat(),
    }), encoding="utf-8")
    current_main = tmp_path / "current-main-sha.txt"
    current_main.write_text("different", encoding="utf-8")
    runner = MigrationRunner(
        mode="apply", repo_root=ROOT, artifact_dir=tmp_path / "output",
        preflight_dir=reference_dir, head_sha="abc123", ref="refs/heads/main",
        run_id="104", preflight_run_id="100", confirmation="APPLY",
        current_main_sha_file=current_main, environment=_environment(),
        command_runner=lambda *_args: (_ for _ in ()).throw(AssertionError("CLI must not run")),
        session=Session(), now=now,
    )

    assert runner.run() == 1
    payload = json.loads((tmp_path / "output" / "verification.json").read_text(encoding="utf-8"))
    assert payload["error_code"] == "main_ref_changed"
