"""De-duplicated Telegram alerting for fresh first-party macro releases."""

from __future__ import annotations

import argparse
import hashlib
import os
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.config import get_settings
from src.finance_intel_policy import polling_rule
from src.market_data import build_market_snapshot
from src.refresh_market_data import write_snapshot
from src.telegram_client import send_briefs, validate_brief


def _is_taiwan_market_window(now: datetime | None = None) -> bool:
    """Return whether Taiwan-session price alerts should lead the queue."""
    local_now = now or datetime.now(ZoneInfo("Asia/Taipei"))
    if local_now.tzinfo is None:
        local_now = local_now.replace(tzinfo=ZoneInfo("Asia/Taipei"))
    else:
        local_now = local_now.astimezone(ZoneInfo("Asia/Taipei"))
    return local_now.weekday() < 5 and time(8, 45) <= local_now.time() <= time(13, 30)


def select_official_event(
    snapshot: dict[str, Any], now: datetime | None = None, *, baseline_official: bool = False
) -> dict[str, Any] | None:
    """Select a verified official release, then a threshold price signal.

    The price signal fallback is constrained by ``event_alerts`` thresholds, so
    routine price refreshes never become Telegram notifications.
    """
    items = snapshot.get("official_events", {}).get("items", [])
    detailed_events = snapshot.get("events", {}).get("items", [])
    if items and not baseline_official:
        for item in items:
            if item.get("importance") != "high-risk":
                return item
            # A black-swan candidate must be confirmed by a related public
            # market move before it becomes a Telegram alert. It remains in
            # the dashboard as an observation when confirmation is absent.
            detailed = next(
                (
                    event for event in detailed_events
                    if event.get("url") == item.get("url")
                    and (event.get("impact_confirmation") or {}).get("confirmed")
                ),
                None,
            )
            if detailed:
                return detailed
    signals = [event for event in snapshot.get("events", {}).get("items", []) if event.get("kind") == "market_signal"]
    if _is_taiwan_market_window(now):
        # During the Taiwan session, a broad Taiwan price signal has priority.
        # Commodity/crypto moves remain visible in the Mini App unless paired
        # with a verified official event above.
        taiwan_signal = next((event for event in signals if (event.get("instrument") or {}).get("ticker") == "TAIEX"), None)
        if taiwan_signal:
            return taiwan_signal
        # Keep the Taiwan session focused, but do not suppress a genuinely
        # broad overseas equity signal merely because Taiwan is quiet.
        return next(
            (
                event for event in signals
                if (event.get("instrument") or {}).get("ticker") in {"NASDAQ", "SOX", "S&P500", "DJIA", "NIKKEI", "KOSPI"}
            ),
            None,
        )
    return signals[0] if signals else None


def event_key(event: dict[str, Any] | None) -> str:
    """Create a stable idempotency key from source facts, not a rendered message."""
    if not event:
        return "none"
    if event.get("kind") == "market_signal":
        instrument = event.get("instrument") or {}
        # A worsening move or a fast rebound after a sell-off is a distinct
        # public observation. Repeated bars in the same state are not.
        material_parts = [
            "price", instrument.get("ticker", "market"), instrument.get("quote_date", "unknown"),
            event.get("signal_state", event.get("risk_level", "觀察")),
        ]
        if event.get("realert_interval_minutes") and instrument.get("quote_time"):
            # Bucket a persistent Taiwan high-risk move by local quote hour:
            # at most one reminder per hour, while a worsening stage keeps a
            # different key and can be sent without waiting for the hour.
            material_parts.append(str(instrument["quote_time"])[:13])
        material = "|".join(str(value) for value in material_parts)
    else:
        # A same-topic official release is only eligible once per configured
        # cooling window. Explicit escalation can bypass this by retaining the
        # source headline in the key.
        topic = str(event.get("topic_key") or event.get("source_key") or event.get("short_label") or "official")
        released_at = str(event.get("released_at") or "")
        try:
            published = datetime.fromisoformat(released_at.replace("Z", "+00:00"))
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            bucket = int(published.timestamp() // (int(polling_rule("topicCooldownMinutes")) * 60))
        except ValueError:
            bucket = released_at
        material_parts = ["official", topic, bucket]
        if event.get("escalation"):
            material_parts.append(str(event.get("title", "")))
        material = "|".join(str(value) for value in material_parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def build_official_event_brief(event: dict[str, Any]) -> str:
    """Make a neutral watch-sized alert for an official event or price move."""
    if event.get("kind") == "market_signal":
        text = f"快訊｜{event.get('brief_title') or event.get('short_label', '價格訊號')}"
        instrument = event.get("instrument") or {}
        ticker = str(instrument.get("ticker") or "市場")
        label = "台指" if ticker == "TAIEX" else ticker
        percent = instrument.get("change_percent")
        if percent is None:
            text = f"快訊｜{event.get('brief_title') or event.get('short_label', '價格訊號')}"[:30]
            validate_brief(text)
            return text
        move = f"{float(percent):+.1f}%" if percent is not None else "波動"
        pattern = str(event.get("pattern") or "價格訊號")
        risk = str(event.get("risk_level") or "觀察")
        text = f"快訊｜{label} {move}｜{pattern}｜{risk}"
        text = text[:30]
        validate_brief(text)
        return text
    label = " ".join(event.get("short_label", "官方事件").split())
    title = " ".join(event.get("brief_summary") or event.get("title", "").split())
    text = f"快訊｜{label}｜{title}"
    text = text[:30]
    validate_brief(text)
    return text


def prepare_snapshot() -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Refresh the public snapshot before the Mini App button is sent."""
    snapshot = build_market_snapshot()
    write_snapshot(snapshot)
    # The first deployment observes current official headlines but avoids
    # immediately replaying them as alerts. Price signals remain eligible.
    baseline_official = os.getenv("OFFICIAL_EVENT_BASELINE_READY") == "false"
    return snapshot, select_official_event(snapshot, baseline_official=baseline_official)


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


def write_send_output(sent: bool, reason: str) -> None:
    """Expose delivery result to GitHub Actions without failing a safe skip."""
    lines = [f"sent={'true' if sent else 'false'}", f"reason={reason}"]
    destination = os.getenv("GITHUB_OUTPUT")
    if destination:
        with Path(destination).open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))


def send_current_event(expected_key: str | None = None) -> bool:
    """Send one verified event, safely skipping it if it changes between steps."""
    _, event = prepare_snapshot()
    current_key = event_key(event)
    if not event or (expected_key and current_key != expected_key):
        # A newer event can arrive between the pre-send check and delivery.
        # Keep the workflow green while avoiding stale delivery or a stale lock.
        write_send_output(False, "event_changed_before_delivery")
        print("Official event changed before delivery; skipped safely.")
        return False
    settings = get_settings()
    if not settings.telegram_ready:
        raise RuntimeError("缺少 Telegram 設定，無法送出官方事件快訊")
    send_briefs(
        token=settings.telegram_bot_token or "",
        chat_ids=settings.telegram_chat_ids,
        text=build_official_event_brief(event),
        dashboard_url=settings.dashboard_url,
    )
    write_send_output(True, "sent")
    return True


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
