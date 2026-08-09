"""Normalize public-scan artifacts into one browser- and report-friendly shape."""
from __future__ import annotations

import ast
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from src.price_action import FUNNEL_LABELS, structure_match_score

NOTICE = "不同策略的研究排序不可直接視為同一種分數；本報表僅統一欄位與資料狀態。"


def _value(value: Any) -> Any:
    return None if pd.isna(value) else value.item() if hasattr(value, "item") else value


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _bounded_candidate_count(value: Any, visible: int) -> int | None:
    """Keep summary counts consistent with the rows actually published.

    A scan summary can be written just before its CSV is interrupted or
    replaced.  Carrying its old formal/observation count into a report with
    zero visible rows creates an invalid release (for example 5 formal rows
    with 0 candidates).  Suppress, rather than invent, counts that cannot be
    proven by the current CSV.
    """
    count = _int_or_none(value)
    if count is None:
        return None
    return max(0, min(count, visible))


def _candidate_state(*, scan_state: str | None, visible: int, data_gap: int | None) -> str:
    """Return a machine-readable state; localized status is display-only."""
    if scan_state == "failed":
        return "data_gap"
    if scan_state == "building":
        return "available_from_completed_records" if visible else ("building" if not data_gap else "data_gap")
    if visible:
        return "available"
    return "no_candidates" if scan_state == "complete" else "data_gap"


