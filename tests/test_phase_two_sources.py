from urllib.parse import urlparse

from src.phase_two_sources import (
    _macd_state,
    build_phase_two_snapshot,
    fetch_crypto_macd,
    fetch_kofia_credit_margin,
)


def test_macd_detects_bearish_cross():
    # A falling tail after a long rising series produces a deterministic cross.
    state = _macd_state([float(i) for i in range(60)] + [60.0, 55.0])
    assert state["bearish_cross"] is True
    assert state["label"] == "死叉"


def test_phase_two_does_not_collect_retired_fred_or_eia_sources(monkeypatch):
    empty = {"status": "healthy", "data": {}, "health": {"key": "x"}}
    monkeypatch.setattr("src.phase_two_sources.fetch_kofia_credit_margin", lambda: {**empty, "health": {"key": "kofia"}})
    monkeypatch.setattr("src.phase_two_sources.fetch_crypto_macd", lambda: {**empty, "health": {"key": "crypto"}})
    monkeypatch.setattr("src.crypto_spot_sources.fetch_crypto_spot_snapshot", lambda: {**empty, "health": {"key": "spot"}})
    monkeypatch.setattr("src.public_market_secondary.fetch_public_market_secondary", lambda: {**empty, "health": {"key": "secondary"}})

    snapshot = build_phase_two_snapshot()

    assert "fred" not in snapshot
    assert "eia" not in snapshot
    assert {item["key"] for item in snapshot["sources"]} == {"kofia", "crypto", "spot", "secondary"}


def test_kofia_reports_unambiguous_gap(monkeypatch):
    class Response:
        text = "<html>public page without a data table</html>"
        def raise_for_status(self):
            return None

    monkeypatch.setattr("src.phase_two_sources.requests.get", lambda *args, **kwargs: Response())
    result = fetch_kofia_credit_margin()
    assert result["status"] == "data_gap"
    assert result["health"]["status"] == "partial"
    assert result["health"]["state"] == "optional_degraded"


def test_crypto_macd_uses_binance_us_fallback_and_counts_success(monkeypatch):
    rows = [[0, 0, 0, 0, float(index), 0] for index in range(80)]

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def requester(url, **kwargs):
        if urlparse(url).hostname == "api.binance.com":
            raise RuntimeError("blocked")
        return Response(rows)

    monkeypatch.setattr("src.phase_two_sources.requests.get", requester)
    result = fetch_crypto_macd()

    assert result["status"] == "healthy"
    assert result["fallback_used"] is True
    assert result["health"]["item_count"] == 4
    assert all(state["fallback_used"] for values in result["data"].values() for state in values.values())
