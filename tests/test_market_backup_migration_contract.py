from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_market_backup_migration_is_private_idempotent_and_bounded():
    sql = (ROOT / "supabase/migrations/202609170001_market_observation_backup.sql").read_text(encoding="utf-8")
    assert "public.market_observations" in sql
    assert "public.market_source_state" in sql
    assert "create table if not exists" in sql
    assert "unique (instrument_id, provider, market_date, quote_basis)" in sql
    assert "enable row level security" in sql
    assert "revoke all on public.market_observations from anon, authenticated" in sql
    assert "market_observations_id_seq" in sql
    assert "purge_expired_market_observations" in sql
