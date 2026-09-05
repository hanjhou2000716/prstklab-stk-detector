import json
from pathlib import Path

import src.mops_history as mops_history
from src.mops_history import (
    MopsPublicClient,
    mops_pristine_history,
    parse_dividend_history,
    parse_eps_report,
    parse_net_income_report,
)


def test_missing_future_period_does_not_abort_history_walk(monkeypatch):
    monkeypatch.setattr(mops_history, "parse_eps_report", lambda _html: (1.0, 1.0))
    class FuturePeriodMissingClient:
        def report(self, api_name, company_id, **parameters):
            if api_name == "t164sb04" and int(parameters["year"]) == 115 and int(parameters["season"]) == 4:
                raise RuntimeError("MOPS t164sb04 did not return a report URL")
            if api_name == "t164sb04":
                year, quarter = int(parameters["year"]), int(parameters["season"])
                return f"<table><tr><td>?箸瘥??</td><td>{year - 100 + quarter / 10}</td><td>1.0</td></tr></table>"
            return "<table>" + "".join(
                f"<tr><td>{year}</td><td>1</td><td></td><td></td><td>0</td><td>0</td><td>0</td><td>0</td><td>1.0</td></tr>"
                for year in (115, 114, 113)
            ) + "</table>"

    record = mops_history.fetch_pristine_history("2330", client=FuturePeriodMissingClient())
    assert record["history_data_complete"] is True
    assert "115Q4" in record["missing_periods"]


def test_incomplete_history_is_not_cached_as_verified(tmp_path: Path):
    class IncompleteClient:
        def report(self, api_name, company_id, **parameters):
            if api_name == "t164sb04":
                return "<table><tr><td>?箸瘥??</td><td>1.0</td><td>1.0</td></tr></table>"
            raise RuntimeError("MOPS t05st09_1 did not return a report URL")

    path = tmp_path / "mops.json"
    records, errors = mops_pristine_history(["2330"], path, client=IncompleteClient())
    assert records == {}
    assert errors == ["2330 MOPS history: RuntimeError"]
    cached = json.loads(path.read_text(encoding="utf-8"))
    assert "2330" not in cached["records"]
    assert cached["failures"]["2330"]["error"] == "RuntimeError"


def test_parse_eps_report_reads_current_and_comparative_values():
    html = """
    <table><tr><td>基本每股盈餘</td><td>13.95</td><td>8.70</td></tr></table>
    """
    assert parse_eps_report(html) == (13.95, 8.70)


def test_parse_net_income_report_converts_mops_thousands_to_ntd():
    html = "<table><tr><td>本期淨利（淨損）</td><td>360,732,661</td><td>225,221,263</td></tr></table>"
    assert parse_net_income_report(html) == (360_732_661_000, 225_221_263_000)


def test_parse_dividend_history_uses_shareholder_dividend_columns_only():
    html = """
    <table>
      <tr><td>115</td><td>1</td><td>115/05/12</td><td></td><td>999</td><td>999</td><td>999</td><td>999</td><td>7.0</td><td>0</td><td>0</td></tr>
      <tr><td>114</td><td>1</td><td>114/05/13</td><td></td><td>999</td><td>999</td><td>999</td><td>999</td><td>0</td><td>0</td><td>0</td></tr>
    </table>
    """
    assert parse_dividend_history(html) == {115: True, 114: False}


def test_no_dividend_year_is_complete_history_not_provider_failure(monkeypatch):
    """A year-specific MOPS 'no records' page is a valid negative fact."""

    monkeypatch.setattr(mops_history, "parse_eps_report", lambda _html: (1.0, 1.0))

    class NoDividendYearClient:
        def report(self, api_name, company_id, **parameters):
            if api_name == "t164sb04":
                year, quarter = int(parameters["year"]), int(parameters["season"])
                return (
                    "<table><tr><td>?箸瘥??</td>"
                    f"<td>{year - 100 + quarter / 10}</td><td>1.0</td></tr></table>"
                )
            year = int(parameters["year"])
            if year == 113:
                return "<html><body>查無資料</body></html>"
            return (
                "<table><tr><td>"
                f"{year}</td><td>1</td><td></td><td></td><td>0</td><td>0</td>"
                "<td>0</td><td>0</td><td>1.0</td></tr></table>"
            )

    record = mops_history.fetch_pristine_history("7769", client=NoDividendYearClient())
    assert record["history_data_complete"] is True
    assert record["three_year_dividend_paid"] is False
    assert 113 not in record["dividend_years"]


