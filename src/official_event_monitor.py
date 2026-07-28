"""De-duplicated Telegram alerting for fresh first-party macro releases."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
from typing import Any

from src.config import get_settings
from src.market_data import build_market_snapshot
from src.refresh_market_data import write_snapshot
from src.telegram_client import send_briefs, validate_brief


def select_official_event(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    """Select a verified official release, then a threshold price signal.

    The price signal fallback is constrained by ``event_alerts`` thresholds, so
    routine price refreshes never become Telegram notifications.
    """
    items = snapshot.get("official_events", {}).get("items", [])
    if items:
        return items[0]
    for event in snapshot.get("events", {}).get("items", []):
        if event.get("kind") == "market_signal":
            return event
    return None


def event_key(event: dict[str, Any] | None) -> str:
    """Create a stable idempotency key from source facts, not a rendered message."""
    if not event:
        return "none"
    if event.get("kind") == "market_signal":
        instrument = event.get("instrument") or {}
        # A worsening move or a fast rebound after a sell-off is a distinct
        # public observation. Repeated bars in the same state are not.
        material = "|".join(str(value) for value in (
            "price", instrument.get("ticker", "market"), instrument.get("quote_date", "unknown"),
            event.get("signal_state", event.get("risk_level", "觀察")),
        ))
    else:
        material = "|".join(str(event.get(key, "")) for key in ("url", "title", "released_at"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def build_official_event_brief(event: dict[str, Any]) -> str:
    """Make a neutral watch-sized alert for an official event or price move."""
    if event.get("kind") == "market_signal":
        text = f"快訊｜{event.get('brief_title') or event.get('short_label', '價格訊號')}"
        text = text[:30]
        validate_brief(text)
        return text
    label = " ".join(event.get("short_label", "官方事件").split())
    title = " ".join(event.get("title", "").split())
    text = f"快訊｜{label}｜{title}"
    text = text[:30]
    validate_brief(text)
    return text


def prepare_snapshot() -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Refresh the public snapshot before the Mini App button is sent."""
    snapshot = build_market_snapshot()
    write_snapshot(snapshot)
    return snapshot, select_official_event(snapshot)


def write_status_output(event: dict[str, Any] | None) -> None:
    """Write GitHub Actions outputs without mixing provider diagnostics into them."""
    lines = [
        f"should_send={'true' if event else 'false'}",
        f"key={event_key(event)}",
    ]
    destination = os.getenv("GITHUB_OUTPUT")
    if destination:
        with Path(destination).open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))


def send_current_event(expected_key: str | None = None) -> None:
    """Send one verified event, refusing a changed event between workflow steps."""
    _, event = prepare_snapshot()
    current_key = event_key(event)
    if not event or (expected_key and current_key != expected_key):
        raise RuntimeError("官方事件在送出前已不再是同一筆最新資料，已停止推播")
    settings = get_settings()
    if not settings.telegram_ready:
        raise RuntimeError("缺少 Telegram 設定，無法送出官方事件快訊")
    send_briefs(
        token=settings.telegram_bot_token or "",
        chat_ids=settings.telegram_chat_ids,
        text=build_official_event_brief(event),
        dashboard_url=settings.dashboard_url,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="監測官方重大事件與已核對價格訊號")
    parser.add_argument("--write-status", action="store_true")
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--expected-key")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.write_status:
        _, event = prepare_snapshot()
        write_status_output(event)
    if args.send:
        send_current_event(args.expected_key)
    if not args.write_status and not args.send:
        raise ValueError("請指定 --write-status 或 --send")


if __name__ == "__main__":
    main()
