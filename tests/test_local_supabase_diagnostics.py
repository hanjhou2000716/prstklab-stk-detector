import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts import local_supabase_migration_test as migration_test


def test_check_preserves_sanitized_command_output(monkeypatch):
    monkeypatch.setattr(
        migration_test,
        "_run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["supabase", "start"],
            1,
            "",
            "container unhealthy; service_role_key=secret-value",
        ),
    )

    with pytest.raises(migration_test.LocalSupabaseError) as captured:
        migration_test._check(["supabase", "start"], Path.cwd())

    assert captured.value.code == "command_failed"
    assert captured.value.stage == "supabase:start"
    assert captured.value.exit_code == 1
    assert "container unhealthy" in captured.value.diagnostic
    assert "secret-value" not in captured.value.diagnostic


def test_run_retains_timeout_diagnostics(monkeypatch):
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(
            ["supabase", "start"], 2, output="startup log", stderr=b"registry connection reset"
        )

    monkeypatch.setattr(migration_test.subprocess, "run", timeout)

    with pytest.raises(migration_test.LocalSupabaseError) as captured:
        migration_test._run(["supabase", "start"], Path.cwd(), timeout=2)

    assert captured.value.code == "command_timed_out"
    assert captured.value.stage == "supabase:start"
    assert "registry connection reset" in captured.value.diagnostic


def test_start_diagnostics_keep_running_when_disk_probe_is_unavailable(monkeypatch):
    def disk_error(_path):
        raise PermissionError("disk usage probe denied")

    monkeypatch.setattr(migration_test.shutil, "disk_usage", disk_error)
    monkeypatch.setattr(
        migration_test,
        "_run",
        lambda command, *_args, **_kwargs: subprocess.CompletedProcess(
            command, 0, "diagnostic-ok", "",
        ),
    )

    result = migration_test._capture_start_diagnostics("supabase", Path.cwd(), "prstk-test")

    assert result["project_id"] == "prstk-test"
    assert result["disk_diagnostic_error"] == "PermissionError"
    assert result["supabase_version"]["output"] == "diagnostic-ok"


def test_disposable_stack_is_stopped_even_when_start_fails(tmp_path, monkeypatch):
    root = tmp_path / "prstk-supabase-diagnostic-test"
    root.mkdir()
    migrations = tmp_path / "repository" / "supabase" / "migrations"
    migrations.mkdir(parents=True)
    (migrations / "0001_test.sql").write_text("select 1;", encoding="utf-8")

    class TemporaryDirectory:
        def __enter__(self):
            return str(root)

        def __exit__(self, *_args):
            return False

    def check(command, cwd, *, timeout=600):
        if command[1] == "init":
            config_dir = cwd / "supabase"
            config_dir.mkdir()
            (config_dir / "config.toml").write_text('project_id = "default"\n', encoding="utf-8")
            return ""
        if command[1] == "start":
            raise migration_test.LocalSupabaseError(
                "command_failed", stage="supabase:start", exit_code=1, diagnostic="container unhealthy"
            )
        raise AssertionError(command)

    stop = Mock(return_value=subprocess.CompletedProcess(["supabase", "stop"], 0, "", ""))
    monkeypatch.setattr(migration_test.shutil, "which", lambda _name: "supabase")
    monkeypatch.setattr(migration_test.tempfile, "TemporaryDirectory", lambda **_kwargs: TemporaryDirectory())
    monkeypatch.setattr(migration_test, "_check", check)
    monkeypatch.setattr(migration_test, "_capture_start_diagnostics", lambda *_args: {"fixture": "captured"})
    monkeypatch.setattr(migration_test, "_run", stop)

    with pytest.raises(migration_test.LocalSupabaseError) as captured:
        migration_test.run(tmp_path / "repository")

    assert captured.value.stage == "supabase:start"
    assert captured.value.cleanup == "stopped"
    assert "container unhealthy" in captured.value.diagnostic
    assert stop.call_args.args[0][1:] == ["stop", "--no-backup"]
