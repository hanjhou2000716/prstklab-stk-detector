from src.twse_quotes import parse_twse_stock_day_all


def test_twse_daily_parser_preserves_official_date_and_signed_change():
    rows = parse_twse_stock_day_all(
        [
            {
                "證券代號": "006208",
                "證券名稱": "富邦台50",
                "收盤價": "244.60",
                "漲跌(+/-)": "+",
                "漲跌價差": "1.10",
                "成交股數": "1000",
            },
            {
                "證券代號": "00685L",
                "證券名稱": "群益臺灣加權正二",
                "收盤價": "11.73",
                "漲跌(+/-)": "+",
                "漲跌價差": "0.18",
            },
        ],
        observed_date="1150916",
    )

    assert rows["006208"]["quote_date"] == "2026-09-16"
    assert rows["006208"]["change"] == 1.1
    assert rows["006208"]["quote_source"] == "TWSE OpenAPI official daily quote"
    assert rows["00685L"]["change_percent"] == 1.56


def test_twse_daily_parser_rejects_invalid_price_and_boolean_values():
    rows = parse_twse_stock_day_all(
        [
            {"證券代號": "A", "收盤價": True, "漲跌價差": "1"},
            {"證券代號": "B", "收盤價": "--", "漲跌價差": "1"},
        ],
        observed_date="20260916",
    )
    assert rows == {}
