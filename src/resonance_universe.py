"""Full-universe adapter for the three-dimensional public research score."""

from __future__ import annotations

import pandas as pd

from src.resonance_research import label, score_bars


def rank_records(records: list[dict], *, min_turnover: float, limit: int = 10) -> pd.DataFrame:
    """Keep liquid, non-overheated observations and rank lower scores first."""
    rows = []
    for record in records:
        bars = record.get("bars")
        if not isinstance(bars, pd.DataFrame) or bars.empty:
            continue
        score = score_bars(bars)
        close = float(bars["Close"].iloc[-1])
        previous = float(bars["Close"].iloc[-2]) if len(bars) > 1 else 0
        turnover = float(close * bars["Volume"].iloc[-1])
        if score is None or score >= 56 or turnover < min_turnover:
            continue
        rows.append({
            "ticker": record["ticker"], "name": record.get("name", record["ticker"]),
            "close": round(close, 2), "change_percent": None if previous == 0 else round((close / previous - 1) * 100, 2),
            "score": score, "status": label(score), "turnover": round(turnover, 2),
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["score", "turnover"], ascending=[True, False]).head(limit).reset_index(drop=True)
