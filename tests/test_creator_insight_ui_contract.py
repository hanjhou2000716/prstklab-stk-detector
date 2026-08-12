from pathlib import Path


def test_creator_insight_panel_is_safe_and_optional():
    page = Path("site/index.html").read_text(encoding="utf-8")
    app = Path("site/app.js").read_text(encoding="utf-8")
    assert 'id="creator-intelligence"' in page
    assert "const renderCreatorInsights" in app
    assert "snapshot.creator_release || snapshot.creator_public_artifact || snapshot.creator_intelligence" in app
    assert "raw_body" not in app


def test_creator_release_loader_enforces_parent_release_binding():
    app = Path("site/app.js").read_text(encoding="utf-8")
    assert 'creator.parent_release_id || "") !== String(manifest.release_id || "")' in app
    assert 'creator.market_snapshot_id || "") !== String(manifest.market_snapshot_id || "")' in app
    assert 'creator.event_snapshot_id || "") !== String(manifest.event_snapshot_id || "")' in app
    assert 'creator.release_id || "") !== String(manifest.creator_release_id)' in app
