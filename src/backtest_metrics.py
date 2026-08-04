"""Formal walk-forward performance metrics with honest missing-data handling."""

from __future__ import annotations

import math
from typing import Any, Sequence


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def performance_metrics(returns: Sequence[float], *, periods_per_year: int = 252, turnover: float = 0.0, benchmark_returns: Sequence[float] | None = None) -> dict[str, Any]:
    values = [float(value) for value in returns]
    if not values:
        return {"status": "insufficient_data", "cagr": None, "volatility": None, "sharpe": None, "sortino": None, "max_drawdown": None, "calmar": None, "hit_rate": None, "turnover": turnover}
    equity = 1.0
    curve = [equity]
    for value in values:
        equity *= 1.0 + value
        curve.append(equity)
    years = len(values) / periods_per_year
    cagr = equity ** (1 / years) - 1 if years > 0 and equity > 0 else None
    mean = _mean(values)
    variance = _mean([(value - mean) ** 2 for value in values])
    volatility = math.sqrt(variance) * math.sqrt(periods_per_year)
    sharpe = mean / math.sqrt(variance) * math.sqrt(periods_per_year) if variance > 0 else None
    downside = [min(0.0, value) ** 2 for value in values]
    downside_dev = math.sqrt(_mean(downside)) * math.sqrt(periods_per_year)
    sortino = mean * periods_per_year / downside_dev if downside_dev > 0 else None
    peak = curve[0]
    drawdowns: list[float] = []
    for value in curve:
        peak = max(peak, value)
        drawdowns.append(value / peak - 1.0)
    max_drawdown = min(drawdowns)
    calmar = cagr / abs(max_drawdown) if cagr is not None and max_drawdown < 0 else None
    result = {"status": "complete", "cagr": cagr, "volatility": volatility, "sharpe": sharpe,
              "sortino": sortino, "max_drawdown": max_drawdown, "calmar": calmar,
              "hit_rate": sum(value > 0 for value in values) / len(values), "turnover": float(turnover),
              "worst_period": min(values), "recovery_periods": _recovery_periods(curve), "observations": len(values)}
    if benchmark_returns is not None:
        benchmark = [float(value) for value in benchmark_returns[:len(values)]]
        active = [a - b for a, b in zip(values, benchmark)]
        result["alpha_observed_mean"] = _mean(active)
        result["benchmark_observations"] = len(benchmark)
    return result


def _recovery_periods(curve: list[float]) -> int | None:
    peak = curve[0]
    longest = current = 0
    for value in curve:
        if value >= peak:
            peak = value
            current = 0
        else:
            current += 1
            longest = max(longest, current)
    return longest
