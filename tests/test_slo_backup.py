import json

from src.backup_manifest import build_backup_manifest, verify_backup_manifest
from src.slo_metrics import calculate_slo


def test_slo_metrics_are_explicit():
    result = calculate_slo([{"status": "ok", "freshness": "live", "cross_checked": True, "delivery": "sent", "research_complete": True}, {"status": "failed", "stale_used": True}])
    assert result["source_success_rate"] == 0.5
    assert result["telegram_delivery_rate"] == 0.5
    assert result["stale_quote_rate"] == 0.5


def test_backup_manifest_can_be_verified(tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps({"release": "r1"}), encoding="utf-8")
    manifest = build_backup_manifest([path], created_at="2026-01-01T00:00:00Z")
    assert verify_backup_manifest(manifest)["status"] == "pass"
    path.write_text("changed", encoding="utf-8")
    assert verify_backup_manifest(manifest)["status"] == "failed"
