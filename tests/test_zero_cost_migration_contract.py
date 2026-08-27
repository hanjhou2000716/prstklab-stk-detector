from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_supabase_migration_has_only_backend_tables_and_rls() -> None:
    sql = (ROOT / "supabase/migrations/202608270001_report_jobs.sql").read_text(encoding="utf-8")
    for table in ("report_jobs", "reports", "system_status"):
        assert f"public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
    assert "market_snapshots" not in sql


def test_report_worker_workflow_is_dispatch_only_and_has_no_railway_dependency() -> None:
    workflow = (ROOT / ".github/workflows/report-worker.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch" in workflow
    assert "job_id" in workflow
    assert "SUPABASE_SERVICE_ROLE_KEY" in workflow
    assert "RAILWAY" not in workflow


def test_frontend_does_not_accept_caller_supplied_recipient() -> None:
    client = (ROOT / "site/report-client.js").read_text(encoding="utf-8")
    assert "X-Telegram-Init-Data" in client
    assert "user_id" not in client
    assert "5 * 60 * 1000" in client
    assert "release_id" in client
    assert "snapshot_id" in client
    assert "trace_id" in client


def test_worker_has_security_boundary_and_required_routes() -> None:
    worker = (ROOT / "worker/src/index.ts").read_text(encoding="utf-8")
    for route in ('"/api/health"', '"/api/report"', '"/api/send"'):
        assert route in worker
    assert "verifyTelegramInitData" in worker
    assert "ALLOWED_ORIGINS" in worker
    assert '"access-control-allow-origin": "*"' not in worker
    assert "SUPABASE_SERVICE_ROLE_KEY" in worker
    assert "GITHUB_DISPATCH_TOKEN" in worker
    assert "TELEGRAM_BOT_TOKEN" in worker
    assert "telegramToken" in worker
    assert "recipientHash" in worker
    assert "delivery_receipts" in worker
    assert "retry_after" in worker
