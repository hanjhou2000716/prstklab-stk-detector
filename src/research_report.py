"""Normalize public-scan artifacts into one browser- and report-friendly shape."""
from __future__ import annotations

import ast
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from src.advice_gate import build_explainability_card, evaluate_advice_gate
from src.instrument_master import InstrumentMaster
from src.price_action import FUNNEL_LABELS, structure_match_score
from src.production_integration import bind_strategy_provenance

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


def _gap_count(value: Any) -> int | None:
    """Collapse structured source gaps to one deterministic count.

    Scan workers keep per-domain diagnostics (for example ``history`` and
    ``quotes``) in their summaries.  The public report must expose the same
    machine-readable integer used by the release contract, without discarding
    those gaps when the summary is read back.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return None
    if isinstance(value, dict):
        counts = [_gap_count(item) for item in value.values()]
        return sum(item for item in counts if item is not None)
    if isinstance(value, (list, tuple)):
        counts = [_gap_count(item) for item in value]
        return sum(item for item in counts if item is not None)
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
    requested = _int_or_none(base.get("requested"))
    complete = _int_or_none(base.get("data_complete"))
    if complete is None:
        complete = _int_or_none(base.get("complete_records"))
    failed = _int_or_none(base.get("failed"))
    if failed is None:
        failed = _int_or_none(base.get("failed_records"))
    if failed is None:
        failed = _int_or_none(base.get("universe_failed"))
    failed = failed or 0
    # Older workers wrote ``complete`` before a failed batch was discovered.
    # Correct the contradiction at the report boundary as a second safety
    # net; a legacy artifact must not look healthy merely because its writer
    # used the wrong state.
    if state == "complete" and (failed > 0 or (
        requested is not None and complete is not None and complete < requested
    )):
        return "building" if (complete or 0) > 0 else "failed"
    if state in {"complete", "building", "failed"}:
        return state
    if not file_readable:
        return "failed"
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
    instruments = InstrumentMaster()
    for rank, (_, row) in enumerate(frame.iterrows(), start=1):
        ticker = str(row["ticker"])
        identity: dict[str, Any] = {
            "instrument_resolution": "unknown",
            "instrument_id": None,
            "asset_type": None,
            "currency": None,
            "instrument_timezone": None,
        }
        try:
            instrument = instruments.resolve(ticker, market=market)
        except (KeyError, ValueError):
            # Research universes are intentionally larger than the compact
            # master registry. Unknown identity is explicit and never guessed.
            pass
        else:
            identity.update({
                "instrument_resolution": "resolved",
                "instrument_id": instrument.instrument_id,
                "asset_type": instrument.asset_type,
                "currency": instrument.currency,
                "instrument_timezone": instrument.timezone,
            })
        structure = _value(row.get("funnel_labels"))
        score = _value(row.get("score"))
        if strategy == "price_action" and score is None:
            score = _structure_score(structure)
        candidates.append({
            "market": market,
            "strategy": strategy,
            "rank": rank,
            "ticker": ticker,
            **identity,
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


def _attach_candidate_contracts(candidates: list[dict[str, Any]]) -> None:
    """Stamp the producer artifact with the same conservative research contract.

    The browser loader also performs this check for backward compatibility, but
    the immutable research JSON must be self-describing for release validation,
    Telegram cards and non-browser consumers.
    """
    for candidate in candidates:
        binding = bind_strategy_provenance(candidate)
        if binding["state"] != "production":
            candidate["advice_gate"] = "observation_only"
        completeness = candidate.get("data_completeness")
        try:
            quality_ok = float(completeness) >= 90 if completeness is not None else False
        except (TypeError, ValueError):
            quality_ok = False
        gate = evaluate_advice_gate({
            "data_quality_ok": quality_ok,
            "quote_stale": candidate.get("freshness") in {"stale", "unavailable"},
            "crosscheck_ok": candidate.get("cross_checked") is True,
            "backtest_release": candidate.get("backtest_release"),
            "backtest_release_contract": candidate.get("backtest_release_contract"),
            "candidate_data_gap": bool(candidate.get("verification_gaps") or candidate.get("failed_conditions")),
            "policy_valid": binding["state"] == "production",
            "general_research": True,
            "evidence": candidate.get("evidence") or candidate.get("source_evidence"),
            "invalidation_condition": candidate.get("invalidation_condition") or candidate.get("invalidation"),
            "alternative_scenario": candidate.get("alternative_scenario"),
            "horizon": candidate.get("horizon"),
            "confidence": candidate.get("confidence"),
        })
        candidate["strategy_binding"] = binding
        candidate["advice_gate_detail"] = gate
        candidate["explainability"] = build_explainability_card(candidate, gate)["explainability"]


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
                    "scan_trading_date", "quote_cutoff_at", "last_successful_generated_at",
                    "execution_version", "data_hash",
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
            requested_records = _int_or_none(base.get("requested_records"))
            if requested_records is None:
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
                "requested_records": requested_records,
                "complete_records": complete_records,
                "failed_records": failed_records,
                "data_gap_counts": _gap_count(base.get("data_gap_counts")) or failed_records or 0,
                "blocking_reason": base.get("blocking_reason") or "research source unavailable; candidate counts suppressed",
                "candidates_definition": "visible_candidates",
            })
            continue
        scan_state = _normalize_scan_state(base, file_readable=True)
        failed_records = _int_or_none(base.get("failed")) or 0
        complete_records = _int_or_none(base.get("complete_records"))
        if complete_records is None:
            complete_records = _int_or_none(base.get("data_complete"))
        requested_records = _int_or_none(base.get("requested_records"))
        if requested_records is None:
            requested_records = _int_or_none(base.get("requested"))
        data_gap_counts = _gap_count(base.get("data_gap_counts"))
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
            # Counts are always integers in a generated report.  A missing
            # list_type in an older scan is not evidence of an unknown count;
            # the current published rows are deterministically zero formal /
            # zero observation until the producer emits the classification.
            "formal_candidates": _bounded_candidate_count(base.get("formal_candidates"), visible) if base.get("formal_candidates") is not None else formal_rows,
            "observation_candidates": _bounded_candidate_count(base.get("observation_candidates"), visible) if base.get("observation_candidates") is not None else observation_rows,
            "visible_candidate_count": visible,
            "formal_candidate_count": _bounded_candidate_count(base.get("formal_candidates"), visible) if base.get("formal_candidates") is not None else formal_rows,
            "observation_candidate_count": _bounded_candidate_count(base.get("observation_candidates"), visible) if base.get("observation_candidates") is not None else observation_rows,
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
    _attach_candidate_contracts(candidates)
    counts = Counter(f"{item['market']}:{item['strategy']}" for item in candidates)
    return {
        "schema_version": "2.0",
        "status": "跨市場研究摘要" if candidates else "目前沒有可整合的研究候選",
        "notice": NOTICE,
        "sources": sources_status,
        "candidates": candidates,
        "summary": {"total_candidates": len(candidates), "by_market_strategy": dict(counts)},
    }


def merge_previous_strategy_versions(
    report: dict[str, Any], previous: dict[str, Any] | None,
    *, target_market: str = "both",
) -> dict[str, Any]:
    """Keep the last verified rows per strategy without masking this run's gap.

    A failed strategy is allowed to publish alongside successful strategies,
    but its rows are explicitly historical.  A completed zero-row scan is a
    valid current result and therefore never falls back to an older shortlist.
    """
    if not isinstance(previous, dict):
        return report
    previous_sources = {
        (str(item.get("market")), str(item.get("strategy"))): item
        for item in previous.get("sources", [])
        if isinstance(item, dict)
    }
    previous_rows: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in previous.get("candidates", []) if isinstance(previous.get("candidates"), list) else []:
        if isinstance(row, dict):
            key = (str(row.get("market")), str(row.get("strategy")))
            previous_rows.setdefault(key, []).append(row)
    candidates = report.setdefault("candidates", [])
    historical_count = 0
    for source in report.get("sources", []) if isinstance(report.get("sources"), list) else []:
        if not isinstance(source, dict):
            continue
        key = (str(source.get("market")), str(source.get("strategy")))
        state = str(source.get("scan_state") or "failed")
        unscanned = target_market in {"taiwan", "us"} and str(source.get("market")) != target_market
        failed = int(source.get("failed_records", source.get("failed", 0)) or 0)
        current_complete = state == "complete" and failed == 0
        source["scan_attempted_at"] = None if unscanned else report.get("generated_at")
        source["historical_fallback"] = False
        source["unscanned_in_run"] = unscanned
        if unscanned:
            rows = previous_rows.get(key, [])
            prev_source = previous_sources.get(key, {})
            if not rows:
                source["strategy_version_state"] = "unavailable"
                source["blocking_reason"] = "本輪未掃描且沒有最後成功版本"
                continue
            previous_time = (
                prev_source.get("last_successful_generated_at")
                or previous.get("generated_at")
                or prev_source.get("scan_attempted_at")
            )
            unscanned_rows: list[dict[str, Any]] = []
            for row in rows:
                copied = dict(row)
                copied["research_version_state"] = "historical"
                copied["historical_from_generated_at"] = previous_time
                copied["historical_reason"] = "本輪未掃描；沿用最後成功版本"
                unscanned_rows.append(copied)
            candidates.extend(unscanned_rows)
            historical_count += len(unscanned_rows)
            source.update({
                "historical_fallback": True,
                "strategy_version_state": "historical",
                "execution_version": prev_source.get("execution_version"),
                "data_hash": prev_source.get("data_hash"),
                "last_successful_at": prev_source.get("last_successful_at") or prev_source.get("last_successful_generated_at") or previous_time,
                "last_successful_generated_at": prev_source.get("last_successful_generated_at") or previous_time,
                "scan_trading_date": prev_source.get("scan_trading_date"),
                "quote_cutoff_at": prev_source.get("quote_cutoff_at"),
                "historical_candidates": len(unscanned_rows),
                "visible_candidates": len(unscanned_rows),
                "candidates": len(unscanned_rows),
                "formal_candidates": sum(1 for row in unscanned_rows if row.get("list_type") == "formal"),
                "observation_candidates": sum(1 for row in unscanned_rows if row.get("list_type") == "observation"),
                "candidate_state": "historical",
                "blocking_reason": "本輪未掃描；沿用最後成功版本並標示歷史資料",
            })
            continue
        if current_complete:
            source["last_successful_generated_at"] = report.get("generated_at")
            source["strategy_version_state"] = "current"
            continue
        rows = previous_rows.get(key, [])
        if not rows:
            source["strategy_version_state"] = "unavailable"
            continue
        prev_source = previous_sources.get(key, {})
        previous_time = (
            prev_source.get("last_successful_generated_at")
            or previous.get("generated_at")
            or prev_source.get("scan_attempted_at")
        )
        historical_rows: list[dict[str, Any]] = []
        for row in rows:
            copied = dict(row)
            copied["research_version_state"] = "historical"
            copied["historical_from_generated_at"] = previous_time
            copied["historical_reason"] = source.get("blocking_reason") or "本輪策略未完成"
            historical_rows.append(copied)
        candidates.extend(historical_rows)
        historical_count += len(historical_rows)
        source.update({
            "historical_fallback": True,
            "strategy_version_state": "historical",
            "execution_version": prev_source.get("execution_version"),
            "data_hash": prev_source.get("data_hash"),
            "scan_trading_date": prev_source.get("scan_trading_date"),
            "quote_cutoff_at": prev_source.get("quote_cutoff_at"),
            "last_successful_at": prev_source.get("last_successful_at") or previous_time,
            "last_successful_generated_at": previous_time,
            "historical_candidates": len(historical_rows),
            "visible_candidates": len(historical_rows),
            "candidates": len(historical_rows),
            "formal_candidates": sum(1 for row in historical_rows if row.get("list_type") == "formal"),
            "observation_candidates": sum(1 for row in historical_rows if row.get("list_type") == "observation"),
            "candidate_state": "historical",
        })
    report["historical_candidate_count"] = historical_count
    report["mixed_date"] = historical_count > 0
    return report
