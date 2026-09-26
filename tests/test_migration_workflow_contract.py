from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_migration_workflow_has_preflight_dry_run_verification_and_redacted_artifact():
    workflow = (ROOT / ".github/workflows/migrate-market-observations.yml").read_text(encoding="utf-8")

    for marker in (
        "SUPABASE_ACCESS_TOKEN",
        "SUPABASE_DB_PASSWORD",
        "SUPABASE_PROJECT_ID",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "mode:",
        "preflight_run_id:",
        "confirmation:",
        "concurrency:",
        "supabase-market-migration-production",
        "cancel-in-progress: false",
        "scripts.market_migration_runner",
        "Final migration gate",
        "actions/upload-artifact",
        "retention-days: 14",
        "run-name: Supabase market migration / ${{ inputs.mode || 'preflight' }} / ${{ github.sha }}",
        "workflow_path:.path",
        "head_sha",
        "created_at",
        "Verify apply still targets current main",
        "--current-main-sha-file",
        "workflow_path:.path",
    ):
        assert marker in workflow

    assert not workflow.startswith("name: Supabase market migration / ${{")
    assert "--jq '{headSha,conclusion,workflowName,createdAt}'" not in workflow

    assert "supabase migration repair" not in workflow
    assert "supabase db reset" not in workflow
    assert "supabase db seed" not in workflow


def test_migration_workflow_preflight_is_warning_only_and_apply_is_final_gate_only():
    workflow = (ROOT / ".github/workflows/migrate-market-observations.yml").read_text(encoding="utf-8")

    assert "continue-on-error: true" in workflow
    assert 'if: always()' in workflow
    assert 'MIGRATION_MODE" = "preflight"' in workflow
    assert 'status" = "warning_blocked"' in workflow
    assert 'status" = "already_verified"' in workflow
    assert 'status" = "applied"' in workflow
    assert "production apply failed" in workflow
    assert "preflight did not produce a diagnostic artifact" in workflow


def test_refresh_dashboard_enables_private_market_backup_without_delivery_secrets():
    workflow = (ROOT / ".github/workflows/refresh-dashboard.yml").read_text(encoding="utf-8")

    assert "SUPABASE_URL: ${{ secrets.SUPABASE_URL }}" in workflow
    assert "SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}" in workflow
    assert 'MARKET_BACKUP_ENABLED: "true"' in workflow
    assert "TELEGRAM_BOT_TOKEN" not in workflow


def test_quality_requires_pinned_actions_syntax_tools_and_local_supabase_integration():
    workflow = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    preflight = (ROOT / "scripts/quality_preflight.py").read_text(encoding="utf-8")
    tool_check = (ROOT / "scripts/check_quality_tools.py").read_text(encoding="utf-8")

    assert "scripts/quality_preflight.py --static" in workflow
    assert "Install pinned actionlint and ShellCheck" in workflow
    assert "scripts/check_quality_tools.py" in preflight
    assert 'ACTIONLINT_VERSION = "1.7.7"' in tool_check
    assert 'SHELLCHECK_VERSION = "0.11.0"' in tool_check
    assert "scripts/local_supabase_migration_test.py" in workflow
    assert "supabase/setup-cli@46f7f98c7f948ad727d22c1e67fab04c223a0520" in workflow


def test_scheduled_brief_preserves_release_gate_diagnostics_after_failure():
    workflow = (ROOT / ".github/workflows/scheduled-brief.yml").read_text(encoding="utf-8")

    assert "Record release gate diagnostics" in workflow
    assert "Save release gate diagnostics" in workflow
    assert "Upload release gate diagnostics" in workflow
    assert "retention-days: 14" in workflow
