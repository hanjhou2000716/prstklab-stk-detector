from pathlib import Path


def test_official_event_workflow_is_dispatchable_and_idempotent():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "official-event-monitor.yml").read_text(encoding="utf-8")
    terminal = (root / "src" / "notification_terminal.py").read_text(encoding="utf-8")

    assert "official-event-check" in workflow
    assert "official-event-monitor-${{ github.ref }}" not in workflow
    assert "monitor-admission" in workflow
    assert "official-monitor-admission-v1" in workflow
    assert "Bind idempotency lock to the complete selected batch" in workflow
    assert "--timeout-seconds 600" in workflow
    assert "cancel-in-progress: false" in workflow
    assert '- cron: "*/5 * * * *"' in workflow
    assert "--send-batch --prepared --expected-keys-file" in workflow
    assert "--expected-alert-targets-file" in workflow
    assert "--notification-keys-file" in workflow
    assert "official-event-batch-${{ hashFiles('.official-event-batch-keys.json') }}" in workflow
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
    assert "Hand off unresolved official notification to incident reconciliation" in workflow
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
        "- name: Hand off unresolved official notification to incident reconciliation", 1
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
    assert "::warning::Official notification remains unresolved" in guard
    assert "exit 1" not in guard.split("- ", 1)[0]
    assert "$NOTIFICATION_REASON" not in guard


def test_research_source_result_is_attempt_bound_and_uploaded_before_reconciliation():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "unified-research-report.yml").read_text(encoding="utf-8")
    reconciler = (root / "scripts" / "incident_reconciliation.py").read_text(encoding="utf-8")
    assert '"schema_version": "unified-research-terminal-v1"' in workflow
    assert '"business_status": business_status' in workflow
    assert "unified-research-terminal-${{ github.run_id }}-attempt-${{ github.run_attempt }}" in workflow
    assert "if-no-files-found: error" in workflow.split("- name: Upload run-bound research incident result", 1)[1]
    assert '"Unified Taiwan-US research report": (' in reconciler
    assert '"business_status") == "degraded"' in reconciler


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
    assert "dispatch_id=\"gmail-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}\"" in workflow
    assert "Audit official monitor liveness" not in workflow
    incident_workflow = (root / ".github" / "workflows" / "incident-reconciliation.yml").read_text(encoding="utf-8")
    incident_script = (root / "scripts" / "incident_reconciliation.py").read_text(encoding="utf-8")
    assert "Central incident reconciliation" in incident_workflow
    assert 'cron: "*/5 * * * *"' in incident_workflow
    assert "Official macro and price monitor" in incident_workflow
    assert "result = audit_liveness(" in incident_script
    assert "defer_notification_cadence=True" in incident_script
    assert "priority_recovery_scan_status" in workflow
    dispatcher = (root / "scripts" / "official_monitor_dispatch.py").read_text(encoding="utf-8")
    assert "scripts/official_monitor_dispatch.py" in workflow
    assert "gmail-reviewed-observation-or-recovery" in dispatcher
    assert "scheduled_monitor_poll" in dispatcher
    assert "repository_dispatch_monitor_poll" in dispatcher


def test_worker_deploy_publishes_revision_for_health_reconciliation():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "deploy-worker.yml").read_text(encoding="utf-8")
    assert '--var "VERSION:${GITHUB_SHA}"' in workflow
