from pathlib import Path


def test_research_workflow_deploys_the_new_research_snapshot_to_pages():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "unified-research-report.yml").read_text(encoding="utf-8")

    assert "group: unified-research-report" in workflow
    assert "types: [unified-research-report]" in workflow
    assert "github.event.client_payload.taiwan_limit" in workflow
    assert "pages: write" in workflow
    assert "id-token: write" in workflow
    assert "actions/upload-pages-artifact@v3" in workflow
    assert "uses: ./.github/actions/deploy-pages-retry" in workflow
    assert "id: deployment" in workflow
    assert "scan_mode" in workflow
    assert "--scan-mode \"$SCAN_MODE\"" in workflow
    assert "isolated artifact only; skipping data-release publication" in workflow


def test_research_workflow_clears_previous_scan_artifacts_and_fails_closed_on_invalid_release():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "unified-research-report.yml").read_text(encoding="utf-8")

    assert "Clear previous research scan artifacts" in workflow
    assert "rm -f data/*-scan*.csv data/*-summary*.json" in workflow
    assert "run: python -m src.release_manifest\n" in workflow
    assert "src.release_manifest ||" not in workflow


def test_post_close_brief_is_scheduled_for_1445_taipei_time():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scheduled-brief.yml").read_text(encoding="utf-8")
    assert 'cron: "45 6 * * 1-5"' in workflow


def test_research_scan_starts_before_post_close_brief_buffer():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "unified-research-report.yml").read_text(encoding="utf-8")
    # 02:00 UTC = 10:00 Asia/Taipei, leaving a buffer for schedule jitter and
    # the bounded historical value scan before the 14:45 release consumer.
    assert "cron: '0 2 * * 1-5'" in workflow
    assert "cron: '30 5 * * 1-5'" not in workflow