class _FakeClient:
    def report(self, api_name, company_id, **parameters):
        if api_name == "t164sb04":
            year, quarter = int(parameters["year"]), int(parameters["season"])
            return f"<table><tr><td>基本每股盈餘</td><td>{year - 100 + quarter / 10}</td><td>1.0</td></tr><tr><td>本期淨利（淨損）</td><td>2000000</td><td>2000000</td></tr></table>"
        return "<table><tr><td>115</td><td>1</td><td></td><td></td><td>0</td><td>0</td><td>0</td><td>0</td><td>1.0</td></tr><tr><td>114</td><td>1</td><td></td><td></td><td>0</td><td>0</td><td>0</td><td>0</td><td>1.0</td></tr><tr><td>113</td><td>1</td><td></td><td></td><td>0</td><td>0</td><td>0</td><td>0</td><td>1.0</td></tr></table>"


def test_mops_history_uses_cache_after_first_public_fetch(tmp_path: Path):
    path = tmp_path / "mops.json"
    records, errors = mops_pristine_history(["2330"], path, client=_FakeClient())
    assert not errors
    assert records["2330"]["three_year_eps_positive"] is True
    again, errors = mops_pristine_history(["2330"], path, client=_FakeClient())
    assert not errors
    assert again["2330"]["three_year_dividend_paid"] is True


def test_mops_history_caps_attempts_when_reports_fail(tmp_path: Path):
    class FailingClient:
        def report(self, *args, **kwargs):
            raise RuntimeError("temporary MOPS failure")

    records, errors = mops_pristine_history(
        ["1101", "1102", "1103"], tmp_path / "mops.json", max_refresh=2, client=FailingClient()
    )

    assert records == {}
    assert len(errors) == 2


def test_mops_history_skips_recent_failures_and_advances_to_new_tickers(tmp_path: Path):
    class FailingClient:
        def report(self, *args, **kwargs):
            raise RuntimeError("temporary MOPS failure")

    path = tmp_path / "mops.json"
    mops_pristine_history(["1101", "1102", "1103"], path, max_refresh=2, client=FailingClient())
    _, errors = mops_pristine_history(["1101", "1102", "1103"], path, max_refresh=2, client=FailingClient())

    # 1101/1102 remain in a cooldown; the second run tries 1103 instead of
    # burning its batch on the same temporary outage.
    assert len(errors) == 1


def test_mops_history_full_run_retries_recent_failures(tmp_path: Path):
    """A zero refresh limit means verify the whole pool, not skip cooldowns."""

    class FailingClient:
        def report(self, *args, **kwargs):
            raise RuntimeError("temporary MOPS failure")

    path = tmp_path / "mops.json"
    # Seed one recent failure with the bounded/incremental mode.
    mops_pristine_history(["1101"], path, max_refresh=1, client=FailingClient())
    _, errors = mops_pristine_history(["1101"], path, max_refresh=0, client=FailingClient())

    assert errors == ["1101 MOPS history: RuntimeError"]


