"""Build an explicit public health record for each Mini App data source."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from src.health_observability import aggregate_source_health, summarize_health_history

SOURCE_DEFINITIONS = (
    ("market_quotes", "市場報價", {"", "index", "macro_quote", "taiwan_crosscheck"}),
    ("official_events", "官方重大事件", {"official_event"}),
    ("market_news", "市場新聞", {"news"}),
    ("risk", "情緒／波動", {"risk"}),
)

CANONICAL_STATES = {
    "healthy",
    "degraded_with_fallback",
    "optional_degraded",
    "configuration_required",
    "critical_gap",
    "failed",
    "warming",
    "no_event",
    "pending_confirmation",
}

# Stable semantic labels consumed by the investor summary.  The legacy
# ``state`` values remain for backwards compatibility, while
# ``semantic_state`` is the single vocabulary used for gap counting and UI
# aggregation.
SEMANTIC_STATES = {
    "healthy", "no_event", "fallback_active", "secondary_unavailable",
    "configuration_missing", "warming", "stale", "partial", "failed", "critical",
}


def _semantic_state(item: dict[str, Any]) -> str:
    # Provider adapters may normalize an unavailable credential as
    # ``status=partial`` while retaining the machine-readable state or
    # provider status.  Configuration is an operator action, not a runtime
    # outage; resolve it before trusting the display status/semantic label so
    # aggregate health cannot over-count it as a failed source.
    explicit_state = str(item.get("state") or "").strip()
    provider_status = str(item.get("provider_status") or item.get("error_code") or "").strip().lower()
    if explicit_state in {"configuration_required", "configuration_missing"} or provider_status in {
        "missing_api_key", "configuration_required", "not_configured",
    }:
        return "configuration_missing"
    explicit = str(item.get("semantic_state") or "").strip()
    if explicit in SEMANTIC_STATES:
        return explicit
    status = str(item.get("status") or "").strip().lower()
    if status == "partial" or status == "data_gap":
        return "partial"
    if status in {"failed", "scan_failed", "掃描失敗"}:
        return "failed"
    legacy = _canonical_state(item)
    if legacy == "degraded_with_fallback":
        return "fallback_active"
    if legacy == "optional_degraded":
        return "partial"
    if legacy == "configuration_required":
        return "configuration_missing"
    if legacy == "critical_gap":
        return "critical"
    if legacy == "pending_confirmation":
        return "secondary_unavailable"
    freshness = str(item.get("freshness") or "").lower()
    if freshness in {"stale", "expired", "recent_close_stale"}:
        return "stale"
    return legacy if legacy in SEMANTIC_STATES else "critical"


def _is_gap(item: dict[str, Any]) -> bool:
    return _semantic_state(item) in {
        "fallback_active", "configuration_missing",
        "stale", "partial", "failed", "critical",
    }


def _canonical_state(item: dict[str, Any]) -> str:
    """Map legacy provider statuses to the public source-health taxonomy."""
    explicit = str(item.get("state") or "").strip()
    if explicit in CANONICAL_STATES:
        return explicit
    status = str(item.get("status") or "").lower()
    if status in {"healthy", "ok", "success", "no_event"}:
        return "no_event" if status == "no_event" else "healthy"
    if status in {"warming", "建檔中"}:
        return "warming"
    if status in {"pending", "pending_confirmation"}:
        return "pending_confirmation"
    if status in {"missing_api_key", "configuration_required", "not_configured"}:
        return "configuration_required"
    if status in {"optional_degraded", "optional_gap"}:
        return "optional_degraded"
    if status in {"partial", "fallback", "degraded_with_fallback"}:
        return "degraded_with_fallback" if item.get("fallback_used") else "critical_gap"
    if status in {"failed", "scan_failed", "掃描失敗"}:
        return "failed"
    return "critical_gap"


def _source_item(key: str, label: str, issues: list[str], checked_at: str) -> dict[str, Any]:
    item = {
        "key": key,
        "label": label,
        "status": "healthy" if not issues else "partial",
        # ``state`` is deliberately separate from status so the UI can tell
        # a clean scan with no event from a failed provider request.
        "state": "no_event" if not issues else "failed",
        "role": "required_for_core" if key in {"market_quotes", "official_events"} else "required_for_alert",
        "checked_at": checked_at,
        "issues": issues[:2],
    }
    item["semantic_state"] = "no_event" if not issues else "failed"
    return item


def _attach_detail_summary(target: dict[str, Any], details: list[dict[str, Any]]) -> None:
    """Add non-sensitive freshness counters without replacing per-source evidence.

    Providers may return different optional fields.  We aggregate only values that
    are explicitly present; a failed request therefore never gets a fabricated
    success timestamp or latency.
    """
    records = [item for item in details if isinstance(item, dict)]
    if not records:
        return
    checked = [str(item.get("checked_at") or "") for item in records if item.get("checked_at")]
    successful = [
        str(item.get("last_success_at") or item.get("checked_at") or "")
        for item in records
        if str(item.get("status") or "").lower() in {"healthy", "ok", "success"}
        and (item.get("last_success_at") or item.get("checked_at"))
    ]
    counts: list[float] = [float(item["item_count"]) for item in records if isinstance(item.get("item_count"), (int, float))]
    latencies: list[float] = [float(item["latency_ms"]) for item in records if isinstance(item.get("latency_ms"), (int, float))]
    urls = sorted({str(item.get("source_url") or "") for item in records if item.get("source_url")})
    failures = [int(item["consecutive_failures"]) for item in records if isinstance(item.get("consecutive_failures"), int) and item["consecutive_failures"] >= 0]
    fallback_count = sum(1 for item in records if item.get("fallback_used") is True)
    error_codes = sorted({str(item.get("error_code")) for item in records if item.get("error_code")})
    if checked:
        target["checked_at"] = max(checked)
    if successful:
        target["last_success_at"] = max(successful)
    if counts:
        target["item_count"] = int(sum(counts))
    if latencies:
        target["latency_ms"] = round(max(float(value) for value in latencies), 1)
    if urls:
        target["source_urls"] = urls
        target.setdefault("source_url", urls[0])
    if failures:
        target["max_consecutive_failures"] = max(failures)
    if fallback_count:
        target["fallback_count"] = fallback_count
    if error_codes:
        target["error_codes"] = error_codes[:8]


def _research_item(report: dict[str, Any], checked_at: str) -> dict[str, Any]:
    """Present research warming, empty results and failures as different states."""
    sources = [item for item in report.get("sources", []) if isinstance(item, dict)]
    # Producers historically emitted localized display labels, while current
    # producers emit machine states.  Always prefer the stable scan_state so
    # a label change cannot turn a failed scan into a healthy source row.
    failed_states = {"failed", "scan_failed", "data_unavailable", "unavailable"}
    building_states = {"building", "warming", "partial", "in_progress"}
    failed = [
        item for item in sources
        if str(item.get("scan_state") or "").strip().lower() in failed_states
        or str(item.get("status") or "").strip().lower() in failed_states
        or str(item.get("status")) in {"資料暫時無法取得", "掃描失敗"}
    ]
    partial = []
    for item in sources:
        if item in failed:
            continue
        try:
            failed_count = int(item.get("failed") or 0)
        except (TypeError, ValueError):
            failed_count = 0
        scan_state = str(item.get("scan_state") or "").strip().lower()
        status_state = str(item.get("status") or "").strip().lower()
        if failed_count > 0 or scan_state in {"partial", "data_gap"} or status_state in {"partial", "data_gap"}:
            partial.append(item)
    warming = [
        item for item in sources
        if str(item.get("scan_state") or "").strip().lower() in building_states
        or str(item.get("status") or "").strip().lower() in building_states
        or str(item.get("status")) == "建檔中"
    ]
    if failed:
        issues = [f"{item.get('market', '')} {item.get('strategy', '')} 掃描失敗".strip() for item in failed]
        return {"key": "research", "label": "量化研究", "status": "partial", "semantic_state": "failed", "checked_at": checked_at, "issues": issues[:2]}
    if partial:
        issues = [f"{item.get('market', '')} {item.get('strategy', '')} 部分資料缺漏".strip() for item in partial]
        return {"key": "research", "label": "量化研究", "status": "partial", "semantic_state": "partial", "checked_at": checked_at, "issues": issues[:2]}
    if warming:
        details = []
        for item in warming:
            cached, expected = item.get("history_cached"), item.get("history_expected")
            progress = f"：已核對 {cached}／{expected} 檔" if cached is not None and expected is not None else ""
            details.append(f"{item.get('market', '')} 璞玉價值建檔中{progress}".strip())
        return {"key": "research", "label": "量化研究", "status": "warming", "semantic_state": "warming", "checked_at": checked_at, "issues": details[:2]}
    if (report.get("health") or {}).get("is_expired"):
        return {"key": "research", "label": "量化研究", "status": "partial", "semantic_state": "stale", "checked_at": checked_at, "issues": ["研究資料已逾時，候選清單已隱藏"]}
    diagnostics = [
        item.get("selection_diagnostics")
        for item in sources
        if isinstance(item.get("selection_diagnostics"), dict)
    ]
    formal = sum(int(item.get("formal_candidates") or 0) for item in sources)
    observation = sum(int(item.get("observation_candidates") or 0) for item in sources)
    candidate_count = sum(int(item.get("candidates") or 0) for item in sources)
    candidate_state = "available" if candidate_count else "no_candidates"
    return {
        "key": "research",
        "label": "量化研究",
        "status": "healthy",
        "semantic_state": "healthy",
        "checked_at": checked_at,
        "issues": [],
        "candidate_state": candidate_state,
        "candidate_count": candidate_count,
        "formal_candidates": formal,
        "observation_candidates": observation,
        "selection_diagnostics": diagnostics,
    }


def _monitor_health_item(monitor_health: dict[str, Any], checked_at: str) -> dict[str, Any] | None:
    """Re-attach Railway monitor state after a normal market refresh."""
    if str(monitor_health.get("component") or "").lower() != "gdelt":
        return None
    try:
        pending_count = max(0, int(monitor_health.get("pending_count") or 0))
    except (TypeError, ValueError):
        pending_count = 0
    status = str(monitor_health.get("status") or "unknown")
    source_status = "partial" if status == "failed" else "pending" if pending_count else "healthy"
    reasons = monitor_health.get("pending_reasons")
    if not isinstance(reasons, dict):
        reasons = {}
    issues = [f"{reason}: {count} pending event(s)" for reason, count in reasons.items() if count]
    if pending_count and not issues:
        if str(monitor_health.get("market_sync_status") or "not_confirmed") != "confirmed":
            issues.append("等待市場同步：相關價格或波動尚未確認")
        else:
            issues.append("等待第二來源：尚未有第二個可信新聞網域核對")
    return {
        "key": "gdelt_crosscheck",
        "label": "GDELT event cross-check",
        "status": source_status,
        "checked_at": monitor_health.get("checked_at") or checked_at,
        "source_url": "https://api.gdeltproject.org/api/v2/doc/doc",
        "issues": issues[:3],
        "pending_count": pending_count,
        "pending_reasons": reasons,
        "market_sync_status": monitor_health.get("market_sync_status") or "not_confirmed",
        "semantic_state": "failed" if status == "failed" else "secondary_unavailable" if pending_count else "healthy",
    }


def build_source_health(
    *,
    errors: list[dict[str, str]],
    events: dict[str, Any],
    research_report: dict[str, Any],
    checked_at: datetime,
    official_sources: list[dict[str, Any]] | None = None,
    news_sources: list[dict[str, Any]] | None = None,
    additional_sources: list[dict[str, Any]] | None = None,
    creator_sources: list[dict[str, Any]] | None = None,
    monitor_health: dict[str, Any] | None = None,
    quote_evidence: dict[str, Any] | None = None,
    history_records: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Expose failures distinctly from a clean scan with no market event."""
    checked = checked_at.isoformat()
    grouped: dict[str, list[str]] = {key: [] for key, _, _ in SOURCE_DEFINITIONS}
    for error in errors:
        scope = str(error.get("scope") or "")
        ticker = str(error.get("ticker") or "")
        message = str(error.get("message") or "公開來源暫時無法取得")
        if ticker == "新聞":
            grouped["market_news"].append(message)
            continue
        for key, _, scopes in SOURCE_DEFINITIONS:
            if scope in scopes:
                grouped[key].append(message)
                break

    sources = [
        _source_item(key, label, grouped[key], checked)
        for key, label, _ in SOURCE_DEFINITIONS
    ]
    if official_sources:
        official = next(item for item in sources if item["key"] == "official_events")
        official["source_details"] = official_sources
        _attach_detail_summary(official, official_sources)
        official["data_gaps"] = [
            item for item in official_sources if item.get("status") not in {"healthy", "no_event"}
        ]
        if official["data_gaps"] and official["status"] == "healthy":
            official["status"] = "partial"
            official["issues"] = ["部分官方來源暫時無法取得"]
    if news_sources:
        news = next(item for item in sources if item["key"] == "market_news")
        news["source_details"] = news_sources
        _attach_detail_summary(news, news_sources)
        news["data_gaps"] = [
            item for item in news_sources
            if item.get("status") not in {"healthy", "no_event", "no_new_content"}
        ]
        # A successful provider returning no stories is not a failure. Keep
        # this state explicit so the Mini App can say "本輪無新內容" instead
        # of implying that the feed was unavailable.
        provider_states = {
            str(item.get("status") or "").strip().lower()
            for item in news_sources
            if isinstance(item, dict)
        }
        if provider_states and provider_states <= {"no_event", "no_new_content"}:
            news["status"] = "no_new_content"
            news["state"] = "no_new_content"
            news["semantic_state"] = "no_event"
            news["data_gaps"] = []
            news["issues"] = ["本輪來源已完成掃描，沒有新的市場新聞"]
        elif provider_states and "no_new_content" in provider_states and news["status"] == "healthy":
            news["issues"] = ["部分來源本輪沒有新內容"]
    if additional_sources:
        for item in additional_sources:
            if not isinstance(item, dict):
                continue
            normalized = dict(item)
            # Optional adapters may provide only a machine key and status.
            # Keep the public envelope total so a degraded provider cannot
            # crash source-health aggregation while building data_gaps.
            normalized.setdefault("label", normalized.get("key") or "unknown source")
            normalized["state"] = _canonical_state(normalized)
            if str(normalized.get("status") or "") in {"missing_api_key", "not_configured"}:
                normalized["status"] = "configuration_missing"
            normalized["semantic_state"] = _semantic_state(normalized)
            normalized.setdefault("role", "optional")
            # The current refresh succeeded for healthy providers, so this is a
            # legitimate success timestamp; failed/partial providers stay unset.
            if normalized.get("status") == "healthy" and not normalized.get("last_success_at"):
                normalized["last_success_at"] = normalized.get("checked_at")
            sources.append(normalized)
    if creator_sources:
        for item in creator_sources:
            if not isinstance(item, dict):
                continue
            normalized = dict(item)
            normalized.setdefault("key", f"creator_{normalized.get('provider') or 'unknown'}")
            normalized.setdefault("label", f"Creator｜{normalized.get('provider') or 'unknown'}")
            normalized.setdefault("role", "optional")
            normalized["state"] = _canonical_state(normalized)
            normalized["semantic_state"] = _semantic_state(normalized)
            normalized.setdefault("creator_health", normalized["semantic_state"])
            sources.append(normalized)
    if monitor_health:
        monitor_item = _monitor_health_item(monitor_health, checked)
        if monitor_item:
            sources.append(monitor_item)
    sources.append(_research_item(research_report, checked))
    if quote_evidence:
        market = next(item for item in sources if item["key"] == "market_quotes")
        market["evidence"] = {
            key: value for key, value in quote_evidence.items() if isinstance(value, dict)
        }
        stale = sum(int((value or {}).get("stale_count") or 0) for value in quote_evidence.values() if isinstance(value, dict))
        if stale and market["status"] == "healthy":
            market["status"] = "partial"
            market["issues"] = [f"{stale} 筆報價過期或不可用，僅供顯示"]

    event_dependencies = {"market_quotes", "official_events", "market_news"}
    dependency_failed = any(
        source["key"] in event_dependencies
        and source["status"] not in {"healthy", "no_event", "no_new_content"}
        for source in sources
    )
    if events.get("is_major"):
        event_scan = {
            "status": "event_detected",
            "has_events": True,
            "label": "已核對重大事件",
            "detail": "本輪掃描已發現符合門檻的市場事件。",
        }
    elif dependency_failed:
        event_scan = {
            "status": "scan_failed",
            "has_events": False,
            "label": "部分來源失敗",
            "detail": "部分事件來源暫時無法取得，不能將本輪解讀為沒有事件。",
        }
    else:
        event_scan = {
            "status": "no_event",
            "has_events": False,
            "label": "本輪無重大事件",
            "detail": "事件來源已完成掃描，未發現符合提醒門檻的重大事件。",
        }
    for source in sources:
        if source.get("status") in {"partial", "failed", "missing_api_key", "data_gap"} and source.get("semantic_state") in {"healthy", "no_event"}:
            source["semantic_state"] = "failed" if source.get("status") == "failed" else "partial"
        source["semantic_state"] = _semantic_state(source)
    gap_sources = [source for source in sources if _is_gap(source)]
    partial = len(gap_sources)
    configuration_sources = [
        source for source in sources if _semantic_state(source) == "configuration_missing"
    ]
    runtime_gap_sources = [
        source for source in gap_sources
        if _semantic_state(source) != "configuration_missing"
    ]
    warming = sum(source["status"] == "warming" for source in sources)
    core_gap = any(
        _semantic_state(source) != "configuration_missing"
        and _is_gap(source) and str(source.get("role") or "") == "required_for_core"
        for source in sources
    )
    status = "critical" if core_gap else "partial" if runtime_gap_sources else "warming" if warming else "healthy"
    # Optional credentials are disclosed separately; they do not downgrade
    # the investor-facing aggregate when all required runtime sources work.
    investor_status = "核心資料不足" if core_gap else "部分資料降級" if runtime_gap_sources else "資料正常"
    summary = (
        f"{partial} 個來源有資料缺口" if partial else
        "璞玉價值歷史資料建檔中" if warming else
        "所有來源本輪可用"
    )
    data_gaps = [
        {"source": source["label"], "key": source["key"], "issues": source.get("issues", [])}
        for source in gap_sources
    ]
    observability = aggregate_source_health(sources)
    if history_records is not None:
        observability["history"] = summarize_health_history(history_records, now=checked_at)
    # Configuration is an explicit operator action, not a provider outage.
    # Keep it visible for engineering users, but do not fold it into runtime
    # failure counts or imply that the configured market sources are broken.
    observability["configuration_missing_count"] = len(configuration_sources)
    observability["runtime_failure_count"] = len(runtime_gap_sources)
    observability["state"] = (
        "healthy" if not runtime_gap_sources else
        "partial" if any(source.get("status") not in {"failed", "critical"} for source in runtime_gap_sources)
        else "failed"
    )
    return {
        "checked_at": checked,
        "status": status,
        "summary": summary,
        "investor_status": investor_status,
        "observability": observability,
        "event_scan": event_scan,
        "sources": sources,
        "data_gaps": data_gaps,
        "missing_source_count": len(gap_sources),
        "runtime_failure_count": len(runtime_gap_sources),
        "configuration_missing_count": len(configuration_sources),
        "gap_source_keys": [str(source.get("key") or "") for source in gap_sources],
        "state_counts": {
            state: sum(_canonical_state(source) == state for source in sources)
            for state in sorted(CANONICAL_STATES)
        },
        "source_roles": {
            role: sum(str(source.get("role") or "optional") == role for source in sources)
            for role in ("required_for_core", "required_for_alert", "required_for_research", "optional")
        },
    }
