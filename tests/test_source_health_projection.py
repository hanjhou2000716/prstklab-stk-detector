from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PATH = Path(__file__).parents[1] / "railway-monitor" / "source_health_projection.py"
_SPEC = importlib.util.spec_from_file_location("railway_monitor_projection_loader", _PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
project_source_health = _MODULE.project_source_health


def test_source_health_projection_keeps_only_public_creator_and_fj_fields() -> None:
    diagnostics = {
        "store": {
            "source_health": {
                "creator": {
                    "status": "healthy",
                    "last_received_at": "2026-08-21T00:00:00Z",
                    "daily_coverage_count": 2,
                    "last_snapshot_id": "creator-snapshot-1",
                    "last_telegram_delivery_status": "delivered",
                    "raw_body": "never expose",
                    "gmail_message_id": "private-id",
                },
                "financialjuice": {"status": "no_new_content", "importance_gte_8_count": 0},
                "news": {"body": "must not be projected"},
            },
            "raw_body": "never copy",
        }
    }
    result = project_source_health(diagnostics)
    assert set(result) == {"creator", "financialjuice"}
    assert result["creator"]["status"] == "healthy"
    assert result["creator"]["daily_coverage_count"] == 2
    assert result["creator"]["last_snapshot_id"] == "creator-snapshot-1"
    assert result["creator"]["last_telegram_delivery_status"] == "delivered"
    assert "raw_body" not in result
    assert "gmail_message_id" not in result["creator"]


def test_source_health_projection_fails_soft_for_missing_diagnostics() -> None:
    assert project_source_health(None) == {}


def test_source_health_projection_rejects_nested_or_unbounded_values() -> None:
    diagnostics = {
        "store": {
            "source_health": {
                "creator": {
                    "status": {"private": "value"},
                    "received_count": -1,
                    "last_release_id": "x" * 161,
                    "daily_coverage_count": True,
                },
                "financialjuice": {
                    "importance_gte_8_count": "3",
                    "last_importance_gte_8_at": "2026-08-21T00:00:00Z",
                },
            }
        }
    }
    result = project_source_health(diagnostics)
    assert result["creator"] == {}
    assert result["financialjuice"]["importance_gte_8_count"] == 3
    assert result["financialjuice"]["last_importance_gte_8_at"].endswith("Z")
