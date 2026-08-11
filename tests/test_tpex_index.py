from src.tpex_index import fetch_tpex_yahoo_chart_fallback, parse_tpex_index, parse_twse_mis_tpex


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
    assert quote["source_label"] == "TPEx"


def test_tpex_index_accepts_container_payload_and_roc_dates():
    quote = parse_tpex_index({"data": [
        {"日期": "1150728", "收盤指數": "352.42"},
        {"日期": "1150729", "收盤指數": "334.24"},
    ]})
    assert quote is not None
    assert quote["name"] == "臺灣櫃買指數"
    assert quote["quote_date"] == "2026-07-29"
    assert quote["change_percent"] == -5.16


def test_tpex_index_keeps_single_official_close_visible():
    quote = parse_tpex_index([{"Date": "20260729", "Close": "334.24"}])
    assert quote is not None
    assert quote["price"] == 334.24
    assert quote["change"] is None


def test_twse_mis_tpex_fallback_parses_official_otc_row():
    quote = parse_twse_mis_tpex({"msgArray": [{
        "c": "o00", "z": "348.59", "y": "327.72",
        "tlong": "1785475980000",
    }]})
    assert quote is not None
    assert quote["name"] == "臺灣櫃買指數"
    assert quote["price"] == 348.59
    assert quote["quote_source"] == "TWSE MIS official OTC index"
    assert quote["source_label"] == "TWSE"
    assert quote["quote_basis"] == "最近收盤"


def test_twse_mis_tpex_accepts_channel_suffix_and_date_time_fallback():
    quote = parse_twse_mis_tpex({"msgArray": [{
        "ch": "o00.tw", "z": "347.85", "y": "326.23",
        "d": "20260731", "t": "13:33:00",
    }]})
    assert quote is not None
    assert quote["price"] == 347.85
    assert quote["quote_date"] == "2026-07-31"


class _FakeYahooResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "chart": {"result": [{
                "timestamp": [1785286800, 1785373200],
                "indicators": {"quote": [{"close": [326.23, 347.85]}]},
            }]}
        }


class _FakeYahooSession:
    def get(self, *args, **kwargs):
        return _FakeYahooResponse()


def test_yahoo_chart_fallback_provides_a_labeled_recent_close():
    quote = fetch_tpex_yahoo_chart_fallback(session=_FakeYahooSession())
    assert quote is not None
    assert quote["ticker"] == "TPEx"
    assert quote["price"] == 347.85
    assert quote["quote_source"] == "Yahoo Finance public chart fallback"
    assert quote["source_label"] == "Yahoo"
    assert quote["data_status"] == "recent_close"
