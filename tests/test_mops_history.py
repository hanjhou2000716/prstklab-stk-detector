from pathlib import Path

from src.mops_history import (
    MopsPublicClient,
    mops_pristine_history,
    parse_dividend_history,
    parse_eps_report,
    parse_net_income_report,
)


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


def test_mops_client_uses_legacy_public_endpoint_after_redirect_failure():
    client = MopsPublicClient()
    client._report_once = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("redirect blocked"))
    client._legacy_report_once = lambda *args, **kwargs: "<table><tr><td>ok</td></tr></table>"
    assert client.report("t164sb04", "2330", year=114, season=1) == "<table><tr><td>ok</td></tr></table>"
