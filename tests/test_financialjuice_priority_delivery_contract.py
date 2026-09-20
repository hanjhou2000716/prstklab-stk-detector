from pathlib import Path


def test_priority_delivery_migration_preserves_private_terminal_state() -> None:
    root = Path(__file__).resolve().parents[1]
    migration = (
        root / "supabase" / "migrations" / "202609200001_financialjuice_priority_delivery.sql"
    ).read_text(encoding="utf-8")

    for field in (
        "delivery_status", "next_retry_at", "last_progress_at",
        "last_blocking_reason", "delivered_at",
    ):
        assert field in migration
    for status in (
        "summary_pending", "ready", "delivery_pending", "delivered",
        "expired", "contract_failed",
    ):
        assert status in migration
    assert "transition_financialjuice_priority_delivery" in migration
    assert "revoke all on table public.financialjuice_priority_pending" in migration
    assert "message_id" not in migration
    assert "telegram_id" not in migration
