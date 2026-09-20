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
        "scripts/market_migration_runner.py",
        "Final migration gate",
        "actions/upload-artifact",
        "retention-days: 14",
    ):
        assert marker in workflow

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
