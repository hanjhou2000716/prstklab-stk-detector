from src.tpex_index import parse_tpex_index


def test_tpex_index_uses_the_latest_two_official_closes():
    quote = parse_tpex_index([
        {"Date": "20260728", "Close": "352.42", "Change": "-25.67"},
        {"Date": "20260729", "Close": "334.24", "Change": "-18.18"},
    ])
    assert quote is not None
    assert quote["ticker"] == "TPEx"
    assert quote["price"] == 334.24
    assert quote["change"] == -18.18
    assert quote["change_percent"] == -5.16
    assert quote["quote_source"] == "TPEx OpenAPI official close"
