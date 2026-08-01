import pandas as pd

from src.pristine_value import heat_metrics, review_pristine_observation_pool, review_pristine_pool


def _row(ticker: str, *, income=6_000_000_000, heat=1, return_3m=0.05):
    return {
        "ticker": ticker,
        "net_income": income,
        "roe": 0.2,
        "roe_stable": True,
        "pe": 15,
        "three_year_eps_positive": True,
        "four_quarter_eps_positive": True,
        "three_year_dividend_paid": True,
        "financial_source": "TWSE/MOPS",
        "average_turnover": heat * 100,
        "average_volume": heat * 100,
        "turnover_rate": heat / 10_000,
        "return_3m": return_3m,
        "volatility": 0.2,
    }


def test_pristine_value_keeps_quality_company_outside_top_heat_decile():
    rows = [_row(f"{index:04d}", heat=index, return_3m=index / 100) for index in range(1, 11)]
    selected = review_pristine_pool(rows, "taiwan")
    assert len(selected) == 5
    assert all(item["strategy_label"] == "璞玉價值" for item in selected)
    assert "0010" not in {item["ticker"] for item in selected}


def test_pristine_value_excludes_missing_required_quality_history():
    row = _row("2330")
    row["three_year_eps_positive"] = None
    assert review_pristine_pool([row], "taiwan") == []


def test_pristine_value_formal_candidate_uses_five_of_six_conditions():
    rows = [_row(f"{index:04d}", heat=index, return_3m=index / 100) for index in range(1, 11)]
    target = rows[0]
    # Make one de-hotting metric a top-decile failure while keeping the other
    # five conditions true and fully verified.
    target["average_turnover"] = 10_000
    selected = review_pristine_pool(rows, "taiwan", limit=10)
    chosen = next(item for item in selected if item["ticker"] == "0001")
    assert chosen["pristine_conditions_matched"] == 5
    assert chosen["pristine_conditions_total"] == 6
    assert chosen["condition_count"] == "5/6"


def test_pristine_value_observation_list_accepts_complete_three_or_four_of_six():
    rows = [_row(f"{index:04d}", heat=index, return_3m=index / 100) for index in range(1, 11)]
    target = rows[0]
    # Two quality passes plus two low-heat metrics make a complete 4/6 row.
    target["average_turnover"] = 10_000
    target["average_volume"] = 10_000
    observations = review_pristine_observation_pool(rows, "taiwan")
    chosen = next(item for item in observations if item["ticker"] == "0001")
    assert chosen["pristine_conditions_matched"] == 4
    assert chosen["condition_count"] == "4/6"


def test_heat_metrics_returns_three_month_public_observations():
    index = pd.date_range("2026-01-01", periods=63, freq="B")
    bars = pd.DataFrame({"Close": range(100, 163), "Volume": [1_000] * 63}, index=index)
    result = heat_metrics(bars, shares_outstanding=100_000)
    assert result["average_turnover"] is not None
    assert result["turnover_rate"] == 0.01
