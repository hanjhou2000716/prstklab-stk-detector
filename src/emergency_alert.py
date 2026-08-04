"""Manually send an in-scope emergency alert with the Mini App entry point."""

from __future__ import annotations

import argparse
import os

from src.config import get_settings
from src.telegram_client import send_briefs, summarize_deliveries, validate_brief


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
    results = send_briefs(
        token=settings.telegram_bot_token or "",
        chat_ids=settings.telegram_chat_ids,
        text=text,
        dashboard_url=settings.dashboard_url,
    )
    summary = summarize_deliveries(results)
    trace_id = os.environ.get("TRACE_ID", f"manual-{args.category}")
    lines = [
        f"trace_id={trace_id}",
        f"release_id={os.environ.get('RELEASE_ID', '')}",
        f"snapshot_id={os.environ.get('SNAPSHOT_ID', '')}",
        f"delivered_count={summary.delivered_count}",
        f"failed_count={summary.failed_count}",
        f"delivery_status={'delivered' if summary.failed_count == 0 else 'partial' if summary.delivered_count else 'failed'}",
        f"failed_recipient_hashes={','.join(summary.failed_recipient_hashes)}",
    ]
    destination = os.environ.get("GITHUB_OUTPUT")
    if destination:
        with open(destination, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))
    if not summary.any_delivered:
        raise RuntimeError("Telegram delivery failed for every configured recipient")
    print(f"Telegram delivery: {summary.delivered_count} delivered, {summary.failed_count} failed")


if __name__ == "__main__":
    main()
