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
    failed = [item for item in sources if str(item.get("status")) == "資料暫時無法取得"]
    warming = [item for item in sources if str(item.get("status")) == "建檔中"]
    if failed:
        issues = [f"{item.get('market', '')} {item.get('strategy', '')} 掃描失敗".strip() for item in failed]
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
    return {"key": "research", "label": "量化研究", "status": "healthy", "checked_at": checked_at, "issues": []}


def build_source_health(
    *,
    errors: list[dict[str, str]],
    events: dict[str, Any],
    research_report: dict[str, Any],
    checked_at: datetime,
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
    partial = sum(source["status"] == "partial" for source in sources)
    warming = sum(source["status"] == "warming" for source in sources)
    status = "partial" if partial else "warming" if warming else "healthy"
    summary = (
        f"{partial} 個來源有資料缺口" if partial else
        "璞玉價值歷史資料建檔中" if warming else
        "所有來源本輪可用"
    )
    return {
        "checked_at": checked,
        "status": status,
        "summary": summary,
        "event_scan": event_scan,
        "sources": sources,
    }
