"""Full-universe adapter for the three-dimensional public research score."""

from __future__ import annotations

import pandas as pd

from src.research_contract import latest_quote_context
from src.resonance_research import label, score_bars
from src.resonance_smart_money import smart_money_conditions, smart_money_summary


def rank_records(
    records: list[dict], *, min_turnover: float, benchmark_bars: pd.DataFrame | None, limit: int = 5,
) -> pd.DataFrame:
    """Keep FGI<56 observations with four Smart Money checks, then three-check fallbacks."""
    rows = []
    for record in records:
        bars = record.get("bars")
        if not isinstance(bars, pd.DataFrame) or bars.empty:
            continue
        score = score_bars(bars)
        quote = latest_quote_context(bars)
        if score is None or quote is None or score >= 56 or quote["turnover"] < min_turnover:
            continue
        summary = smart_money_summary(smart_money_conditions(bars, benchmark_bars))
        if int(str(summary["count"])) < 3:
            continue
        rows.append({
            "ticker": record["ticker"], "name": record.get("name", record["ticker"]),
            **quote,
            "score": summary["score"], "fgi_score": score, "status": summary["tier"],
            "conditions_matched": summary["matched_labels"], "condition_count": summary["count"],
            "fgi_status": label(score),
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["condition_count", "score", "turnover"], ascending=[False, False, False]).head(limit).reset_index(drop=True)
