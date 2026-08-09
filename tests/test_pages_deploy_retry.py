from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def test_pages_deploy_wrapper_retries_and_reports_degraded_status():
    action = (ROOT / ".github" / "actions" / "deploy-pages-retry" / "action.yml").read_text(encoding="utf-8")

    assert "actions/deploy-pages@d6db90164ac5ed86f2b6aed7e0febac5b3c0c03e" in action
    assert "continue-on-error: true" in action
    assert "steps.first.outcome == 'failure'" in action
    assert 'default: "120000"' in action
    assert "retry_delay_seconds" in action
    assert "Neither Pages deployment attempt returned a public URL" in action
    assert "available:" in action
    assert "pages_deployment_unavailable" in action
    assert "exit 1" not in action


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
