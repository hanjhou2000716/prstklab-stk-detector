from src.market_crosscheck import compare_quotes, quote_provenance


def test_crosscheck_requires_aligned_secondary_quote():
    first = {"price": 100, "quote_time": "2026-08-01T10:00:00+00:00"}
    second = {"price": 100.4, "quote_time": "2026-08-01T10:05:00+00:00"}
    result = compare_quotes(first, second)
    assert result["cross_checked"] is True
    assert compare_quotes(first, None)["cross_checked"] is False


def test_quote_provenance_exposes_basis_and_crosscheck_state():
    result = quote_provenance({"ticker": "TPEx", "quote_source": "TPEx OpenAPI official close", "quote_date": "2026-08-01", "crosscheck_status": "已交叉核對"})
    assert result["source_label"] == "TPEx"
    assert result["quote_basis"] == "最近收盤"
    assert result["cross_checked"] is True


def test_quote_provenance_normalizes_legacy_provider_map_to_array():
    result = quote_provenance({
        "ticker": "TAIEX",
        "quote_source": "TWSE MIS cash index",
        "quote_date": "2026-08-01",
        "crosscheck_sources": {
            "twse": {"quote_date": "2026-08-01", "price": 100},
            "taifex": {"quote_date": "2026-08-01", "price": 101},
        },
    })
    assert isinstance(result["crosscheck_sources"], list)
    assert {item["label"] for item in result["crosscheck_sources"]} == {"TWSE", "TAIFEX"}


def test_daily_close_dates_can_be_cross_checked():
    result = compare_quotes(
        {"price": 100, "quote_date": "2026-08-01"},
        {"price": 100.2, "quote_date": "2026-08-01"},
        max_age_minutes=24 * 60,
    )
    assert result["cross_checked"] is True


def test_quote_provenance_accepts_canonical_confirmation_statuses():
    for status in ("confirmed", "verified", "已交叉核對"):
        result = quote_provenance({
            "ticker": "NASDAQ",
            "quote_source": "Yahoo public quote",
            "quote_date": "2026-08-01",
            "crosscheck_status": status,
        })
        assert result["cross_checked"] is True


def test_quote_provenance_does_not_treat_pending_status_as_confirmed():
    result = quote_provenance({
        "ticker": "NASDAQ",
        "quote_source": "Yahoo public quote",
        "quote_date": "2026-08-01",
        "crosscheck_status": "pending",
    })
    assert result["cross_checked"] is False

