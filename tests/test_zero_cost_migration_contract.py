import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_supabase_migration_has_only_backend_tables_and_rls() -> None:
    sql = (ROOT / "supabase/migrations/202608270001_report_jobs.sql").read_text(encoding="utf-8")
    for table in ("report_jobs", "reports", "system_status"):
        assert f"public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
    assert "market_snapshots" not in sql


def test_telegram_subscription_migration_is_private_and_idempotent() -> None:
    sql = (ROOT / "supabase/migrations/202609130001_telegram_subscriptions.sql").read_text(encoding="utf-8")
    assert "public.telegram_subscriptions" in sql
    assert "chat_type = 'private'" in sql
    assert "status in ('active', 'stopped', 'blocked')" in sql
    assert "enable row level security" in sql
    assert "chat_id text primary key" in sql


def test_telegram_migration_workflow_has_prerequisite_result_contract() -> None:
    workflow = (ROOT / ".github/workflows/migrate-telegram-subscribers.yml").read_text(encoding="utf-8")
    assert "workflow_call:" in workflow
    for status in ("applied", "already_applied", "blocked_prerequisite", "failed"):
        assert status in workflow or status in (ROOT / "src/migrate_telegram_subscribers.py").read_text(encoding="utf-8")
    assert "migration_status" in workflow
    assert "prerequisite_status" in workflow
    assert "PRODUCTION_SHA" in workflow
    assert "GITHUB_STEP_SUMMARY" in (ROOT / "src/migrate_telegram_subscribers.py").read_text(encoding="utf-8")
    assert "telegram_subscription_table_missing" in (ROOT / "src/telegram_subscriptions.py").read_text(encoding="utf-8")
    assert "telegram_subscription_request_failed" in (ROOT / "src/migrate_telegram_subscribers.py").read_text(encoding="utf-8")


def test_worker_deploy_requires_safe_subscription_migration() -> None:
    workflow = (ROOT / ".github/workflows/deploy-worker.yml").read_text(encoding="utf-8")
    assert "migrate-telegram-subscribers.yml" in workflow
    assert "needs: migrate_subscriptions" in workflow
    assert "blocked_prerequisite" in workflow


def test_telegram_bootstrap_orders_worker_before_webhook_and_menu() -> None:
    workflow = (ROOT / ".github/workflows/telegram-bootstrap.yml").read_text(encoding="utf-8")
    assert "deploy-worker.yml" in workflow
    assert "configure-telegram-webhook.yml" in workflow
    assert "configure-mini-app.yml" in workflow
    assert "needs: deploy_worker" in workflow


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
    for route in ('"/api/health"', '"/api/report"', '"/api/send"', '"/api/delivery-receipt"', '"/api/creator-delivery-history"', '"/api/telegram-webhook"'):
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
    assert "DELIVERY_RECEIPT_SHARED_SECRET" in worker
    assert "delivery_receipt_events" in worker
    assert 'backend: "supabase"' in worker
    assert "configured: Boolean" in worker
    assert "RECEIPT_HISTORY_UNAVAILABLE" in worker
    assert "TELEGRAM_WEBHOOK_SECRET" in worker
    assert "telegram_subscriptions" in worker
    assert "📡 D.iNV Detector" in worker


def test_gmail_realtime_migration_and_worker_keep_push_separate_from_sync() -> None:
    migration = (ROOT / "supabase/migrations/202609100001_gmail_realtime_processing.sql").read_text(encoding="utf-8")
    for field in (
        "last_push_received_at", "last_sync_started_at", "last_sync_completed_at",
        "last_sync_status", "last_sync_error", "candidate_decided_at",
    ):
        assert field in migration
    assert "'dispatch_requested'" in migration
    assert "'processing'" in migration
    assert "'completed'" in migration
    worker = (ROOT / "worker/src/index.ts").read_text(encoding="utf-8")
    assert "dispatch_status: \"dispatching\"" in worker
    assert "dispatch_status: \"dispatch_requested\"" in worker
    assert "inputs: { history_id: historyId, notify: \"true\" }" in worker
    assert "last_push_received_at: receivedAt" in worker


def test_gmail_sync_recovery_migration_is_private_and_bounded() -> None:
    migration = (ROOT / "supabase/migrations/202609140001_gmail_sync_recovery.sql").read_text(encoding="utf-8")
    assert "public.gmail_sync_health" in migration
    assert "enable row level security" in migration
    for status in ("healthy", "recovered_after_retry", "retry_pending", "persistent_failure"):
        assert status in migration
    assert "record_gmail_sync_failure" in migration
    assert "clear_gmail_sync_failure" in migration
    assert "interval '10 minutes'" in migration
    assert "message_id" not in migration
    workflow = (ROOT / ".github/workflows/gmail-history-sync.yml").read_text(encoding="utf-8")
    for field in ("recovery_status", "request_attempts", "consecutive_failure_count", "cursor_preserved"):
        assert field in workflow
    assert "transient_sync_failure_retry_pending" in workflow


def test_receipt_events_migration_is_idempotent_and_privacy_safe() -> None:
    migration = (ROOT / "supabase/migrations/202608280001_delivery_receipt_events.sql").read_text(encoding="utf-8")
    assert "public.delivery_receipt_events" in migration
    assert "trace_id text not null unique" in migration
    assert "delivery_status in ('delivered', 'partial', 'failed')" in migration
    assert "alter table public.delivery_receipt_events enable row level security" in migration
    assert "chat_id" not in migration


def test_receipt_callback_prefers_worker_over_railway(monkeypatch) -> None:
    from src.delivery_callback import _callback_target

    monkeypatch.setenv("RECEIPT_CALLBACK_URL", "https://worker.example/api/delivery-receipt")
    monkeypatch.setenv("RAILWAY_STATUS_URL", "https://railway.example")
    assert _callback_target() == ("https://worker.example/api/delivery-receipt", "cloudflare_worker")


def test_receipt_event_schema_is_strict_and_machine_readable() -> None:
    schema = json.loads((ROOT / "schemas/delivery-receipt-event.schema.json").read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False
    assert schema["properties"]["receipt_origin"]["const"] == "github_actions"
    assert "trace_id" in schema["required"]
