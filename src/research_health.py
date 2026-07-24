"""Explicit freshness and source-availability status for research reports."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


def assess_research_health(
    report: dict[str, Any],
    *,
    now: datetime | None = None,
    max_age_minutes: int = 180,
) -> dict[str, Any]:
    """Return a transparent health summary; never infer missing source data."""
    now = now or datetime.now(ZoneInfo("Asia/Taipei"))
    reasons: list[str] = []
    unavailable = [item for item in report.get("sources", []) if item.get("status") == "資料暫時無法取得"]
    if unavailable:
        reasons.append("無法取得：" + "、".join(f"{item.get('market')} {item.get('strategy')}" for item in unavailable))
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

    if not report.get("sources"):
        reasons.append("沒有來源狀態")
    return {
        "status": "健康" if not reasons else "需留意",
        "reasons": reasons,
        "unavailable_sources": len(unavailable),
        "age_minutes": age_minutes,
        "checked_at": now.isoformat(),
    }
