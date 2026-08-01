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

