"""Public, non-trading paper-observation ledger.

This is deliberately separate from private portfolio risk.  It stores only
research candidates and simulated reference prices that were visible at the
time of publication.  It never places orders and never turns a blocked Advice
Gate into a recommendation.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.production_integration import bind_strategy_provenance


def _price(row: dict[str, Any]) -> float | None:
    value = row.get("close", row.get("price"))
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def build_paper_portfolio_snapshot(
    candidates: Iterable[dict[str, Any]], quotes: Iterable[dict[str, Any]], *,
    release_id: str | None = None,
) -> dict[str, Any]:
    """Create a safe snapshot from currently visible research rows.

    Rows without a valid backtest release stay visible as observations but are
    never represented as an actionable paper position.
    """
    quote_by_ticker = {
        str(row.get("ticker")): row for row in quotes if isinstance(row, dict) and row.get("ticker")
    }
    records: list[dict[str, Any]] = []
    blocked = 0
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        ticker = str(candidate.get("ticker") or "").strip()
        quote = quote_by_ticker.get(ticker, {})
        entry_price = _price(quote)
        binding = bind_strategy_provenance(candidate)
        if binding["state"] != "production" or entry_price is None:
            blocked += 1
            continue
        records.append({
            "ticker": ticker,
            "market": candidate.get("market"),
            "strategy": candidate.get("strategy"),
            "strategy_binding": binding,
            "release_id": release_id,
            "observed_at": quote.get("quote_time") or quote.get("quote_date") or candidate.get("as_of"),
            "simulated_entry_price": entry_price,
            "horizons": {"5d": None, "20d": None, "60d": None},
            "state": "paper_observation",
            "not_a_trade": True,
        })
    state = "available" if records else "observation_only"
    return {
        "state": state,
        "records": records,
        "blocked_candidate_count": blocked,
        "blocking_reason": None if records else "no_candidate_with_valid_backtest_and_quote",
        "disclaimer": "Research simulation only; no order, position, or performance promise.",
    }
