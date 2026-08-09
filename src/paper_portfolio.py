"""Public, non-trading paper-observation ledger.

This is deliberately separate from private portfolio risk.  It stores only
research candidates and simulated reference prices that were visible at the
time of publication.  It never places orders and never turns a blocked Advice
Gate into a recommendation.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

from src.production_integration import bind_strategy_provenance


def _price(row: dict[str, Any]) -> float | None:
    value = row.get("close", row.get("price", row.get("simulated_entry_price")))
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


def _observation_date(value: Any) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None


def update_paper_observations(
    records: Iterable[dict[str, Any]],
    history: dict[str, Iterable[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Attach point-in-time paper results when enough later closes exist.

    ``history`` is read-only public OHLC data keyed by ticker.  A horizon is
    completed only after that many *later* observations are available, so a
    missing trading day cannot be mistaken for a completed holding period.
    The function never fills missing returns and never changes the
    ``not_a_trade`` safety marker.
    """
    horizons = {"5d": 5, "20d": 20, "60d": 60}
    updated: list[dict[str, Any]] = []
    for original in records:
        record = dict(original)
        entry = _price(record)
        start = _observation_date(record.get("observed_at"))
        ticker = str(record.get("ticker") or "")
        rows: list[tuple[date, float]] = []
        for item in history.get(ticker, ()):
            if not isinstance(item, dict):
                continue
            observed = _observation_date(item.get("date") or item.get("as_of") or item.get("quote_date"))
            close = _price(item)
            if observed is None or close is None or (start is not None and observed <= start):
                continue
            rows.append((observed, close))
        rows.sort(key=lambda pair: pair[0])
        results: dict[str, float | None] = {}
        if entry is not None and entry != 0:
            for label, offset in horizons.items():
                results[label] = round((rows[offset - 1][1] / entry - 1) * 100, 4) if len(rows) >= offset else None
            moves = [((close / entry) - 1) * 100 for _, close in rows]
            record["max_favorable_excursion"] = round(max(moves), 4) if moves else None
            record["max_adverse_excursion"] = round(min(moves), 4) if moves else None
        else:
            results = {label: None for label in horizons}
            record["max_favorable_excursion"] = None
            record["max_adverse_excursion"] = None
        record["horizons"] = results
        completed = [label for label, value in results.items() if value is not None]
        record["tracking_state"] = "complete" if len(completed) == len(horizons) else "partial" if completed else "pending"
        record["completed_horizons"] = completed
        record["not_a_trade"] = True
        updated.append(record)
    return updated
