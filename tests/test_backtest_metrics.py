from src.backtest_metrics import performance_metrics


def test_metrics_include_net_series_statistics():
    result = performance_metrics([0.1, -0.05, 0.02], periods_per_year=3, turnover=1.5, benchmark_returns=[0.01, 0.0, 0.01])
    assert result["status"] == "complete"
    assert result["max_drawdown"] < 0
    assert result["turnover"] == 1.5
    assert "alpha_observed_mean" in result


def test_empty_metrics_are_not_zero_performance():
    result = performance_metrics([])
    assert result["status"] == "insufficient_data"
    assert result["cagr"] is None
