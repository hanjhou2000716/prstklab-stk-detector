from src.taiwan_market_crosscheck import crosscheck_taiex_quote, parse_taifex_txf, parse_twse_taiex


def test_parses_twse_mis_taiex_observation():
    quote = parse_twse_taiex({
        "msgArray": [{"c": "t00", "z": "41600.00", "y": "42000.00", "tlong": "1785301200000"}],
    })
    assert quote is not None
    assert quote["ticker"] == "TAIEX"
    assert quote["change_percent"] == -0.95
    assert quote["source"] == "TWSE MIS 公開市況"


def test_parses_taifex_current_txf_observation():
    quote = parse_taifex_txf({
        "RtData": {"QuoteList": [
            {"SymbolID": "TXF-P", "CLastPrice": "", "CRefPrice": "41603.36", "CDate": "20260728", "CTime": ""},
            {"SymbolID": "TXF-S", "CLastPrice": "40039", "CRefPrice": "41603.36", "CDate": "20260729", "CTime": "133315"},
        ]},
    })
    assert quote is not None
    assert quote["ticker"] == "TXF"
    assert quote["change_percent"] == -3.76


def test_crosscheck_uses_twse_cash_index_when_txf_direction_agrees():
    quote = crosscheck_taiex_quote(
        {"ticker": "TAIEX", "price": 41590, "change_percent": -1.0, "quote_basis": "盤中 5 分鐘"},
        twse={"price": 41600, "previous_close": 42000, "change": -400, "change_percent": -0.95, "quote_date": "2026-07-29", "quote_time": "2026-07-29T10:00:00+08:00"},
        taifex={"price": 41550, "change": -350, "change_percent": -0.84, "quote_date": "2026-07-29", "quote_time": "2026-07-29T10:00:00+08:00"},
    )
    assert quote["price"] == 41600
    assert quote["previous_close"] == 42000
    assert quote["change"] == -400
    assert quote["change_percent"] == -0.95
    assert quote["crosscheck_status"] == "已交叉核對"
    assert quote["quote_delayed"] is False
    assert quote["quote_basis"] == "TWSE 公開市況；TAIFEX 台指期方向核對"
    assert isinstance(quote["crosscheck_sources"], list)
    assert {item["label"] for item in quote["crosscheck_sources"]} == {"TWSE", "TAIFEX"}


def test_crosscheck_blocks_alert_when_cash_and_future_disagree():
    quote = crosscheck_taiex_quote(
        {"ticker": "TAIEX", "price": 41590, "change_percent": -1.0},
        twse={"price": 41600, "change": -400, "change_percent": -0.95, "quote_date": "2026-07-29", "quote_time": "2026-07-29T10:00:00+08:00"},
        taifex={"price": 42000, "change": 300, "change_percent": 0.72, "quote_date": "2026-07-29", "quote_time": "2026-07-29T10:00:00+08:00"},
    )
    assert quote["crosscheck_status"] == "現貨期貨方向不一致"
    assert quote["quote_delayed"] is True
