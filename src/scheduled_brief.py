"""Create a short market brief, refresh dashboard data, and notify Telegram."""

from __future__ import annotations

import argparse
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import get_settings
from src.market_data import build_market_snapshot
from src.refresh_market_data import write_snapshot
from src.telegram_client import send_brief


SLOT_LABELS = {
    "morning": "晨報",
    "pre_open": "盤前",
    "intraday": "盤中",
    "midday": "午報",
    "afternoon": "午盤",
    "post_close": "盤後",
    "us_premarket": "美股盤前",
    "us_open": "美股開盤",
}


def resolve_slot(value: str, now: datetime | None = None) -> str:
    """Resolve an explicit slot or choose the nearest Taiwan-time briefing slot."""
    if value != "auto":
        return value
    local_now = now or datetime.now(ZoneInfo("Asia/Taipei"))
    hour = local_now.hour
    if hour < 8:
        return "morning"
    if hour < 10:
        return "pre_open"
    if hour < 11:
        return "intraday"
    if hour < 13:
        return "midday"
    if hour < 14:
        return "afternoon"
    if hour < 18:
        return "post_close"
    if hour < 22:
        return "us_premarket"
    return "us_open"


def _pick_quote(snapshot: dict, slot: str) -> dict | None:
    preferred_ticker = "2330" if slot in {
        "pre_open", "intraday", "midday", "afternoon", "post_close"
    } else "NVDA"
    quotes = snapshot.get("quotes", [])
    return next((quote for quote in quotes if quote["ticker"] == preferred_ticker), None) or (
        quotes[0] if quotes else None
    )


def build_brief(snapshot: dict, slot: str) -> str:
    """Create a neutral, watch-friendly brief that always stays under 30 characters."""
    label = SLOT_LABELS[slot]
    quote = _pick_quote(snapshot, slot)
    if not quote:
        return f"{label}｜市場資料暫時無法取得"
    pct = quote.get("change_percent")
    if pct is None:
        return f"{label}｜{quote['ticker']} 資料暫時無法取得"
    icon = "📈" if pct > 1 else "📉" if pct < -1 else "🟰"
    return f"{label}｜{quote['ticker']}{icon}{pct:+.1f}%"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="產製並發送 PRStK 定時快報")
    parser.add_argument("--slot", choices=("auto", *SLOT_LABELS), default="auto")
    parser.add_argument("--print-window", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    now = datetime.now(ZoneInfo("Asia/Taipei"))
    slot = resolve_slot(args.slot, now)
    if args.print_window:
        print(f"slot={slot}")
        print(f"key={now.date().isoformat()}-{slot}")
        return

    settings = get_settings()
    if not settings.telegram_ready:
        raise RuntimeError("缺少 Telegram 設定，未發送快報。")
    snapshot = build_market_snapshot()
    write_snapshot(snapshot)
    brief = build_brief(snapshot, slot)
    result = send_brief(
        token=settings.telegram_bot_token or "",
        chat_id=settings.telegram_chat_id or "",
        text=brief,
        dashboard_url=settings.dashboard_url,
    )
    print(f"已發送 {slot} 快報，訊息 ID：{result.message_id}。")


if __name__ == "__main__":
    main()
