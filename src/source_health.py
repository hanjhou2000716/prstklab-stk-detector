"""Build an explicit public health record for each Mini App data source."""

from __future__ import annotations

from datetime import datetime
from typing import Any


SOURCE_DEFINITIONS = (
    ("market_quotes", "市場報價", {"", "index", "macro_quote", "taiwan_crosscheck"}),
    ("official_events", "官方重大事件", {"official_event"}),
    ("market_news", "市場新聞", {"news"}),
    ("risk", "情緒／波動", {"risk"}),
)


def _source_item(key: str, label: str, issues: list[str], checked_at: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": "healthy" if not issues else "partial",
        "checked_at": checked_at,
        "issues": issues[:2],
    }


def _research_item(report: dict[str, Any], checked_at: str) -> dict[str, Any]:
    """Present research warming, empty results and failures as different states."""
    sources = [item for item in report.get("sources", []) if isinstance(item, dict)]
    failed = [item for item in sources if str(item.get("status")) in {"資料暫時無法取得", "掃描失敗"}]
    partial = []
    for item in sources:
        if item in failed:
            continue
        try:
            failed_count = int(item.get("failed") or 0)
        except (TypeError, ValueError):
            failed_count = 0
        if failed_count > 0:
            partial.append(item)
    warming = [item for item in sources if str(item.get("status")) == "建檔中"]
    if failed:
        issues = [f"{item.get('market', '')} {item.get('strategy', '')} 掃描失敗".strip() for item in failed]
        return {"key": "research", "label": "量化研究", "status": "partial", "checked_at": checked_at, "issues": issues[:2]}
    if partial:
        issues = [f"{item.get('market', '')} {item.get('strategy', '')} 部分資料缺漏".strip() for item in partial]
        return {"key": "research", "label": "量化研究", "status": "partial", "checked_at": checked_at, "issues": issues[:2]}
    if warming:
        details = []
        for item in warming:
            cached, expected = item.get("history_cached"), item.get("history_expected")
            progress = f"：已核對 {cached}／{expected} 檔" if cached is not None and expected is not None else ""
            details.append(f"{item.get('market', '')} 璞玉價值建檔中{progress}".strip())
        return {"key": "research", "label": "量化研究", "status": "warming", "checked_at": checked_at, "issues": details[:2]}
    if (report.get("health") or {}).get("is_expired"):
        return {"key": "research", "label": "量化研究", "status": "partial", "checked_at": checked_at, "issues": ["研究資料已逾時，候選清單已隱藏"]}
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
    monitor_health: dict[str, Any] | None = None,
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
        official["data_gaps"] = [
            item for item in official_sources if item.get("status") != "healthy"
        ]
        if official["data_gaps"] and official["status"] == "healthy":
            official["status"] = "partial"
            official["issues"] = ["部分官方來源暫時無法取得"]
    if news_sources:
        news = next(item for item in sources if item["key"] == "market_news")
        news["source_details"] = news_sources
        news["data_gaps"] = [item for item in news_sources if item.get("status") != "healthy"]
    if additional_sources:
        sources.extend(additional_sources)
    if monitor_health:
        monitor_item = _monitor_health_item(monitor_health, checked)
        if monitor_item:
            sources.append(monitor_item)
    sources.append(_research_item(research_report, checked))

    event_dependencies = {"market_quotes", "official_events", "market_news"}
    dependency_failed = any(
        source["key"] in event_dependencies and source["status"] != "healthy"
        for source in sources
    )
    if events.get("is_major"):
        event_scan = {
            "status": "event_detected",
            "label": "已核對重大事件",
            "detail": "本輪掃描已發現符合門檻的市場事件。",
        }
    elif dependency_failed:
        event_scan = {
            "status": "incomplete",
            "label": "部分來源失敗",
            "detail": "部分事件來源暫時無法取得，不能將本輪解讀為沒有事件。",
        }
    else:
        event_scan = {
            "status": "no_event",
            "label": "本輪無重大事件",
            "detail": "事件來源已完成掃描，未發現符合提醒門檻的重大事件。",
        }
    partial = sum(source["status"] in {"partial", "failed", "missing_api_key", "data_gap"} for source in sources)
    warming = sum(source["status"] == "warming" for source in sources)
    status = "partial" if partial else "warming" if warming else "healthy"
    summary = (
        f"{partial} 個來源有資料缺口" if partial else
        "璞玉價值歷史資料建檔中" if warming else
        "所有來源本輪可用"
    )
    data_gaps = [
        {"source": source["label"], "key": source["key"], "issues": source.get("issues", [])}
        for source in sources if source.get("status") not in {"healthy", "pending", "warming"}
    ]
    return {
        "checked_at": checked,
        "status": status,
        "summary": summary,
        "event_scan": event_scan,
        "sources": sources,
        "data_gaps": data_gaps,
        "missing_source_count": len(data_gaps),
    }
