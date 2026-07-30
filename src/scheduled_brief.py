"""Create a short market brief, refresh dashboard data, and notify Telegram."""

from __future__ import annotations

import argparse
import os
from datetime import datetime
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
TAIWAN_SESSION_SLOTS = frozenset({"pre_open", "intraday", "midday", "afternoon"})

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
    "us_premarket": (20 * 60 + 30, 21 * 60 + 30),
}


def _strict_slot_at(now: datetime) -> str | None:
    """Return the one external-scheduler slot permitted at this local time."""
    minute = now.hour * 60 + now.minute
    for slot, (start, end) in STRICT_SLOT_WINDOWS.items():
        if start <= minute <= end:
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
    # This system has one fixed Taiwan-time pre-market report throughout the
    # year.  The content remains a public market briefing, not a claim that
    # the US cash session is about to open at the same local clock time.
    return "us_premarket" if hour == 21 else None


def _pick_quote(snapshot: dict, slot: str) -> dict | None:
    if slot in TAIWAN_SESSION_SLOTS:
        # Taiwan intraday reports lead with the broad market, not an
        # individual company.  Representative shares remain a fallback.
        items = [*(snapshot.get("indices") or []), *(snapshot.get("quotes") or [])]
        return next((item for item in items if item.get("ticker") == "TAIEX"), None) or next(
            (item for item in items if item.get("ticker") == "2330"), None
        ) or (items[0] if items else None)

    quotes = snapshot.get("quotes", [])
    return next((quote for quote in quotes if quote["ticker"] == "NVDA"), None) or (
        quotes[0] if quotes else None
    )


def _pick_event(snapshot: dict, slot: str) -> dict | None:
    """Prioritise the market currently relevant to the timed watch brief."""
    events = (snapshot.get("events") or {}).get("items", [])
    if slot in TAIWAN_SESSION_SLOTS:
        preferred = ("TAIEX", "TPEx")
    else:
        preferred = ("SOX", "NASDAQ", "S&P 500")
    for ticker in preferred:
        selected = next(
            (event for event in events if event.get("instrument", {}).get("ticker") == ticker),
            None,
        )
        if selected:
            return selected

    if slot in TAIWAN_SESSION_SLOTS:
        # During Taiwan trading hours, an overseas price-only move (Brent,
        # crypto, etc.) stays visible in the Mini App but must not replace the
        # Taiwan-market headline. A verified policy/macro/company event may.
        return next((event for event in events if event.get("kind") != "market_signal"), None)
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
    if event and event.get("kind") == "market_signal" and pct is not None:
        instrument = event.get("instrument") or quote
        market = "台指" if instrument.get("ticker") == "TAIEX" else str(instrument.get("ticker") or quote["ticker"])
        pattern = str(event.get("pattern") or "價格波動")
        return f"{label}｜{market} {float(pct):+.1f}%｜{pattern}"[:MAX_BRIEF_LENGTH]
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


def write_event_lock_key(event: dict | None) -> None:
    """Let a timed briefing suppress the same monitor alert immediately after."""
    if not event:
        return
    from src.official_event_monitor import event_key

    destination = os.getenv("GITHUB_OUTPUT")
    if destination:
        with open(destination, "a", encoding="utf-8") as handle:
            handle.write(f"event_key={event_key(event)}\n")


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
        print("此時段不在已設定的台灣時間快報窗口，略過快報。")
        return

    settings = get_settings()
    if not settings.telegram_ready:
        raise RuntimeError("缺少 Telegram 設定，未發送快報。")
    snapshot = build_market_snapshot()
    snapshot["briefing"] = build_briefing_snapshot(snapshot, slot)
    write_snapshot(snapshot)
    write_event_lock_key(_pick_event(snapshot, slot))
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
