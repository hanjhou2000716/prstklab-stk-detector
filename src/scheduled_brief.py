"""Create a short market brief, refresh dashboard data, and notify Telegram."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.config import get_settings
from src.briefing_cards import build_briefing_snapshot
from src.market_data import build_market_snapshot
from src.refresh_market_data import write_snapshot
from src.telegram_client import send_briefs


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
MAX_BRIEF_LENGTH = 30

# External scheduler calls are accepted only around their declared Taiwan-time
# slot. This prevents an accidental early backup request from consuming the
# same-day idempotency lock that belongs to the real scheduled briefing.
STRICT_SLOT_WINDOWS = {
    "morning": (5 * 60 + 30, 6 * 60 + 30),
    "pre_open": (8 * 60 + 15, 9 * 60 + 15),
    "intraday": (9 * 60 + 30, 10 * 60 + 30),
    "midday": (11 * 60 + 15, 12 * 60 + 15),
    "afternoon": (12 * 60 + 45, 13 * 60 + 45),
    "post_close": (13 * 60 + 55, 14 * 60 + 55),
    "us_premarket_summer": (20 * 60 + 30, 21 * 60 + 30),
    "us_premarket_winter": (21 * 60 + 30, 22 * 60 + 30),
}


def is_new_york_daylight_saving(now: datetime) -> bool:
    """Return whether New York observes daylight saving time at this instant."""
    new_york_now = now.astimezone(ZoneInfo("America/New_York"))
    return new_york_now.dst() not in (None, timedelta(0))


def _strict_slot_at(now: datetime) -> str | None:
    """Return the one external-scheduler slot permitted at this local time."""
    minute = now.hour * 60 + now.minute
    for slot, (start, end) in STRICT_SLOT_WINDOWS.items():
        if start <= minute <= end:
            if slot == "us_premarket_summer":
                return "us_premarket" if is_new_york_daylight_saving(now) else None
            if slot == "us_premarket_winter":
                return "us_premarket" if not is_new_york_daylight_saving(now) else None
            return slot
    return None


def resolve_slot(value: str, now: datetime | None = None, *, strict_window: bool = False) -> str | None:
    """Resolve an explicit slot or choose the nearest Taiwan-time briefing slot."""
    local_now = now or datetime.now(ZoneInfo("Asia/Taipei"))
    if strict_window:
        matched = _strict_slot_at(local_now)
        if matched is None or (value != "auto" and value != matched):
            return None
        return matched
    if value != "auto":
        return value
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
    if hour < 21:
        return "us_premarket"
    # Both 21:00 and 22:00 Taiwan time are 09:00 in New York.  The active
    # one depends on daylight saving time; the other invocation is skipped.
    daylight_saving = is_new_york_daylight_saving(local_now)
    if hour == 21:
        return "us_premarket" if daylight_saving else None
    return "us_premarket" if not daylight_saving else None


def _pick_quote(snapshot: dict, slot: str) -> dict | None:
    preferred_ticker = "2330" if slot in {
        "pre_open", "intraday", "midday", "afternoon", "post_close"
    } else "NVDA"
    quotes = snapshot.get("quotes", [])
    return next((quote for quote in quotes if quote["ticker"] == preferred_ticker), None) or (
        quotes[0] if quotes else None
    )


def _pick_event(snapshot: dict, slot: str) -> dict | None:
    """Keep Taiwan sessions Taiwan-first and US sessions US-first in the watch brief."""
    events = (snapshot.get("events") or {}).get("items", [])
    preferred = ("TAIEX", "TPEx") if slot in {
        "pre_open", "intraday", "midday", "afternoon", "post_close"
    } else ("SOX", "NASDAQ", "S&P 500")
    for ticker in preferred:
        selected = next(
            (event for event in events if event.get("instrument", {}).get("ticker") == ticker),
            None,
        )
        if selected:
            return selected
    return events[0] if events else None


def build_brief(snapshot: dict, slot: str) -> str:
    """Create a neutral, watch-friendly brief that always stays under 30 characters."""
    label = SLOT_LABELS[slot]
    quote = _pick_quote(snapshot, slot)
    event = _pick_event(snapshot, slot)
    event_label = event.get("brief_title") if event else None
    legacy_event_label = event.get("short_label") if event else None
    if not quote:
        return f"{label}｜市場資料暫時無法取得"
    pct = quote.get("change_percent")
    if pct is None:
        return f"{label}｜{quote['ticker']} 資料暫時無法取得"
    icon = "📈" if pct > 1 else "📉" if pct < -1 else "🟰"
    suffix = f"{quote['ticker']}{icon}{pct:+.1f}%"
    if event_label:
        # The event card title is designed for a watch notification: clear
        # situation, move type and risk state, while the Mini App holds detail.
        return f"{label}｜{str(event_label)[:MAX_BRIEF_LENGTH - len(label) - 1]}"
    if not legacy_event_label:
        return f"{label}｜{suffix}"

    # Keep the market and move first. If a news label is unusually long,
    # truncate only that optional context instead of letting Telegram reject
    # the entire watch-sized brief.
    prefix = f"{label}｜"
    available = MAX_BRIEF_LENGTH - len(prefix) - len(suffix) - 1  # final separator
    if available <= 0:
        return f"{prefix}{suffix}"
    return f"{prefix}{str(legacy_event_label)[:available]}｜{suffix}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="產製並發送 PRStK 定時快報")
    parser.add_argument("--slot", choices=("auto", *SLOT_LABELS), default="auto")
    parser.add_argument("--print-window", action="store_true")
    parser.add_argument("--strict-window", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    now = datetime.now(ZoneInfo("Asia/Taipei"))
    slot = resolve_slot(args.slot, now, strict_window=args.strict_window)
    if args.print_window:
        print(f"should_run={'true' if slot else 'false'}")
        print(f"slot={slot or 'skip'}")
        print(f"key={now.date().isoformat()}-{slot or 'skip'}")
        return

    if slot is None:
        print("此時段不符合目前美國夏令／冬令時間，略過快報。")
        return

    settings = get_settings()
    if not settings.telegram_ready:
        raise RuntimeError("缺少 Telegram 設定，未發送快報。")
    snapshot = build_market_snapshot()
    snapshot["briefing"] = build_briefing_snapshot(snapshot, slot)
    write_snapshot(snapshot)
    brief = build_brief(snapshot, slot)
    results = send_briefs(
        token=settings.telegram_bot_token or "",
        chat_ids=settings.telegram_chat_ids,
        text=brief,
        dashboard_url=settings.dashboard_url,
    )
    delivered = sum(result.delivered for result in results)
    unavailable = [result.chat_id for result in results if not result.delivered]
    print(f"已發送 {slot} 快報給 {delivered}/{len(results)} 位收件人。")
    if unavailable:
        print("以下收件人尚未啟動或已封鎖 Bot，略過本次發送：" + ", ".join(unavailable))


if __name__ == "__main__":
    main()
