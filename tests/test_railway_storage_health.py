from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "railway-monitor" / "storage_health.py"
SPEC = importlib.util.spec_from_file_location("railway_storage_health_test", MODULE_PATH)
assert SPEC and SPEC.loader
storage_health = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(storage_health)
record_storage_startup = storage_health.record_storage_startup
storage_diagnostics = storage_health.storage_diagnostics


def test_writable_non_mount_is_not_claimed_durable(tmp_path: Path) -> None:
    result = storage_diagnostics(tmp_path / "monitor.sqlite3")

    assert result["state_parent_writable"] is True
    assert result["durable_volume_detected"] is False
    assert result["status"] == "unknown"
    assert result["fail_closed_for_high_risk"] is True


def test_missing_parent_is_unavailable(tmp_path: Path) -> None:
    result = storage_diagnostics(tmp_path / "missing" / "monitor.sqlite3")

    assert result["state_parent_exists"] is False
    assert result["status"] == "unavailable"
    assert result["fail_closed_for_high_risk"] is True


def test_mounted_writable_parent_is_ready(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(storage_health.os.path, "ismount", lambda _path: True)

    result = storage_diagnostics(tmp_path / "monitor.sqlite3")

    assert result["durable_volume_detected"] is True
    assert result["status"] == "ready"
    assert result["fail_closed_for_high_risk"] is False


def test_startup_probe_verifies_continuity_without_exposing_marker(tmp_path: Path) -> None:
    state_path = tmp_path / "monitor.sqlite3"

    first = record_storage_startup(state_path)
    assert first["status"] == "not_verified"
    second = record_storage_startup(state_path)
    assert second["status"] == "verified"
    assert second["previous_started_at"]

    diagnostics = storage_diagnostics(state_path)
    assert diagnostics["restart_continuity"]["status"] == "verified"
    assert "marker_path" not in diagnostics["restart_continuity"]
    assert "process_id" not in diagnostics["restart_continuity"]


def test_invalid_startup_probe_is_visible_and_stays_fail_closed(tmp_path: Path) -> None:
    state_path = tmp_path / "monitor.sqlite3"
    marker = tmp_path / ".prstk-storage-probe.json"
    marker.write_text("not-json", encoding="utf-8")

    diagnostics = storage_diagnostics(state_path)
    assert diagnostics["restart_continuity"] == {
        "status": "failed", "previous_started_at": None, "error": "invalid_marker"
    }
    assert diagnostics["fail_closed_for_high_risk"] is True