def _normalize_scan_state(base: dict[str, Any], *, file_readable: bool) -> str:
    state = str(base.get("scan_state") or "").strip().lower()
    if state in {"complete", "building", "failed"}:
        return state
    if not file_readable:
        return "failed"
    requested = _int_or_none(base.get("requested"))
    complete = _int_or_none(base.get("data_complete"))
    failed = _int_or_none(base.get("failed")) or 0
    if requested is not None and complete == requested and failed == 0:
        return "complete"
    if failed:
        return "failed"
    return "building"


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
            "list_type": _value(row.get("list_type")),
            "pristine_conditions_matched": _value(row.get("pristine_conditions_matched")),
            "pristine_conditions_total": _value(row.get("pristine_conditions_total")),
            "quality_verified": _value(row.get("quality_verified")),
            "heat_verified": _value(row.get("heat_verified")),
            "verification_gaps": _value(row.get("verification_gaps")),
            "passed_conditions": _value(row.get("passed_conditions")),
            "failed_conditions": _value(row.get("failed_conditions")),
            "risk_factors": _value(row.get("risk_factors")),
            "data_completeness": _value(row.get("data_completeness")),
            "invalidation": _value(row.get("invalidation")),
            "invalidation_condition": _value(row.get("invalidation_condition")),
            "advice_gate": _value(row.get("advice_gate")),
            "strategy_version": _value(row.get("strategy_version")),
            "data_version": _value(row.get("data_version")),
            "backtest_release": _value(row.get("backtest_release")),
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
                    "requested", "requested_records", "data_complete", "complete_records", "failed", "failed_records", "scan_state", "status", "error_details",
                    "universe_mode", "universe_expected", "universe_scanned", "universe_completed", "universe_failed",
                    "candidates", "formal_candidates", "observation_candidates",
                    "candidate_state", "complete_records", "data_gap_counts",
                    "history_cached", "history_expected", "history_progress_pct",
                    "history_pending", "history_failure_count", "partial_candidates_allowed",
                    "evaluable_records", "blocking_reason", "notice", "selection_diagnostics",
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
                "掃描失敗" if base.get("scan_state") == "failed"
                else "建檔中" if base.get("scan_state") == "building"
                else "本次無研究候選" if completed_empty
                else "資料暫時無法取得"
            )
            scan_state = _normalize_scan_state(base, file_readable=False)
            requested_records = _int_or_none(base.get("requested"))
            failed_records = _int_or_none(base.get("failed"))
            complete_records = _int_or_none(base.get("complete_records"))
            if complete_records is None:
                complete_records = _int_or_none(base.get("data_complete"))
            sources_status.append({
                **base,
                "status": status,
                "scan_state": scan_state,
                "candidate_state": _candidate_state(scan_state=scan_state, visible=0, data_gap=failed_records),
                "candidates": 0,
                "visible_candidates": 0,
                # The summary belongs to a scan output that is unavailable in
                # this run.  Do not carry its formal/observation totals into
                # an empty source and thereby fail the release contract.
                "formal_candidates": 0,
                "observation_candidates": 0,
                "visible_candidate_count": 0,
                "formal_candidate_count": 0,
                "observation_candidate_count": 0,
                "history_pending_count": _int_or_none(base.get("history_pending")),
                "source_failure_count": failed_records or 0,
                "incomplete_record_count": max(0, (requested_records or 0) - (complete_records or 0)) if requested_records is not None else None,
                "complete_records": complete_records,
                "failed_records": failed_records,
                "data_gap_counts": failed_records or 0,
                "blocking_reason": base.get("blocking_reason") or "research source unavailable; candidate counts suppressed",
                "candidates_definition": "visible_candidates",
            })
            continue
        scan_state = _normalize_scan_state(base, file_readable=True)
        failed_records = _int_or_none(base.get("failed")) or 0
        complete_records = _int_or_none(base.get("complete_records"))
        if complete_records is None:
            complete_records = _int_or_none(base.get("data_complete"))
        requested_records = _int_or_none(base.get("requested"))
        data_gap_counts = _int_or_none(base.get("data_gap_counts"))
        if data_gap_counts is None:
            data_gap_counts = failed_records
        blocked = (
            base.get("scan_state") == "failed"
            or (base.get("scan_state") == "building" and not base.get("partial_candidates_allowed"))
            or (
                base.get("status") in {"掃描失敗", "資料暫時無法取得", "建檔中"}
                and not base.get("partial_candidates_allowed")
            )
        )
        # Never copy a previous CSV into the new report while a scan is still
        # running or failed.  The source status is the authoritative freshness
        # boundary; an old candidate is less useful than an explicit gap.
        rows = [] if blocked else normalize_frame(frame, source["market"], source["strategy"])
        formal_rows = sum(1 for row in rows if str(row.get("list_type") or "").lower() == "formal")
        observation_rows = sum(1 for row in rows if str(row.get("list_type") or "").lower() == "observation")
        visible = len(rows)
        candidate_state = _candidate_state(scan_state=scan_state, visible=visible, data_gap=data_gap_counts)
        status = (
            "掃描失敗" if base.get("scan_state") == "failed" or base.get("status") == "掃描失敗"
            else "建檔中" if base.get("scan_state") == "building" or base.get("status") == "建檔中"
            else "資料暫時無法取得" if base.get("status") == "資料暫時無法取得"
            else "可用" if rows else "本次無研究候選"
        )
        sources_status.append({
            **base,
            "status": status,
            "scan_state": scan_state,
            "candidate_state": candidate_state,
            "candidates": visible,
            "visible_candidates": visible,
            "candidates_definition": "visible_candidates",
            "formal_candidates": _bounded_candidate_count(base.get("formal_candidates"), visible) if base.get("formal_candidates") is not None else (formal_rows or None),
            "observation_candidates": _bounded_candidate_count(base.get("observation_candidates"), visible) if base.get("observation_candidates") is not None else (observation_rows or None),
            "visible_candidate_count": visible,
            "formal_candidate_count": _bounded_candidate_count(base.get("formal_candidates"), visible) if base.get("formal_candidates") is not None else (formal_rows or 0),
            "observation_candidate_count": _bounded_candidate_count(base.get("observation_candidates"), visible) if base.get("observation_candidates") is not None else (observation_rows or 0),
            "history_pending_count": _int_or_none(base.get("history_pending")),
            "source_failure_count": failed_records,
            "incomplete_record_count": max(0, (requested_records or 0) - (complete_records or 0)) if requested_records is not None else None,
            "requested_records": requested_records,
            "complete_records": complete_records,
            "failed_records": failed_records,
            "data_gap_counts": data_gap_counts,
            "blocking_reason": base.get("blocking_reason") or ("scan incomplete" if blocked else None),
        })
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
