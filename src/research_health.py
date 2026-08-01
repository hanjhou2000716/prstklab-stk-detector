"""Explicit freshness and source-availability status for research reports."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


DEFAULT_MAX_AGE_MINUTES = 30 * 60


def _source_state(source: dict[str, Any]) -> str:
    """Normalize legacy and current scan states without hiding a failure."""
    state = str(source.get("scan_state") or source.get("status") or "")
    if state in {"building", "建檔中"}:
        return "warming"
    if state in {"failed", "掃描失敗", "資料暫時無法取得"}:
        return "failed"
    try:
        if int(source.get("failed") or 0) > 0:
            return "partial"
    except (TypeError, ValueError):
        pass
    if state in {"empty", "本次無研究候選"}:
        return "empty"
    return "ready"


def assess_research_health(
    report: dict[str, Any],
    *,
    now: datetime | None = None,
    max_age_minutes: int = DEFAULT_MAX_AGE_MINUTES,
) -> dict[str, Any]:
    """Return a transparent health summary; never infer missing source data."""
    now = now or datetime.now(ZoneInfo("Asia/Taipei"))
    reasons: list[str] = []
    sources = [item for item in report.get("sources", []) if isinstance(item, dict)]
    failed = [item for item in sources if _source_state(item) == "failed"]
    partial = [item for item in sources if _source_state(item) == "partial"]
    warming = [item for item in sources if _source_state(item) == "warming"]
    empty = [item for item in sources if _source_state(item) == "empty"]
    if failed:
        reasons.append("掃描失敗：" + "、".join(f"{item.get('market')} {item.get('strategy')}" for item in failed))
    if partial:
        reasons.append("部分資料缺漏：" + "、".join(f"{item.get('market')} {item.get('strategy')}" for item in partial))
    generated = report.get("generated_at")
    age_minutes = None
    if generated:
        try:
            timestamp = datetime.fromisoformat(str(generated))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=ZoneInfo("Asia/Taipei"))
            age_minutes = max(0, round((now - timestamp).total_seconds() / 60, 1))
            if age_minutes > max_age_minutes:
                reasons.append(f"研究報表已超過 {max_age_minutes} 分鐘")
        except ValueError:
            reasons.append("研究報表時間格式無法判讀")
    else:
        reasons.append("研究報表沒有產生時間")

    if not sources:
        reasons.append("沒有來源狀態")
    status = "健康" if not reasons else "需留意"
    if status == "健康" and warming:
        status = "建檔中"
    return {
        "status": status,
        "reasons": reasons,
        "unavailable_sources": len(failed),
        "partial_sources": len(partial),
        "warming_sources": len(warming),
        "empty_sources": len(empty),
        "age_minutes": age_minutes,
        "checked_at": now.isoformat(),
        "max_age_minutes": max_age_minutes,
        "is_expired": age_minutes is None or age_minutes > max_age_minutes,
    }
