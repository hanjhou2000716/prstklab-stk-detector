from datetime import UTC, datetime

from src.crypto_spot_sources import fetch_crypto_spot_snapshot
from src.market_data import apply_crypto_spot_crosscheck


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_crypto_spot_fetches_both_public_providers_and_isolates_quotes():
    now_ms = int(datetime(2026, 8, 1, 1, 0, tzinfo=UTC).timestamp() * 1000)

    def requester(url, *, params, timeout, headers):
        assert timeout == 15
        if "binance.com" in url:
            return FakeResponse(
                {
                    "lastPrice": "100.0" if params["symbol"] == "BTCUSDT" else "10.0",
                    "priceChangePercent": "-1.25",
                    "closeTime": now_ms,
                }
            )
        return FakeResponse(
            {
                "bitcoin": {"usd": 100.2, "usd_24h_change": -1.1, "last_updated_at": now_ms // 1000},
                "ethereum": {"usd": 10.01, "usd_24h_change": -1.0, "last_updated_at": now_ms // 1000},
            }
        )

    snapshot = fetch_crypto_spot_snapshot(requester=requester)

    assert snapshot["status"] == "healthy"
    assert set(snapshot["primary"]) == {"BTC", "ETH"}
    assert set(snapshot["secondary"]) == {"BTC", "ETH"}
    assert snapshot["health"]["item_count"] == 4
    assert snapshot["primary"]["BTC"]["source_domain"] == "api.binance.com"


def test_crypto_spot_failure_is_partial_and_does_not_hide_existing_cards():
    def requester(url, *, params, timeout, headers):
        if "binance.com" in url:
            raise TimeoutError("binance unavailable")
        return FakeResponse({"bitcoin": {"usd": 100.0}, "ethereum": {"usd": 10.0}})

    snapshot = fetch_crypto_spot_snapshot(requester=requester)
    cards = apply_crypto_spot_crosscheck(
        [
            {"ticker": "BTC", "name": "Bitcoin", "price": 99.0},
            {"ticker": "ETH", "name": "Ethereum", "price": 9.0},
            {"ticker": "NASDAQ", "price": 100.0},
        ],
        snapshot,
    )

    assert snapshot["status"] == "partial"
    assert all(card["cross_checked"] is False for card in cards[:2])
    assert all(card["ticker"] in {"BTC", "ETH", "NASDAQ"} for card in cards)
    assert cards[0]["crosscheck_status"] == "primary_unavailable"


def test_crypto_spot_retries_transient_provider_failure_once():
    calls = {"binance": 0}

    def requester(url, *, params, timeout, headers):
        if "binance.com" in url:
            calls["binance"] += 1
            if calls["binance"] == 1:
                raise TimeoutError("temporary provider timeout")
            return FakeResponse({"lastPrice": "100", "priceChangePercent": "0.5", "closeTime": 0})
        return FakeResponse({"bitcoin": {"usd": 100.0}, "ethereum": {"usd": 10.0}})

    snapshot = fetch_crypto_spot_snapshot(requester=requester)

    assert calls["binance"] == 3
    assert snapshot["status"] == "healthy"
    assert set(snapshot["primary"]) == {"BTC", "ETH"}


def test_crypto_spot_crosscheck_marks_aligned_prices_confirmed():
    cards = apply_crypto_spot_crosscheck(
        [{"ticker": "BTC", "name": "Bitcoin", "price": 99.0}],
        {
            "primary": {
                "BTC": {
                    "ticker": "BTC",
                    "price": 100.0,
                    "quote_time": "2026-08-01T01:00:00+00:00",
                    "quote_source": "Binance public spot quote",
                    "source_url": "https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT",
                }
            },
            "secondary": {
                "BTC": {
                    "ticker": "BTC",
                    "price": 100.2,
                    "quote_time": "2026-08-01T01:05:00+00:00",
                    "source_url": "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin",
                }
            },
        },
    )

    assert cards[0]["cross_checked"] is True
    assert cards[0]["crosscheck_status"] == "已交叉核對"
    assert {item["label"] for item in cards[0]["crosscheck_sources"]} == {"Binance", "CoinGecko"}
