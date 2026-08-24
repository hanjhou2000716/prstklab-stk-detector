from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PATH = Path(__file__).parents[1] / "railway-monitor" / "email_store.py"
_SPEC = importlib.util.spec_from_file_location("railway_email_store_source_health", _PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
EmailStore = _MODULE.EmailStore


def test_financialjuice_health_projects_priority_and_lineage_without_private_ids(tmp_path: Path) -> None:
    store = EmailStore(tmp_path / "email.sqlite3")
    assert store.claim_observation(
        {
            "gmail_message_id": "private-message-id",
            "observation_id": "obs-1",
            "content_origin": "financialjuice",
            "parse_status": "parsed",
            "parser_version": "test",
            "received_at": "2026-08-24T02:00:00+00:00",
        }
    )
    assert store.save_public_observation(
        {
            "public_safe": True,
            "observation_id": "obs-1",
            "content_origin": "financialjuice",
            "vendor_importance": 9,
            "vendor_priority_notification": True,
            "event_cluster_key": "cluster-1",
            "official_confirmed": False,
            "published_at": "2026-08-24T01:59:00+00:00",
            "release_id": "release-1",
            "snapshot_id": "snapshot-1",
            "source_url": "https://example.invalid/item",
        }
    )

    health = store.source_health()["financialjuice"]
    assert health["status"] == "healthy"
    assert health["importance_gte_8_count"] == 1
    assert health["qualifying_item_count"] == 1
    assert health["pending_cluster_count"] == 1
    assert health["decision"] == "priority_items_ready_for_release_review"
    assert health["last_release_id"] == "release-1"
    assert health["last_snapshot_id"] == "snapshot-1"
    assert health["last_observation_id"] == "obs-1"
    assert health["last_importance_gte_8_at"] == "2026-08-24T01:59:00+00:00"
    assert "gmail_message_id" not in health

