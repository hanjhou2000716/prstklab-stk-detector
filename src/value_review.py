"""Third-stage public fundamental review for already-screened research candidates."""

from __future__ import annotations

from typing import Any

TW_NET_INCOME_MINIMUM = 5_000_000_000
US_NET_INCOME_MINIMUM = 500_000_000


def metrics_from_info(info: dict[str, Any]) -> dict[str, float | None]:
    def number(key: str) -> float | None:
        value = info.get(key)
        return float(value) if isinstance(value, (int, float)) else None

    return {
        "net_income": number("netIncomeToCommon"),
        "market_cap": number("marketCap"),
        "roe": number("returnOnEquity"),
        "payout_ratio": number("payoutRatio"),
        "pe": number("trailingPE"),
    }


def score_metrics(metrics: dict[str, float | None]) -> int:
    """Score only reproducible public fields; business moat remains manual review."""
    return sum((
        (metrics.get("net_income") or 0) > 500_000_000,
        (metrics.get("market_cap") or 0) > 10_000_000_000,
        (metrics.get("roe") or 0) >= 0.17,
        0.20 <= (metrics.get("payout_ratio") or 0) <= 0.80,
    ))


def quote_from_info(info: dict[str, Any]) -> dict[str, float | None]:
    """Extract a public last price and one-day change without inferring values."""
    def number(*keys: str) -> float | None:
        for key in keys:
            value = info.get(key)
            if isinstance(value, (int, float)):
                return float(value)
        return None

    close = number("currentPrice", "regularMarketPrice")
    previous = number("previousClose", "regularMarketPreviousClose")
    change_percent = (
        None
        if close is None or previous is None or previous == 0
        else round((close / previous - 1) * 100, 2)
    )
    return {"close": close, "change_percent": change_percent}


def review_candidates(candidates: list[dict[str, str]], info_getter: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Enrich a bounded upstream candidate set without scanning every issuer's fundamentals."""
    reviewed, errors = [], []
    for item in candidates:
        try:
            info = info_getter(item["symbol"])
            metrics = metrics_from_info(info)
            quote = quote_from_info(info)
        except Exception:
            errors.append(item["ticker"])
            continue
        reviewed.append({
            "ticker": item["ticker"], "name": item["name"], "score": score_metrics(metrics),
            "metrics_available": sum(value is not None for value in metrics.values()),
            "moat_review": "需人工檢視", **metrics, **quote,
        })
    reviewed.sort(key=lambda item: (item["score"], item["metrics_available"]), reverse=True)
    return reviewed[:5], errors


def score_public_fundamentals(metrics: dict[str, Any], market: str) -> tuple[float, list[str]]:
    """Score disclosed fundamentals without turning a score into an order signal."""
    minimum_income = TW_NET_INCOME_MINIMUM if market == "taiwan" else US_NET_INCOME_MINIMUM
    score, checks = 0.0, []
    net_income = metrics.get("net_income")
    if isinstance(net_income, (int, float)) and net_income >= minimum_income:
        score += 30
        checks.append("規模獲利")
    roe = metrics.get("roe")
    if metrics.get("roe_stable") is True:
        score += 30
        checks.append("三年 ROE 穩定")
    elif isinstance(roe, (int, float)) and roe >= 0.17:
        # A latest-period figure is useful, but must not be labelled three-year stable.
        score += 15
        checks.append("最新 ROE 達標")
    payout = metrics.get("payout_ratio")
    if isinstance(payout, (int, float)) and payout >= 0.20:
        score += 20
        checks.append("現金回饋")
    if metrics.get("pe") not in (None, 0):
        score += 10
        checks.append("本益比可核對")
    if metrics.get("financial_source"):
        score += 10
    return round(min(score, 100), 1), checks


def review_public_pool(
    candidates: list[dict[str, str]],
    fundamentals: dict[str, dict[str, Any]],
    quotes: dict[str, dict[str, Any]],
    market: str,
    limit: int | None = 5,
    allow_missing_supplemental: bool = False,
) -> list[dict[str, Any]]:
    """Build public value observations from an independent constituent pool."""
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        ticker = candidate["ticker"]
        metrics = fundamentals.get(ticker)
        # ROE, net income and P/E are supplemental context for the Taiwan
        # Pristine Value pool.  A TWSE endpoint outage must not prevent a
        # ticker with complete MOPS six-condition data from being evaluated.
        if not metrics and not allow_missing_supplemental:
            continue
        metrics = metrics or {}
        score, checks = score_public_fundamentals(metrics, market)
        quote = quotes.get(candidate["symbol"], {})
        rows.append({
            "ticker": ticker,
            "name": candidate["name"],
            "pool": candidate["pool"],
            "score": score,
            "value_checks": checks,
            "metrics_available": sum(metrics.get(key) is not None for key in ("net_income", "roe", "payout_ratio", "pe")),
            "moat_review": "公開財務條件覆核；護城河仍需人工閱讀年報與產業資料。",
            **metrics,
            **quote,
        })
    rows.sort(key=lambda row: (row["score"], row["metrics_available"], row.get("net_income") or 0), reverse=True)
    return rows[:limit] if limit is not None else rows
