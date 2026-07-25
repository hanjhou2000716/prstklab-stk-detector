"""Bounded Taiwan-universe Price Action research ranking."""
from __future__ import annotations

import pandas as pd

from src.price_action import PriceActionResearchScanner
from src.price_action import structure_match_score


def rank_records(
    records: list[dict],
    scanner: PriceActionResearchScanner | None = None,
    *,
    min_turnover: float = 5_000_000,
    limit: int = 5,
) -> pd.DataFrame:
    """Keep public-data structure candidates, ranked by match score then turnover."""
    scanner = scanner or PriceActionResearchScanner()
    candidates = []
    for record in records:
        bars = record.get("bars")
        if not isinstance(bars, pd.DataFrame):
            continue
        try:
            result = scanner.scan_daily(bars)
        except (KeyError, ValueError):
            continue
        if result and float(result["turnover"]) >= min_turnover:
            result.setdefault("score", structure_match_score(result.get("matched_funnels", [])))
            candidates.append({"ticker": record["ticker"], "name": record.get("name", record["ticker"]), **result})
    if not candidates:
        return pd.DataFrame()
    return pd.DataFrame(candidates).sort_values(
        ["score", "turnover"], ascending=[False, False]
    ).head(limit).reset_index(drop=True)
