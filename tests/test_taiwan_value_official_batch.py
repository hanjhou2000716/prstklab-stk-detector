import json

from src.pristine_value import review_pristine_pool
from src.value_fundamentals import (
    TW_VALUE_RULE_VERSION,
    twse_current_quality_snapshot,
)


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _Client:
    headers = {}

    def __init__(self, payload=None, error=False):
        self.payload = payload or [{
            "公司代號": "2330", "公司名稱": "台積電", "年度": "115", "季別": "2",
            "出表日期": "1150814", "基本每股盈餘（元）": "1.2",
            "本期淨利（淨損）": "1,000",
            "權益總計": "10,000",
        }]
        self.error = error
        self.calls = []

    def get(self, url, **_):
        self.calls.append(url)
        if self.error:
            raise OSError("offline")
        return _Response(self.payload)


def test_official_batch_reads_all_endpoints_once_and_calculates_current_quality(tmp_path):
    client = _Client()
    records, errors, diagnostics = twse_current_quality_snapshot(
        ["2330"], client, cache_path=tmp_path / "official.json",
    )

    assert errors == []
    assert len(client.calls) == 12
    record = records["2330"]
    assert record["quality_rule_version"] == TW_VALUE_RULE_VERSION
    assert record["current_eps_positive"] is True
    assert record["annualized_quality_ratio"] == 0.2
    assert record["current_quality_pass"] is True
    assert record["total_net_income_ytd"] == 1_000_000
    assert record["total_equity"] == 10_000_000
    assert diagnostics["mops_calls"] == 0
    assert diagnostics["mops_history_used"] is False
    assert json.loads((tmp_path / "official.json").read_text(encoding="utf-8"))["records"]["2330"]["source_sha256"]


def test_official_batch_never_substitutes_wrong_equity_column_for_total_equity():
    client = _Client(payload=[{
        "公司代號": "2330", "年度": "115", "季別": "2",
        "基本每股盈餘（元）": "1.2",
        "本期淨利（淨損）": "1,000",
        "權益總額": "10,000",
    }])
    records, _errors, _diagnostics = twse_current_quality_snapshot(["2330"], client)

    assert records["2330"]["current_quality_pass"] is None


def test_official_batch_reuses_recent_same_period_cache_without_refreshing_time(tmp_path):
    cache = tmp_path / "official.json"
    first_client = _Client()
    first, _errors, _diagnostics = twse_current_quality_snapshot(["2330"], first_client, cache_path=cache)
    checked_at = json.loads(cache.read_text(encoding="utf-8"))["records"]["2330"]["last_checked_at"]

    second, errors, diagnostics = twse_current_quality_snapshot(
        ["2330"], _Client(error=True), cache_path=cache,
        expected_period=first["2330"]["reporting_period"],
    )

    assert second["2330"]["cache_used"] is True
    assert diagnostics["cache_used_count"] == 1
    assert errors
    assert json.loads(cache.read_text(encoding="utf-8"))["records"]["2330"]["last_checked_at"] == checked_at


def _quality_row(ticker: str, *, eps: bool = True, quality: bool = True, ratio: float = 0.2):
    return {
        "market": "taiwan", "ticker": ticker, "name": ticker,
        "quality_rule_version": TW_VALUE_RULE_VERSION,
        "current_eps_positive": eps, "current_quality_pass": quality,
        "annualized_quality_ratio": ratio,
        "financial_source": "TWSE official batch",
        "average_turnover_percentile": 50,
        "average_volume_percentile": 50,
        "turnover_rate_percentile": 50,
        "return_3m_percentile": 50,
    }


def test_current_quality_requires_both_quality_conditions_even_at_five_of_six():
    row = _quality_row("2330", eps=False)
    assert review_pristine_pool([row], "taiwan", rule_version=TW_VALUE_RULE_VERSION) == []


def test_current_quality_boundary_17_percent_is_included_but_16_99_is_not():
    below = _quality_row("2330", ratio=0.1699, quality=False)
    at = _quality_row("2317", ratio=0.17, quality=True)
    selected = review_pristine_pool([below, at], "taiwan", rule_version=TW_VALUE_RULE_VERSION)

    assert [item["ticker"] for item in selected] == ["2317"]
