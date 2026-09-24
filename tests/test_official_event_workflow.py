from pathlib import Path


def test_official_event_workflow_is_dispatchable_and_idempotent():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "official-event-monitor.yml").read_text(encoding="utf-8")

    assert "official-event-check" in workflow
    assert "official-event-${{ steps.status.outputs.key }}" in workflow
    assert "official-event-monitor-${{ github.ref }}" in workflow
    assert "cancel-in-progress: false" in workflow
    assert '- cron: "*/5 * * * *"' in workflow
    assert "python -m src.official_event_monitor --send" in workflow
    assert "DASHBOARD_URL" in workflow
    assert "delivered_count" in workflow or "delivery_status" in workflow
    assert "src.delivery_callback" in workflow
    assert "PUBLIC_OBSERVATIONS_URL" in workflow
    assert "PUBLIC_OBSERVATIONS_SHARED_SECRET" in workflow
    assert "DISPATCH_PRIORITY_EVENT_REFS" in workflow
    assert "priority_summary_timeout" in (Path(__file__).resolve().parents[1] / "src" / "official_event_monitor.py").read_text(encoding="utf-8")
    assert "Prepare reconciled Pages artifact" in workflow
    assert "artifact_name: github-pages-reconciled" in workflow
    assert "Save official event diagnostic" in workflow
    assert "official-event-diagnostic-${{ github.run_id }}" in workflow
    assert "retention-days: 14" in workflow
    assert "Fail expected official notification without delivered receipt" in workflow
    assert "steps.status.outputs.should_send == 'true'" in workflow
    assert "DEPLOYMENT_ERROR_CODE" in workflow
    assert "expected_delivery_or_recipient_receipt_missing" in workflow
    assert "Do not resend this event" in workflow


def test_expected_official_notification_only_skips_for_existing_successful_receipt():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "official-event-monitor.yml"
    ).read_text(encoding="utf-8")
    guard = workflow.split(
        "- name: Fail expected official notification without delivered receipt", 1
    )[1]

    assert guard.index('if [ "$CACHE_HIT" = "true" ]') < guard.index(
        'if [ "$QUEUE_STATUS" = "superseded" ] || [ "$PREPARED_CURRENT" != "true" ]'
    )
    assert 'notification_terminal_status: failed' in guard
    assert "expected_notification_superseded_or_stale_without_prior_receipt" in guard
    assert 'echo "::error::Expected official notification was not delivered;' in guard
    assert "exit 1" in guard


def test_gmail_history_dispatches_realtime_monitor_after_new_reviewed_rows():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "gmail-history-sync.yml").read_text(encoding="utf-8")
    assert "contents: write" in workflow
    assert "gmail-sync-result.json" in workflow
    assert "official-event-check" in workflow
    assert "processed" in workflow
    assert "Validate Gmail sync result contract" in workflow
    assert "priority_candidate_count" in workflow
    assert "priority_event_refs" in workflow
    assert "client_payload[priority_event_refs]" in workflow
    assert "priority_recovery_scan_status" in workflow
    assert "gmail-reviewed-observation-or-recovery" in workflow


def test_worker_deploy_publishes_revision_for_health_reconciliation():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "deploy-worker.yml").read_text(encoding="utf-8")
    assert '--var "VERSION:${GITHUB_SHA}"' in workflow

