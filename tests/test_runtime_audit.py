import json

from src.runtime_audit import audit_artifacts


def _write_valid_artifacts(tmp_path, *, market=None, research=None):
    (tmp_path / "site").mkdir()
    (tmp_path / "market.json").write_text(
        json.dumps(market or {
            "generated_at": "2026-08-02T10:00:00+08:00",
            "scan": {},
            "indices": [{
                "ticker": "TAIEX", "price": 43119.75, "quote_date": "2026-08-01",
                "source_label": "TWSE", "quote_basis_label": "最近收盤", "freshness": "recent_close",
            }],
            "quotes": [],
            "source_health": {"data_gaps": []},
        }, ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / "research.json").write_text(
        json.dumps(research or {
            "schema_version": "2.0",
            "sources": [{"market": "taiwan", "strategy": "value", "scan_state": "complete", "status": "healthy"}],
            "candidates": [],
            "health": {"is_expired": False},
            "generated_at": "2026-08-02T10:00:00+08:00",
        }, ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / "site" / "index.html").write_text("<!doctype html>", encoding="utf-8")


def test_audit_accepts_valid_artifacts_and_reports_gaps_as_warnings(tmp_path):
    _write_valid_artifacts(tmp_path)
    market = json.loads((tmp_path / "market.json").read_text(encoding="utf-8"))
    market["source_health"]["data_gaps"] = [{"key": "fred"}]
    (tmp_path / "market.json").write_text(json.dumps(market), encoding="utf-8")

    report = audit_artifacts(
        market_path=tmp_path / "market.json",
        research_path=tmp_path / "research.json",
        index_path=tmp_path / "site" / "index.html",
    )

    assert report["ok"] is True
    assert report["warnings"] == ["market source gaps: 1"]


def test_audit_rejects_invalid_market_shape(tmp_path):
    _write_valid_artifacts(tmp_path)
    market = json.loads((tmp_path / "market.json").read_text(encoding="utf-8"))
    del market["indices"][0]["quote_basis_label"]
    (tmp_path / "market.json").write_text(json.dumps(market), encoding="utf-8")

    report = audit_artifacts(
        market_path=tmp_path / "market.json",
        research_path=tmp_path / "research.json",
        index_path=tmp_path / "site" / "index.html",
    )

    assert report["ok"] is False
    assert any("quote 1 missing keys" in issue for issue in report["issues"])


def test_audit_rejects_missing_research_artifact(tmp_path):
    _write_valid_artifacts(tmp_path)
    (tmp_path / "research.json").unlink()

    report = audit_artifacts(
        market_path=tmp_path / "market.json",
        research_path=tmp_path / "research.json",
        index_path=tmp_path / "site" / "index.html",
    )

    assert report["ok"] is False
    assert any("research missing" in issue for issue in report["issues"])


def test_production_audit_fails_closed_on_fixture_without_manifest(tmp_path):
    _write_valid_artifacts(tmp_path)
    report = audit_artifacts(
        market_path=tmp_path / "market.json",
        research_path=tmp_path / "research.json",
        index_path=tmp_path / "site" / "index.html",
        manifest_path=tmp_path / "missing-manifest.json",
        require_production=True,
    )

    assert report["ok"] is False
    assert any("production release manifest is required" in issue for issue in report["issues"])
