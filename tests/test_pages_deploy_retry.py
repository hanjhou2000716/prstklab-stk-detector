from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def test_pages_deploy_wrapper_retries_and_fails_closed():
    action = (ROOT / ".github" / "actions" / "deploy-pages-retry" / "action.yml").read_text(encoding="utf-8")

    assert "actions/deploy-pages@v4" in action
    assert "continue-on-error: true" in action
    assert "steps.first.outcome == 'failure'" in action
    assert "Neither Pages deployment attempt returned a public URL." in action
    assert "Fail closed when Pages deployment is unavailable" in action


def test_all_pages_workflows_use_the_retry_wrapper_and_fail_closed_manifests():
    pages_workflows = [
        "deploy-pages.yml",
        "emergency-alert.yml",
        "monitor-health.yml",
        "official-event-monitor.yml",
        "refresh-dashboard.yml",
        "scheduled-brief.yml",
    ]

    for name in pages_workflows:
        workflow = (WORKFLOWS / name).read_text(encoding="utf-8")
        assert "uses: ./.github/actions/deploy-pages-retry" in workflow
        assert "actions/deploy-pages@v4" not in workflow
        assert "src.release_manifest ||" not in workflow