def test_mops_history_persists_each_ticker_before_later_worker_interrupt(tmp_path: Path, monkeypatch):
    """A bounded worker timeout must not discard earlier verified tickers."""

    path = tmp_path / "mops.json"
    calls = {"count": 0}

    def fake_fetch(ticker, *, client=None, as_of=None):
        calls["count"] += 1
        if calls["count"] == 2:
            # KeyboardInterrupt represents the process being terminated by a
            # host-side timeout; it is intentionally outside the helper's
            # provider-error handling.
            raise KeyboardInterrupt
        return {
            "three_year_eps_positive": True,
            "four_quarter_eps_positive": True,
            "three_year_dividend_paid": True,
            "history_data_complete": True,
        }

    monkeypatch.setattr(mops_history, "fetch_pristine_history", fake_fetch)
    try:
        mops_pristine_history(["1101", "1102"], path, max_refresh=0, client=object())
    except KeyboardInterrupt:
        pass
    else:  # pragma: no cover - the fake must interrupt the first run
        raise AssertionError("the simulated worker interruption did not occur")

    cached = json.loads(path.read_text(encoding="utf-8"))
    assert "1101" in cached["records"]
    assert "1102" not in cached["records"]


def test_mops_period_progress_resumes_after_one_report_failure(monkeypatch):
    """A verified company/report/period is reused after a later period fails."""

    monkeypatch.setattr(mops_history, "REPORT_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(mops_history, "parse_eps_report", lambda _html: (1.0, 1.0))
    monkeypatch.setattr(mops_history, "parse_dividend_history", lambda _html: {115: True, 114: True, 113: True})

    class Client:
        def __init__(self, fail_at: int | None = None):
            self.calls: list[tuple[str, int, int | None]] = []
            self.fail_at = fail_at

        def report(self, api_name, company_id, **parameters):
            year = int(parameters["year"])
            season = int(parameters.get("season")) if parameters.get("season") is not None else None
            self.calls.append((api_name, year, season))
            if self.fail_at is not None and len(self.calls) == self.fail_at:
                raise RuntimeError("temporary MOPS failure")
            return "report"

    progress: dict[str, object] = {}
    first = Client(fail_at=3)
    try:
        mops_history.fetch_pristine_history(
            "2330", client=first, progress=progress, progress_callback=lambda entry: None,
        )
    except RuntimeError:
        pass
    else:  # pragma: no cover - the injected provider failure must interrupt
        raise AssertionError("the simulated period failure did not interrupt the first run")

    verified = [entry for entry in progress.values() if isinstance(entry, dict) and entry.get("status") == "verified"]
    assert len(verified) == 2

    second = Client()
    record = mops_history.fetch_pristine_history(
        "2330", client=second, progress=progress, progress_callback=lambda entry: None,
    )
    assert record["history_data_complete"] is True
    # The two already verified periods are read from progress, not requested
    # again by the resumed run.
    assert second.calls[0][0] == "t164sb04"
    assert len(second.calls) < 12


def test_mops_client_uses_legacy_public_endpoint_after_redirect_failure():
    client = MopsPublicClient()
    client._report_once = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("redirect blocked"))
    client._legacy_report_once = lambda *args, **kwargs: "<table><tr><td>ok</td></tr></table>"
    assert client.report("t164sb04", "2330", year=114, season=1) == "<table><tr><td>ok</td></tr></table>"


def test_mops_client_rotates_session_after_both_public_paths_fail(monkeypatch):
    monkeypatch.setattr(mops_history, "MIN_REQUEST_INTERVAL_SECONDS", 0)
    sleeps: list[float] = []
    monkeypatch.setattr(mops_history.time, "sleep", lambda seconds: sleeps.append(seconds))
    client = MopsPublicClient()
    old_session = client.session
    attempts = {"redirect": 0, "legacy": 0}

    def redirect(*args, **kwargs):
        attempts["redirect"] += 1
        if attempts["redirect"] == 1:
            raise RuntimeError("security block")
        return "redirect-ok"

    def legacy(*args, **kwargs):
        attempts["legacy"] += 1
        raise RuntimeError("legacy security block")

    client._report_once = redirect
    client._legacy_report_once = legacy
    assert client.report("t164sb04", "2330", year=114, season=1) == "redirect-ok"
    assert client.session is not old_session
    assert mops_history.SECURITY_BLOCK_BACKOFF_SECONDS in sleeps
