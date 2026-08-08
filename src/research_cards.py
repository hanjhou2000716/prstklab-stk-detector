"""Load the latest full-universe research artifact for the public Mini App."""

from __future__ import annotations

# The public notice is intentionally assigned twice below: the final value
# overrides the raw notice only when the research artifact is expired.
# ruff: noqa: F601
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.research_health import assess_research_health

REPORT_PATH = Path("site/data/research-report.json")
ALLOWED_STRATEGIES = {"momentum", "price_action", "resonance", "value"}
ALLOWED_MARKETS = {"taiwan", "us"}


def load_research_cards(path: Path = REPORT_PATH, *, now: datetime | None = None) -> dict[str, Any]:
    """Return only non-actionable fields from the newest research artifact."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "status": "資料暫時無法取得",
            "notice": "全市場研究報告尚未產生，請等待下一次掃描完成。",
            "generated_at": None,
            "sources": [],
            "candidates": [],
        }

    health = assess_research_health(raw, now=now or datetime.now(ZoneInfo("Asia/Taipei")))
    expired = bool(health["is_expired"])
    blocked_sources = {
        (str(item.get("market")), str(item.get("strategy")))
        for item in raw.get("sources", [])
        if isinstance(item, dict)
        and (
            (
                item.get("scan_state") in {"failed", "building"}
                and not (
                    item.get("scan_state") == "building"
                    and item.get("partial_candidates_allowed") is True
                )
            )
            or (
                item.get("status") in {"掃描失敗", "資料暫時無法取得", "建檔中"}
                and not (
                    item.get("status") == "建檔中"
                    and item.get("partial_candidates_allowed") is True
                )
            )
        )
    }
    candidates = []
    for item in raw.get("candidates", []):
        if not isinstance(item, dict) or item.get("strategy") not in ALLOWED_STRATEGIES or item.get("market") not in ALLOWED_MARKETS:
            continue
        if expired:
            continue
        if (str(item.get("market")), str(item.get("strategy"))) in blocked_sources:
            continue
        candidates.append({key: item.get(key) for key in (
            "market", "strategy", "rank", "ticker", "name", "score", "close", "previous_close", "change_percent", "turnover", "as_of", "signal_labels", "volume_ratio", "range_contraction", "breakout_20", "vcp_breakout", "new_high_days", "fgi_score", "fgi_status", "conditions_matched", "condition_count", "structure", "status",
            "roe", "pe", "payout_ratio", "metrics_available", "moat_review", "list_type",
            "pristine_conditions_matched", "pristine_conditions_total", "quality_verified",
            "heat_verified", "verification_gaps", "passed_conditions", "failed_conditions",
            "risk_factors", "data_completeness", "invalidation", "invalidation_condition",
            "advice_gate", "strategy_version", "data_version", "backtest_release"
        )})
    sources = [
        {key: source.get(key) for key in (
            "market", "strategy", "status", "scan_state", "candidate_state", "candidates", "visible_candidates", "visible_candidate_count", "candidates_definition", "formal_candidates", "formal_candidate_count", "observation_candidates", "observation_candidate_count", "requested", "requested_records", "data_complete", "complete_records", "failed", "failed_records",
            "scan_state", "candidate_state", "complete_records", "data_gap_counts", "history_cached", "history_expected", "history_progress_pct",
            "history_pending", "history_pending_count", "history_failure_count", "source_failure_count", "incomplete_record_count", "blocking_reason", "notice", "error_details",
            "partial_candidates_allowed",
            "selection_diagnostics",
        )}
        for source in raw.get("sources", [])
        if isinstance(source, dict) and source.get("strategy") in ALLOWED_STRATEGIES
    ]
    return {
        "status": raw.get("status", "研究報告"),
        "notice": raw.get("notice", "全市場公開資料研究。"),
        "generated_at": raw.get("generated_at"),
        "sources": sources,
        "candidates": candidates,
        "health": health,
        "availability": "expired" if expired else "available",
        "notice": "研究資料已逾時，候選清單已隱藏；等待下一次全市場掃描完成。" if expired else raw.get("notice"),
    }
