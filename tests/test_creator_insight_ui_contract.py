from pathlib import Path


def test_creator_insight_panel_is_not_public_but_backend_contract_remains():
    page = Path("site/index.html").read_text(encoding="utf-8")
    app = Path("site/app.js").read_text(encoding="utf-8")
    assert 'href="#creator-section"' not in page
    assert 'id="creator-section"' not in page
    assert 'id="report-actions"' not in page
    assert 'report-client.js' not in page
    assert "renderCreatorInsights(creatorSource)" not in app
    assert "raw_body" not in app
    assert (Path("src/creator_notification.py")).exists()


def test_creator_release_loader_enforces_parent_release_binding():
    app = Path("site/app.js").read_text(encoding="utf-8")
    assert 'creator.parent_release_id || "") !== String(manifest.release_id || "")' in app
    assert 'creator.market_snapshot_id || "") !== String(manifest.market_snapshot_id || "")' in app
    assert 'creator.event_snapshot_id || "") !== String(manifest.event_snapshot_id || "")' in app
    assert 'creator.release_id || "") !== String(manifest.creator_release_id)' in app
