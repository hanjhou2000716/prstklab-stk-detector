from src.market_data import apply_public_market_secondary_crosscheck
from src.public_market_secondary import fetch_public_market_secondary


class FakeResponse:
    text = "Symbol,Date,Time,Open,High,Low,Close,Volume\n^spx,2026-08-01,00:00:00,100,101,99,100.5,123\n"

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "data": {
                "timeAsOf": "Aug 3, 2026",
                "primaryData": {
                    "lastSalePrice": "25,913.90",
                    "percentageChange": "+2.13%",
                },
            }
        }


def test_public_secondary_parses_stooq_close_and_keeps_per_symbol_errors():
    def requester(url, *, params, timeout, headers):
        if params["s"] == "^ndq":
            raise TimeoutError("temporary timeout")
        return FakeResponse()

    result = fetch_public_market_secondary(requester=requester)

    assert result["status"] == "partial"
    assert "S&P 500" in result["quotes"]
    assert result["quotes"]["S&P 500"]["price"] == 100.5
    assert any(error.startswith("NASDAQ:") for error in result["errors"])
    assert result["health"]["item_count"] == 8


def test_public_secondary_uses_nasdaq_fallback_for_composite_indexes():
    def requester(url, *, params, timeout, headers):
        if "stooq.com" in url:
            if params["s"] == "^ndq":
                raise TimeoutError("stooq blocked")
            return FakeResponse()
        assert "api.nasdaq.com/api/quote/comp/info" in url
        return FakeResponse()

    result = fetch_public_market_secondary(requester=requester)

    assert result["status"] == "healthy"
    assert result["quotes"]["NASDAQ"]["price"] == 25913.90
    assert result["quotes"]["NASDAQ"]["source_domain"] == "api.nasdaq.com"
    assert not any(error.startswith("NASDAQ:") for error in result["errors"])
    assert result["health"]["health_class"] == "degraded_with_fallback"
    assert result["health"]["fallback_active"] is True


def test_public_secondary_crosscheck_does_not_replace_primary_price():
    cards = apply_public_market_secondary_crosscheck(
        [
            {
                "ticker": "S&P 500",
                "price": 100.0,
                "quote_date": "2026-08-01",
                "quote_source": "Yahoo Finance public daily quote",
                "source_url": "https://finance.yahoo.com/quote/%5EGSPC",
            }
        ],
        {
            "quotes": {
                "S&P 500": {
                    "ticker": "S&P 500",
                    "price": 100.5,
                    "quote_date": "2026-08-01",
                    "source_url": "https://stooq.com/q/l/?s=%5Espx&f=sd2t2ohlcv&h&e=csv",
                }
            }
        },
    )

    assert cards[0]["price"] == 100.0
    assert cards[0]["cross_checked"] is True
    assert cards[0]["crosscheck_status"] == "已交叉核對"
    assert [source["label"] for source in cards[0]["crosscheck_sources"]] == ["Yahoo", "Stooq"]


def test_public_secondary_crosscheck_labels_nasdaq_fallback():
    cards = apply_public_market_secondary_crosscheck(
        [{"ticker": "NASDAQ", "price": 100.0, "quote_date": "2026-08-01"}],
        {"quotes": {"NASDAQ": {"ticker": "NASDAQ", "price": 100.2, "quote_date": "2026-08-01", "source_domain": "api.nasdaq.com", "source_url": "https://api.nasdaq.com/api/quote/comp/info?assetclass=index"}}},
    )

    assert cards[0]["crosscheck_sources"][1]["label"] == "Nasdaq"


def test_public_secondary_missing_quote_is_explicitly_disclosed():
    cards = apply_public_market_secondary_crosscheck(
        [{
            "ticker": "NIKKEI",
            "price": 40000.0,
            "quote_date": "2026-08-04",
            "quote_source": "Yahoo Finance public daily quote",
            "source_url": "https://finance.yahoo.com/quote/%5EN225",
        }],
        {"quotes": {}},
    )

    assert cards[0]["cross_checked"] is False
    assert cards[0]["crosscheck_status"] == "secondary_unavailable"
    assert cards[0]["crosscheck_reason"] == "secondary_source_unavailable"
    assert cards[0]["expected_sources"] == ["Yahoo", "public-market-secondary"]
    assert [source["label"] for source in cards[0]["crosscheck_sources"]] == [
        "Yahoo", "public-market-secondary"
    ]
