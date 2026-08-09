from urllib.parse import urlparse

from src.phase_two_sources import (
    _macd_state,
    fetch_crypto_macd,
    fetch_eia_snapshot,
    fetch_fred_snapshot,
    fetch_kofia_credit_margin,
)


def test_macd_detects_bearish_cross():
    # A falling tail after a long rising series produces a deterministic cross.
    state = _macd_state([float(i) for i in range(60)] + [60.0, 55.0])
    assert state["bearish_cross"] is True
    assert state["label"] == "死叉"


def test_fred_never_calls_without_key(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    result = fetch_fred_snapshot()
    assert result["status"] == "missing_api_key"
    assert result["data"] == {}
    assert result["health"]["state"] == "configuration_required"


def test_eia_never_calls_without_key(monkeypatch):
    monkeypatch.delenv("EIA_API_KEY", raising=False)
    result = fetch_eia_snapshot()
    assert result["status"] == "missing_api_key"
    assert result["data"] == {}
    assert result["health"]["state"] == "configuration_required"


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
