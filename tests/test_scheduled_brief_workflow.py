from pathlib import Path


def test_duplicate_brief_still_deploys_the_latest_dashboard_files():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scheduled-brief.yml"
    ).read_text(encoding="utf-8")

    assert "The lock deduplicates the Telegram notification" in workflow
    deploy_section = workflow.split("- name: 設定 GitHub Pages", 1)[1]
    assert "steps.idempotency.outputs.cache-hit" not in deploy_section


def test_automatic_scheduled_dispatch_enables_notification_but_manual_stays_opt_in():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scheduled-brief.yml"
    ).read_text(encoding="utf-8")
    assert "github.event_name == 'repository_dispatch' && (github.event.client_payload.notify == false || github.event.client_payload.notify == 'false') && 'false' || 'true'" in workflow
    assert "inputs.notify == true && 'true'" in workflow
    assert "dispatch_unix" in workflow
    assert "dispatch-trace-id" in workflow


def test_gmail_workflow_reports_candidate_rejection_reason_instead_of_no_new_content():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "gmail-history-sync.yml"
    ).read_text(encoding="utf-8")
    assert "accepted_new_but_candidate_rejected:${candidate_reason:-unspecified}" in workflow
    assert "candidate_diagnostics" in workflow
    assert "manual_replay" in workflow
    assert "downstream_dispatch_failure" in workflow
    assert "args+=(--notify \"$NOTIFY\")" in workflow
    assert "notification_status=\"not_requested\"" in workflow
    assert '- cron: "*/5 * * * *"' in workflow


def test_workflow_has_only_four_routine_anchors_and_never_masks_contract_errors():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scheduled-brief.yml"
    ).read_text(encoding="utf-8")
    assert "options: [auto, morning, pre_open, post_close, us_premarket]" in workflow
    assert "send_step_not_run" not in workflow
    assert "Fail closed for invalid schedule context" in workflow
    assert "schedule_contract_version" in workflow
    assert "scheduled_for_at" in workflow


def test_release_policy_writes_outputs_without_corrupting_github_output():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scheduled-brief.yml"
    ).read_text(encoding="utf-8")
    policy = workflow.split("- name: Resolve release publication policy", 1)[1].split(
        "- name: Publish snapshot and manifest", 1
    )[0]

    assert 'Path(os.environ["GITHUB_OUTPUT"]).open("a"' in policy
    assert 'publish = manifest.get("status") in {"ready", "ready_with_quarantine"}' in policy
    assert 'print("::warning::Release manifest is not ready; preserving the previous immutable release.")' in policy
    assert "Publication and research delivery are separate gates" in policy
    assert 'run: |\n          python - <<\'PY\' >> "$GITHUB_OUTPUT"' not in policy


def test_research_policy_marks_stale_content_without_blocking_market_delivery():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scheduled-brief.yml"
    ).read_text(encoding="utf-8")
    policy = workflow.split("- name: Resolve research delivery policy", 1)[1].split(
        "- name: Verify deployed release before delivery", 1
    )[0]

    assert 'Path(os.environ["GITHUB_OUTPUT"]).open("a"' in policy
    assert 'print("::warning::Research is stale or unverified; market delivery continues without research claims.")' in policy
    assert 'output.write("allow_telegram=true\\n")' in policy
    assert 'run: |\n          python - <<\'PY\' >> "$GITHUB_OUTPUT"' not in policy


def test_stale_research_fallback_does_not_block_market_pages_publication():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scheduled-brief.yml"
    ).read_text(encoding="utf-8")
    publication = workflow.split("- name: Resolve release publication policy", 1)[1].split(
        "- name: Publish snapshot and manifest", 1
    )[0]
    research = workflow.split("- name: Resolve research delivery policy", 1)[1].split(
        "- name: Verify deployed release before delivery", 1
    )[0]

    # A stale fallback remains visible and auditable in Pages, while the
    # market delivery path remains eligible without research claims.
    assert 'publish = manifest.get("status") in {"ready", "ready_with_quarantine"}' in publication
    assert 'include_research = freshness == "fresh"' in research
    assert 'allow_telegram=true' in research


