from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "railway-monitor" / "storage_health.py"
SPEC = importlib.util.spec_from_file_location("railway_storage_health_test", MODULE_PATH)
assert SPEC and SPEC.loader
storage_health = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(storage_health)
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
