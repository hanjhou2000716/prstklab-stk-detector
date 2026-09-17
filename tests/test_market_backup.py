from datetime import date

from src.market_backup import SupabaseMarketObservationStore, backup_quote_within_limit, payload_hash


def test_backup_age_is_bounded_and_never_accepts_future_or_invalid_rows():
    assert backup_quote_within_limit(
        {"quote_date": "2026-09-14", "price": 100},
        expected_market_date=date(2026, 9, 17),
    )
    assert not backup_quote_within_limit(
        {"quote_date": "2026-09-13", "price": 100},
        expected_market_date=date(2026, 9, 17),
    )
    assert not backup_quote_within_limit(
        {"quote_date": "2026-09-18", "price": 100},
        expected_market_date=date(2026, 9, 17),
    )
    assert not backup_quote_within_limit(
        {"quote_date": "2026-09-16", "price": True},
        expected_market_date=date(2026, 9, 17),
    )


def test_payload_hash_uses_normalized_public_fields_only():
    first = {"ticker": "006208", "price": 244.6, "quote_date": "2026-09-16", "private": "a"}
    second = {"ticker": "006208", "price": 244.6, "quote_date": "2026-09-16", "private": "b"}
    assert payload_hash(first) == payload_hash(second)


def test_supabase_upsert_sends_idempotent_private_row():
    calls = []

    class Response:
        content = b"[]"

        def raise_for_status(self):
            return None

        def json(self):
            return []

    class Session:
        def request(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            return Response()

    store = SupabaseMarketObservationStore("https://example.supabase.co", "secret", session=Session())
    result = store.upsert_quote({
        "instrument_id": "twse:006208",
        "ticker": "006208",
        "source_label": "TWSE",
        "source_tier": "official",
        "quote_date": "2026-09-16",
        "price": 244.6,
        "previous_close": 243.5,
        "change": 1.1,
        "change_percent": 0.45,
        "quote_basis": "TWSE 官方日線收盤",
        "currency": "TWD",
        "source_url": "https://openapi.twse.com.tw/",
        "freshness": "recent_close",
    })
    assert result["stored"] is True
    assert calls[0][0] == "POST"
    assert calls[0][2]["params"]["on_conflict"] == "instrument_id,provider,market_date,quote_basis"
    assert "resolution=merge-duplicates" in calls[0][2]["headers"]["Prefer"]


def test_supabase_batch_upsert_sends_one_bounded_array_request():
    calls = []

    class Response:
        content = b"[]"

        def raise_for_status(self):
            return None

        def json(self):
            return []

    class Session:
        def request(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            return Response()

    store = SupabaseMarketObservationStore("https://example.supabase.co", "secret", session=Session())
    quotes = [{
        "instrument_id": "twse:006208",
        "ticker": "006208",
        "source_label": "TWSE",
        "source_tier": "official",
        "quote_date": f"2026-09-{16 - index:02d}",
        "price": 244.6 - index,
        "quote_basis": "TWSE 官方日線收盤",
        "currency": "TWD",
        "freshness": "recent_close",
    } for index in range(2)]

    result = store.upsert_quotes(quotes)

    assert len(result) == 2
    assert len(calls) == 1
    assert isinstance(calls[0][2]["json"], list)
    assert len(calls[0][2]["json"]) == 2
