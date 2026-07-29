"""Manual, bounded Taiwan-universe momentum research scan."""
from __future__ import annotations
import pandas as pd
from src.momentum_research import features, WEIGHTS

TAIWAN_MIN_TURNOVER = 30_000_000


def rank_records(records: list[dict], min_turnover: float = TAIWAN_MIN_TURNOVER, limit: int = 5) -> pd.DataFrame:
    rows = []
    for record in records:
        df = record.get("bars")
        result = features(df) if isinstance(df, pd.DataFrame) else None
        if not result or result["turnover"] < min_turnover or not result["above_ma5"]:
            continue
        rows.append({**record, **result})
    if not rows: return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame["score"] = sum(frame[key].rank(pct=True) * weight for key, weight in WEIGHTS.items()) / sum(WEIGHTS.values()) * 100
    return frame.sort_values(["score", "vcp_breakout", "volume_ratio"], ascending=[False, False, False]).head(limit).reset_index(drop=True)
