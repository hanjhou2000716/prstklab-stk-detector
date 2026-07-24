from pathlib import Path


def test_manual_dashboard_refresh_persists_the_generated_snapshot():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "refresh-dashboard.yml").read_text(encoding="utf-8")

    assert "contents: write" in workflow
    assert "fetch-depth: 0" in workflow
    assert "git add site/data/market.json" in workflow
    assert "git push origin HEAD:main" in workflow
    assert "send_brief" not in workflow
