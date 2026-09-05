"""Exchange-aware research refresh slots.

The GitHub cron is deliberately wider than the actual market close windows.
This module is the source of truth for the trading date and slot identity so a
delayed cron, a backup dispatch, and a manual retry all address the same
research run.
"""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, timedelta
from datetime import time as clock_time
from typing import Any
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal

MARKETS = ("taiwan", "us")
TAIPEI = ZoneInfo("Asia/Taipei")


def _calendar(market: str) -> Any:
    if market == "taiwan":
        return mcal.get_calendar("XTAI")
    if market == "us":
        return mcal.get_calendar("XNYS")
    raise ValueError(f"unsupported research market: {market}")


def _session(market: str, day: date) -> tuple[datetime, datetime] | None:
    calendar = _calendar(market)
    schedule = calendar.schedule(start_date=day.isoformat(), end_date=day.isoformat())
    if schedule.empty:
        return None
    row = schedule.iloc[0]
    opened = row["market_open"].to_pydatetime().astimezone(UTC)
    closed = row["market_close"].to_pydatetime().astimezone(UTC)
    return opened, closed


def slot_for(market: str, trading_date: date) -> str:
    """Return a stable identity shared by scheduled and manual retries."""
    return f"{market}:{trading_date.isoformat()}:close-research"


def due_slot(market: str, *, now: datetime | None = None) -> dict[str, Any] | None:
    """Return the newest due close-research slot, including a delayed run.

    GitHub Actions can start after midnight Taipei time.  Looking only at
    ``now.date()`` loses the prior US Friday session during the Taiwan
    weekend, so walk back over recent calendar days and keep the original
    exchange trading date in the slot identity.
    """
    now_utc = (now or datetime.now(UTC)).astimezone(UTC)
    current_session = _session(market, now_utc.date())
    if current_session is not None:
        _opened, closed = current_session
        # XTAI's exchange close is 13:30 Taipei, while the research contract
        # intentionally starts at 15:30 so all official closing data has time
        # to settle.  Do not derive this slot from the market-close timestamp.
        due_at = (
            datetime.combine(now_utc.date(), clock_time(15, 30), tzinfo=TAIPEI).astimezone(UTC)
            if market == "taiwan" else closed + timedelta(hours=1)
        )
        if now_utc < due_at:
            return None
        trading_date = now_utc.date()
        return {
            "market": market,
            "trading_date": trading_date.isoformat(),
            "slot_key": slot_for(market, trading_date),
            "due_at": due_at.isoformat(),
            "market_close": closed.isoformat(),
        }
    # The US session commonly becomes due on Saturday in Taipei.  Preserve
    # that production slot across the local weekend; Taiwan itself has no
    # weekend close task to resolve here.
    if market != "us":
        return None
    for days_back in range(1, 11):
        trading_date = now_utc.date() - timedelta(days=days_back)
        session = _session(market, trading_date)
        if session is None:
            continue
        _opened, closed = session
        due_at = (
            datetime.combine(trading_date, clock_time(15, 30), tzinfo=TAIPEI).astimezone(UTC)
            if market == "taiwan" else closed + timedelta(hours=1)
        )
        if now_utc < due_at:
            continue
        return {
            "market": market,
            "trading_date": trading_date.isoformat(),
            "slot_key": slot_for(market, trading_date),
            "due_at": due_at.isoformat(),
            "market_close": closed.isoformat(),
        }
    return None


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Resolve an exchange-aware research slot")
    parser.add_argument("--market", choices=(*MARKETS, "both"), required=True)
    parser.add_argument("--now", help="UTC ISO timestamp for deterministic tests")
    args = parser.parse_args()
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(UTC)
    markets = MARKETS if args.market == "both" else (args.market,)
    due = [item for market in markets if (item := due_slot(market, now=now))]
    print({"due": bool(due), "slots": due})
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
