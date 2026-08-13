from pathlib import Path


def test_pages_is_the_single_release_publisher():
    workflow = Path(".github/workflows/deploy-pages.yml").read_text(encoding="utf-8")
    assert "data_release --restore" in workflow
    assert "refs/heads/data-release:refs/remotes/origin/data-release" in workflow
    assert "git restore --source=origin/data-release" in workflow
    assert 'manifest.get("status") != "ready"' in workflow
    assert "src.release_gate" in workflow
    assert "env -u GITHUB_OUTPUT python -m src.release_gate" in workflow
    assert "--require-production-research" in workflow
    assert "upload-pages-artifact" in workflow
    assert "concurrency:" in workflow


def test_research_publisher_restores_before_writing():
    workflow = Path(".github/workflows/unified-research-report.yml").read_text(encoding="utf-8")
    assert "data_release --restore" in workflow
    assert "data_release --publish" in workflow


def test_scheduled_brief_skips_telegram_for_stale_research_without_failing():
    workflow = Path(".github/workflows/scheduled-brief.yml").read_text(encoding="utf-8")
    assert "Resolve research delivery policy" in workflow
    assert "research_freshness" in workflow
    assert "allow_telegram" in workflow
    assert "steps.research_policy.outputs.allow_telegram == 'true'" in workflow
    assert "Resolve release publication policy" in workflow
    assert "steps.release_policy.outputs.publish == 'true'" in workflow
    assert "RELEASE_MANIFEST_PATH" in workflow
    assert "fallback_url: ${{ env.DASHBOARD_URL }}" in workflow
