from pathlib import Path


def test_manual_dashboard_refresh_persists_the_generated_snapshot():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "refresh-dashboard.yml").read_text(encoding="utf-8")

    assert "contents: write" in workflow
    assert "fetch-depth: 0" in workflow
    assert "DATA_RELEASE_BRANCH: data-release" in workflow
    assert "src.data_release --restore" in workflow
    assert "src.canonical_release_publisher" in workflow
    assert "git push origin HEAD:main" not in workflow
    assert "send_brief" not in workflow