def test_scheduled_release_quarantine_is_publishable_and_diagnostic_is_always_uploaded():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scheduled-brief.yml"
    ).read_text(encoding="utf-8")

    assert 'publish = manifest.get("status") in {"ready", "ready_with_quarantine"}' in workflow
    assert "id: release_manifest" in workflow
    assert "python -m src.release_diagnostics" in workflow
    assert "if: always()" in workflow.split("- name: Capture private release preflight diagnostics", 1)[1]
    assert "scheduled-release-preflight-${{ github.run_id }}" in workflow
    assert "optional_fj_alert_quarantined" in workflow
    assert "fj_alert_contract_invalid" in workflow


def test_delivery_claim_persistence_reconciles_the_public_release():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scheduled-brief.yml"
    ).read_text(encoding="utf-8")
    assert "id: persist_notification_ledger" in workflow
    assert "Prepare reconciled Pages artifact" in workflow
    assert "name: github-pages-reconciled" in workflow
    assert "artifact_name: github-pages-reconciled" in workflow
    assert "Verify reconciled public release" in workflow


def test_pages_only_publisher_uses_the_shared_single_writer_queue():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "deploy-pages.yml"
    ).read_text(encoding="utf-8")
    assert "group: main-data-writer-${{ github.run_id }}" in workflow
    assert "python -m src.writer_queue --settle-seconds 0 --poll-seconds 10" in workflow
    assert '"Deploy dashboard to GitHub Pages"' in (
        Path(__file__).resolve().parents[1] / "src" / "writer_queue.py"
    ).read_text(encoding="utf-8")
    assert "Derive Pages build identity from code and data release" in workflow
    assert "--mode derive-version" in workflow
    assert "steps.pages_version.outputs.pages_build_version" in workflow
    assert "Verify completed Pages deployment identity" in workflow
    assert "Verify exact public release after deployment" in workflow
    assert "--expected-release-id" in workflow
    assert "--expected-snapshot-id" in workflow
    assert "pages-release-gate-diagnostics-${{ github.run_id }}" in workflow


def test_scheduled_release_gate_is_identity_bound_bounded_and_fail_closed():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scheduled-brief.yml"
    ).read_text(encoding="utf-8")
    gate = workflow.split("- name: Verify deployed release before delivery", 1)[1].split(
        "- name: Record release gate diagnostics", 1
    )[0]
    assert "--expected-release-id" in gate
    assert "--deployment-id" in gate
    assert "--public-timeout-seconds 180" in gate
    assert "--public-max-delay 20" in gate
    assert "steps.deployment_identity.outputs.verified == 'true'" in gate
    assert "steps.publish_snapshot.outputs.pages_build_version" in workflow
    assert "steps.persist_notification_ledger.outputs.pages_build_version" in workflow
    assert "reconciled_data_release_sha" in workflow
    assert "--manifest \"$MANIFEST_PATH\"" in workflow
    sender = workflow.split("- name: Send Telegram brief after successful publication", 1)[1].split(
        "- name: Publish scheduled notification decision", 1
    )[0]
    assert "steps.release_gate.outputs.allowed == 'true'" in sender
    assert "release_superseded_by_newer_valid_version" in workflow
    assert "release_gate_error_category" in workflow
    assert "pages_deployment_run_id" in workflow
    action = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "actions"
        / "deploy-pages-retry"
        / "action.yml"
    ).read_text(encoding="utf-8")
    assert "GITHUB_SHA:" not in action
    assert "PAGES_BUILD_VERSION: ${{ inputs.build_version || github.sha }}" in action
    assert "--mode deploy" in action
    assert "deployment_status_url" in action
    creator = workflow.split("- name: Send release-gated Creator notifications", 1)[1].split(
        "- name: Summarize Creator notification decision", 1
    )[0]
    assert "steps.reconciled_release_gate.outputs.allowed == 'true'" in creator
    assert "id: reconciled_release_gate" in workflow


def test_scheduled_brief_reports_pages_publish_only_failure_and_blocks_expected_delivery():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scheduled-brief.yml"
    ).read_text(encoding="utf-8")
    decision = workflow.split("- name: Publish scheduled notification decision", 1)[1].split(
        "- name: Persist scheduled-brief delivery receipt", 1
    )[0]

    assert "PUBLISH_REQUESTED: ${{ steps.release_policy.outputs.publish || 'false' }}" in decision
    assert "pages_deployment_${PAGES_DEPLOYMENT_ERROR_CODE:-unavailable}" in decision
    assert "scan_status=\"published_unverified\"" in decision
    assert "pages_publication_status:" in decision
    assert 'if: always() && env.NOTIFY == \'true\' && steps.window.outputs.delivery_intent == \'notify_candidate\'' in workflow

