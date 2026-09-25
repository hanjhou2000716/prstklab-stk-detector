from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def test_pages_deploy_wrapper_uses_exact_identity_and_fails_closed():
    action = (ROOT / ".github" / "actions" / "deploy-pages-retry" / "action.yml").read_text(encoding="utf-8")

    assert "Deploy GitHub Pages with identity verification" in action
    assert "python -m src.pages_deployment" in action
    assert "--mode deploy" in action
    assert "continue-on-error: true" in action
    assert 'default: "180000"' in action
    assert "FALLBACK_URL" in action
    assert "fallback_url" in action
    assert "artifact_name" in action
    assert 'default: "github-pages"' in action
    assert "available:" in action
    assert "pages_deployment_unavailable" in action
    assert "deployment_id" in action
    assert "deployment_status_url" in action
    assert "deployment_status_url_shape" in action
    assert "pages_deployment_status_url_shape" in action
    assert "recoverable:" in action
    assert "request_outcome:" in action
    assert "DEPLOY_RECOVERABLE" in action
    assert "source_revision" in action
    assert "GITHUB_SHA:" not in action
    assert "actions/deploy-pages@" not in action


def test_all_pages_workflows_use_the_retry_wrapper_and_gate_delivery():
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


def test_pages_workflows_do_not_mask_release_contract_failures():
    job_names = {
        "deploy-pages.yml": "  deploy:\n",
        "emergency-alert.yml": "  send-emergency-alert:\n",
        "monitor-health.yml": "  publish-monitor-health:\n",
        "official-event-monitor.yml": "  monitor-send-deploy:\n",
        "refresh-dashboard.yml": "  refresh-and-deploy:\n",
        "scheduled-brief.yml": "  refresh-notify-deploy:\n",
    }
    for name, marker in job_names.items():
        workflow = (WORKFLOWS / name).read_text(encoding="utf-8")
        start = workflow.index(marker)
        section = workflow[start : start + 360]
        assert "continue-on-error: true" not in section, name


def test_delivery_workflows_skip_notifications_when_pages_is_unavailable():
    for name in ("emergency-alert.yml", "official-event-monitor.yml", "scheduled-brief.yml"):
        workflow = (WORKFLOWS / name).read_text(encoding="utf-8")
        assert "steps.deployment.outputs.available == 'true'" in workflow
        assert "Telegram delivery intentionally skipped (fail closed)." in workflow
        gate_start = workflow.index("name: Verify deployed release")
        gate_end = workflow.find("- name:", gate_start + 1)
        gate = workflow[gate_start : gate_end if gate_end > gate_start else None]
        assert "continue-on-error: true" not in gate


def test_market_event_sidecars_use_explicit_research_fallback():
    for name in ("emergency-alert.yml", "monitor-health.yml"):
        workflow = (WORKFLOWS / name).read_text(encoding="utf-8")
        assert "--allow-stale-research" in workflow
        assert "--research-fallback-reason" in workflow
