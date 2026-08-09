import json

from src.runtime_audit import audit_artifacts


def test_runtime_audit_reports_production_acceptance_warning(tmp_path):
    site = tmp_path / "site" / "data"
    site.mkdir(parents=True)
    (tmp_path / "site" / "index.html").write_text("<html></html>", encoding="utf-8")
    (site / "market.json").write_text(json.dumps({"generated_at": "now", "scan": {}, "indices": [{"ticker": "X", "price": 1, "quote_date": "2026-08-09", "source_label": "Yahoo", "quote_basis_label": "最近收盤", "freshness": "recent_close"}], "quotes": [], "source_health": {}}), encoding="utf-8")
    (site / "research-report.json").write_text(json.dumps({"schema_version": "2", "sources": [{"market": "taiwan", "strategy": "momentum", "scan_state": "complete", "status": "本次無研究候選"}], "candidates": [], "health": {}, "generated_at": "now"}), encoding="utf-8")
    (site / "event-ledger.json").write_text(json.dumps({"events": []}), encoding="utf-8")
    (site / "release-manifest.json").write_text(json.dumps({"status": "ready", "release_id": "r", "market_snapshot_id": "m", "research_snapshot_id": "q", "event_snapshot_id": "e"}), encoding="utf-8")
    report = audit_artifacts(market_path=site / "market.json", research_path=site / "research-report.json", index_path=tmp_path / "site" / "index.html", manifest_path=site / "release-manifest.json")
    assert report["ok"]
