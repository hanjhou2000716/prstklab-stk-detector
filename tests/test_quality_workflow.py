from pathlib import Path

WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "quality.yml"


def test_quality_workflow_runs_tests_and_non_network_smoke_validation():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "python -m pip install -r requirements.txt pytest" in workflow
    assert "pytest -q" in workflow
    assert "python -m compileall -q src railway-monitor" in workflow
    assert "python -m src.delivery_smoke_test" in workflow
    assert "python -m src.production_e2e" in workflow
    assert "TELEGRAM_BOT_TOKEN: \"\"" in workflow
    assert "--send" not in workflow


def test_notify_workflow_supports_an_explicit_single_recipient_smoke_test():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "notify.yml").read_text(encoding="utf-8")
    assert "test_chat_id:" in workflow
    assert "inputs.test_chat_id || secrets.TELEGRAM_CHAT_IDS" in workflow
    assert "photo_test:" in workflow
    assert "text acceptance requires an explicit single test_chat_id" in workflow


def test_scheduled_production_workflow_installs_renderer_browser():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scheduled-brief.yml").read_text(encoding="utf-8")
    assert "send-only" in workflow
    assert "requirements-production.txt" in workflow
    assert "playwright install --with-deps chromium" in workflow


def test_manual_scheduled_run_is_publish_only_by_default():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scheduled-brief.yml").read_text(encoding="utf-8")
    assert "notify:" in workflow
    assert "default: false" in workflow
    assert "NOTIFY:" in workflow
    assert "env.NOTIFY == 'true'" in workflow


def test_manual_scheduled_acceptance_can_scope_one_recipient():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scheduled-brief.yml").read_text(encoding="utf-8")
    assert "test_chat_id:" in workflow
    assert "inputs.test_chat_id || secrets.TELEGRAM_CHAT_IDS" in workflow
    assert "FAILED_RECIPIENT_HASHES: ${{ steps.send_brief.outputs.failed_recipient_hashes }}" in workflow
    assert "FAILED_COUNT: ${{ steps.send_brief.outputs.failed_count || '0' }}" in workflow


def test_scheduled_workflow_only_passes_explicit_external_creator_records():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scheduled-brief.yml").read_text(encoding="utf-8")
    assert "CREATOR_RECORDS_PATH" in workflow
    assert "-f \"$CREATOR_RECORDS_PATH\"" in workflow
    assert "--creator-records \"$CREATOR_RECORDS_PATH\"" in workflow


def test_scheduled_market_delivery_is_not_blocked_by_stale_research():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scheduled-brief.yml").read_text(encoding="utf-8")
    send = workflow.split("- name: Send Telegram brief", 1)[1].split("- name: Persist scheduled-brief delivery receipt", 1)[0]
    assert "steps.release_gate.outputs.allowed == 'true' && env.NOTIFY == 'true'" in send
    assert "steps.research_policy.outputs.allow_telegram" not in send
    assert "market delivery continues without research claims" in workflow


def test_scheduled_morning_slot_binds_creator_batch_to_release_manifest():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scheduled-brief.yml").read_text(encoding="utf-8")
    assert 'steps.window.outputs.slot' in workflow
    assert 'arguments+=(--creator-morning-batch)' in workflow


def test_creator_batch_has_dedicated_1030_and_late_recheck_crons():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scheduled-brief.yml").read_text(encoding="utf-8")
    assert 'cron: "30 2 * * 1-5"' in workflow
    assert 'creator_schedule="${{ github.event.schedule }}"' in workflow
    assert '[ "$creator_schedule" = "45 3 * * 1-5" ]' in workflow
    assert '[ "$creator_schedule" = "15 5 * * 1-5" ]' in workflow


def test_scheduled_workflow_exposes_only_sanitized_external_observations_path():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scheduled-brief.yml").read_text(encoding="utf-8")
    assert "EXTERNAL_OBSERVATIONS_PATH" in workflow
    assert "sanitized" in workflow


def test_scheduled_workflow_creator_notification_is_opt_in_and_release_gated():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scheduled-brief.yml").read_text(encoding="utf-8")
    assert "CREATOR_NOTIFICATION_ENABLED" in workflow
    assert "steps.release_gate.outputs.allowed == 'true' && env.CREATOR_NOTIFICATION_ENABLED == 'true'" in workflow
    assert "python -m src.creator_dispatch" in workflow
    assert ">> \"$GITHUB_OUTPUT\"" in workflow
    assert "DELIVERY_RECEIPT_KIND: creator" in workflow


def test_event_production_workflows_install_renderer_browser():
    root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    for name in ("official-event-monitor.yml", "emergency-alert.yml"):
        workflow = (root / name).read_text(encoding="utf-8")
        assert "requirements-production.txt" in workflow
        assert "playwright install --with-deps chromium" in workflow


def test_public_release_smoke_workflow_is_read_only_and_non_delivery():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "public-release-smoke.yml").read_text(encoding="utf-8")
    assert "contents: read" in workflow
    assert "src.public_release_smoke" in workflow
    assert "TELEGRAM" not in workflow


def test_security_workflow_uses_current_pinned_sbom_action():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "security.yml").read_text(encoding="utf-8")
    assert "anchore/sbom-action@e22c389904149dbc22b58101806040fa8d37a610" in workflow
    assert "fallback_sbom.py" in workflow
    assert "steps.syft.outcome == 'failure'" in workflow
