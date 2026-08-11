"""Manually send an in-scope emergency alert with the Mini App entry point."""

from __future__ import annotations

import argparse
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from src.alert_budget import decide_alert_budget
from src.alert_card_renderer import RendererError, render_alert_card
from src.config import get_settings
from src.event_ledger import EventLedger
from src.telegram_client import send_photo_briefs, summarize_photo_deliveries, validate_brief

STRICT_HIGH_RISK_CATEGORIES = {"black_swan", "conflict"}


def high_risk_confirmation_ready(category: str, risk_level: str | None = None) -> bool:
    if category not in STRICT_HIGH_RISK_CATEGORIES:
        return True
    # Multi-source discovery may be sent as a warning after market impact is
    # confirmed.  Only an explicitly high-risk alert is held behind the
    # first-party + market-sync gate.
    if str(risk_level or os.environ.get("EXTERNAL_RISK_LEVEL", "")).strip() in {"警戒", "warning"}:
        return os.environ.get("EXTERNAL_MARKET_SYNC_CONFIRMED", "").lower() == "true"
    return (
        os.environ.get("EXTERNAL_OFFICIAL_CONFIRMED", "").lower() == "true"
        and os.environ.get("EXTERNAL_MARKET_SYNC_CONFIRMED", "").lower() == "true"
    )


CATEGORY_LABELS = {
    "black_swan": "黑天鵝",
    "material_positive": "重大正向",
    "fed": "Fed",
    "macro": "總經",
    "policy": "政策",
    "conflict": "衝突",
    "energy": "能源",
    "semiconductor": "半導體",
    "market": "極端波動",
}


def build_emergency_brief(category: str, summary: str) -> str:
    """Create a neutral, watch-friendly alert from an allowed event category."""
    if category not in CATEGORY_LABELS:
        raise ValueError("不支援的重大事件類別。")
    normalized = " ".join(summary.split())
    if not normalized:
        raise ValueError("快訊摘要不可空白。")
    text = f"快訊｜{CATEGORY_LABELS[category]}｜{normalized}"
    validate_brief(text)
    return text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="發送稜量重大事件手動快訊")
    parser.add_argument("--category", required=True, choices=CATEGORY_LABELS)
    parser.add_argument("--summary", required=True, help="含前綴共 30 字內的中立摘要")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    if not settings.telegram_ready:
        raise RuntimeError("缺少 Telegram 設定，無法發送快訊。")
    risk_level = os.environ.get("EXTERNAL_RISK_LEVEL", "高風險")
    if args.category in STRICT_HIGH_RISK_CATEGORIES and not high_risk_confirmation_ready(args.category, risk_level):
        print("重大災害尚未同時完成官方來源與相關市場同步確認，僅保留 Mini App 觀察，不發送高風險 Telegram 快訊。")
        return
    text = build_emergency_brief(args.category, args.summary)
    release_id = os.environ.get("RELEASE_ID", "")
    snapshot_id = os.environ.get("SNAPSHOT_ID", "")
    if not release_id or not snapshot_id:
        raise RuntimeError("Emergency photo delivery requires RELEASE_ID and SNAPSHOT_ID")
    alert_id = os.environ.get("ALERT_ID", f"manual-{args.category}")
    trace_id = os.environ.get("TRACE_ID", f"manual-{args.category}")
    event = {
        "event_key": alert_id,
        "event_cluster_key": alert_id,
        "source_key": f"emergency:{args.category}",
        "title": args.summary,
        "summary": args.summary,
        "event_type": args.category,
        "risk_level": risk_level,
        "released_at": os.environ.get("EXTERNAL_OCCURRED_AT") or datetime.now(UTC).isoformat(),
        "trace_id": trace_id,
    }
    ledger = EventLedger()
    budget = decide_alert_budget(event, ledger.delivery_history())
    if not budget.get("allowed", False):
        lines = [
            f"trace_id={trace_id}",
            f"alert_id={alert_id}",
            f"release_id={release_id}",
            f"snapshot_id={snapshot_id}",
            "sent=false",
            "delivery_status=suppressed",
            f"reason=alert_budget:{budget.get('reason', 'suppressed')}",
            "alert_budget_allowed=false",
            f"alert_budget_reason={budget.get('reason', 'suppressed')}",
            f"alert_budget_upgraded={'true' if budget.get('upgraded') else 'false'}",
            "delivery_mode=photo",
        ]
        destination = os.environ.get("GITHUB_OUTPUT")
        if destination:
            with open(destination, "a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
        else:
            print("\n".join(lines))
        print(f"Emergency alert suppressed by alert budget: {budget.get('reason', 'suppressed')}")
        return
    try:
        with tempfile.TemporaryDirectory(prefix="prstk-emergency-card-") as temporary:
            photo_path = render_alert_card(
                {
                    "title": CATEGORY_LABELS[args.category],
                    "lifecycle_state": "escalated" if args.category in STRICT_HIGH_RISK_CATEGORIES else "confirmed",
                    "trigger_reason": text,
                    "release_id": release_id,
                    "snapshot_id": snapshot_id,
                },
                Path(temporary) / "alert.png",
            )
            results = send_photo_briefs(
                token=settings.telegram_bot_token or "",
                chat_ids=settings.telegram_chat_ids,
                caption=text,
                photo_path=photo_path,
                mini_app_url=settings.dashboard_url,
                alert_id=alert_id,
                release_id=release_id,
                snapshot_id=snapshot_id,
                observation_id=trace_id,
            )
    except (RendererError, OSError, ValueError) as exc:
        print(f"renderer_failed={getattr(exc, 'error_type', type(exc).__name__)}")
        raise RuntimeError("renderer failed; Telegram photo was not sent") from exc
    summary = summarize_photo_deliveries(results)
    lines = [
        f"trace_id={trace_id}",
        f"alert_id={os.environ.get('ALERT_ID', f'manual-{args.category}')}",
        f"release_id={os.environ.get('RELEASE_ID', '')}",
        f"snapshot_id={os.environ.get('SNAPSHOT_ID', '')}",
        f"delivered_count={summary.delivered_count}",
        f"failed_count={summary.failed_count}",
        f"delivery_status={'delivered' if summary.failed_count == 0 else 'partial' if summary.delivered_count else 'failed'}",
        "delivery_mode=photo",
        f"failed_recipient_hashes={','.join(summary.failed_recipient_hashes)}",
        "alert_budget_allowed=true",
        f"alert_budget_reason={budget.get('reason', 'budget_available')}",
        f"alert_budget_upgraded={'true' if budget.get('upgraded') else 'false'}",
        f"alert_budget_event_key={budget.get('event_key', '')}",
    ]
    destination = os.environ.get("GITHUB_OUTPUT")
    if destination:
        with open(destination, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))
    if not summary.any_delivered:
        raise RuntimeError("Telegram delivery failed for every configured recipient")
    ledger.record_delivery(event, trace_id=trace_id, reason="emergency_alert")
    ledger.save()
    print(f"Telegram delivery: {summary.delivered_count} delivered, {summary.failed_count} failed")


if __name__ == "__main__":
    main()
