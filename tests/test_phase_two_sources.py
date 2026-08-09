from src.phase_two_sources import _macd_state, fetch_eia_snapshot, fetch_fred_snapshot, fetch_kofia_credit_margin


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
