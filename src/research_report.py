"""Normalize public-scan artifacts into one browser- and report-friendly shape."""
from __future__ import annotations

from collections import Counter
import ast
import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.price_action import FUNNEL_LABELS, structure_match_score


NOTICE = "不同策略的研究排序不可直接視為同一種分數；本報表僅統一欄位與資料狀態。"


def _value(value: Any) -> Any:
    return None if pd.isna(value) else value.item() if hasattr(value, "item") else value


def _structure_score(value: Any) -> int:
    """Backfill a reproducible structure score for reports created before it existed."""
    if isinstance(value, str):
        try:
            value = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return 0
    if not isinstance(value, list):
        return 0
    by_label = {label: key for key, label in FUNNEL_LABELS.items()}
    return structure_match_score([by_label[label] for label in value if label in by_label])


def normalize_frame(frame: pd.DataFrame, market: str, strategy: str) -> list[dict[str, Any]]:
    """Map a known scan CSV to common fields without fabricating missing data."""
    if frame.empty or "ticker" not in frame.columns:
        return []
    candidates = []
    for rank, (_, row) in enumerate(frame.iterrows(), start=1):
        structure = _value(row.get("funnel_labels"))
        score = _value(row.get("score"))
        if strategy == "price_action" and score is None:
            score = _structure_score(structure)
        candidates.append({
            "market": market,
            "strategy": strategy,
            "rank": rank,
            "ticker": str(row["ticker"]),
            "name": _value(row.get("name")),
            "score": score,
            "close": _value(row.get("close")) if _value(row.get("close")) is not None else _value(row.get("reference_close")),
            "change_percent": _value(row.get("change_percent")),
            "turnover": _value(row.get("turnover")),
            "previous_close": _value(row.get("previous_close")),
            "as_of": _value(row.get("as_of")),
            "signal_labels": _value(row.get("signal_labels")),
            "volume_ratio": _value(row.get("volume_ratio")),
            "range_contraction": _value(row.get("range_contraction")),
            "breakout_20": _value(row.get("breakout_20")),
            "vcp_breakout": _value(row.get("vcp_breakout")),
            "new_high_days": _value(row.get("new_high_days")),
            "fgi_score": _value(row.get("fgi_score")),
            "fgi_status": _value(row.get("fgi_status")),
            "conditions_matched": _value(row.get("conditions_matched")),
            "condition_count": _value(row.get("condition_count")),
            "structure": structure,
            "status": _value(row.get("status")),
            "roe": _value(row.get("roe")),
            "pe": _value(row.get("pe")),
            "payout_ratio": _value(row.get("payout_ratio")),
            "metrics_available": _value(row.get("metrics_available")),
            "moat_review": _value(row.get("moat_review")),
            "value_checks": _value(row.get("value_checks")),
            "strategy_label": _value(row.get("strategy_label")),
            "quality_verified": _value(row.get("quality_verified")),
            "heat_verified": _value(row.get("heat_verified")),
            "verification_gaps": _value(row.get("verification_gaps")),
        })
    return candidates


def build_research_report(sources: list[dict[str, str]]) -> dict[str, Any]:
    """Read named CSV artifacts, disclosing unavailable or empty source files."""
    candidates: list[dict[str, Any]] = []
    sources_status: list[dict[str, Any]] = []
    for source in sources:
        path = Path(source["path"])
        base = {"market": source["market"], "strategy": source["strategy"], "path": str(path)}
        summary_path = source.get("summary_path")
        if summary_path:
            try:
                summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
                base.update({key: summary.get(key) for key in (
                    "requested", "data_complete", "failed", "scan_state",
                    "history_cached", "history_expected", "notice",
                )})
            except (OSError, json.JSONDecodeError):
                pass
        try:
            frame = pd.read_csv(path)
        except (FileNotFoundError, pd.errors.EmptyDataError, UnicodeDecodeError):
            # A completed zero-row scan writes an empty CSV.  Its healthy
            # summary must not be mistaken for a failed research source.
            completed_empty = (
                base.get("scan_state") == "complete"
                and base.get("failed") == 0
                and base.get("data_complete") == base.get("requested")
            )
            status = (
                "建檔中" if base.get("scan_state") == "building"
                else "本次無研究候選" if completed_empty
                else "資料暫時無法取得"
            )
            sources_status.append({**base, "status": status, "candidates": 0})
            continue
        rows = normalize_frame(frame, source["market"], source["strategy"])
        status = "建檔中" if base.get("scan_state") == "building" else ("可用" if rows else "本次無研究候選")
        sources_status.append({**base, "status": status, "candidates": len(rows)})
        candidates.extend(rows)
    counts = Counter(f"{item['market']}:{item['strategy']}" for item in candidates)
    return {
        "schema_version": "2.0",
        "status": "跨市場研究摘要" if candidates else "目前沒有可整合的研究候選",
        "notice": NOTICE,
        "sources": sources_status,
        "candidates": candidates,
        "summary": {"total_candidates": len(candidates), "by_market_strategy": dict(counts)},
    }
