from pathlib import Path


def test_official_event_workflow_is_dispatchable_and_idempotent():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "official-event-monitor.yml").read_text(encoding="utf-8")
    terminal = (root / "src" / "notification_terminal.py").read_text(encoding="utf-8")

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
    assert "expected_delivery_or_persistent_recipient_receipt_missing" in terminal
    assert "post_send_public_release_not_reconciled_do_not_resend" in terminal
    assert "Fail on blocked notification preflight" in workflow
    assert "steps.status.outputs.hard_failure == 'true'" in workflow
    assert "notification_preflight_reason" in workflow
    assert "candidate_content_status" in workflow


def test_official_workflow_uses_shared_terminal_classifier_and_durable_receipts():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "official-event-monitor.yml").read_text(encoding="utf-8")
    terminal = (root / "src" / "notification_terminal.py").read_text(encoding="utf-8")

    diagnostic = workflow.split("- name: Save official event diagnostic", 1)[1].split(
        "- name: Upload official event diagnostic", 1
    )[0]
    guard = workflow.split(
        "- name: Fail expected official notification without delivered receipt", 1
    )[1]

    assert "id: terminal_diagnostic" in diagnostic
    assert "evaluate_official_terminal" in diagnostic
    assert "IDEMPOTENCY_CACHE_HIT" in diagnostic
    assert "SCAN_STATUS:" in diagnostic
    assert "RECEIPT_OUTCOME" in diagnostic
    assert "LEDGER_OUTCOME" in diagnostic
    assert "RECONCILED_RELEASE_GATE_OUTCOME" in diagnostic
    assert "idempotency_cache_without_durable_recipient_receipt" in terminal
    assert "expected_delivery_or_persistent_recipient_receipt_missing" in terminal
    assert "steps.terminal_diagnostic.outputs.terminal_failure == 'true'" in guard
    assert "$NOTIFICATION_REASON" not in guard


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
