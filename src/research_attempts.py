"""Persistent, bounded attempts for exchange-close research slots.

The state lives on the data-only release branch so delayed cron runs and
manual retries share the same lease.  It contains no source payloads or
secrets: only slot/strategy identity, rule version, and retry timestamps.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RETRY_INTERVAL = timedelta(hours=1)
CURRENT_TW_VALUE_RULE = "tw_value_total_equity_quality_v3"
STRATEGIES = ("momentum", "price_action", "resonance", "value")


def _now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(UTC)
    return current.astimezone(UTC)


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _slot_pairs(slot_key: str, target_market: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for token in str(slot_key or "").split(","):
        parts = token.split(":")
        if len(parts) >= 3 and parts[0] in {"taiwan", "us"} and (target_market in {"both", parts[0]}):
            pairs.append((parts[0], token))
    return pairs


def rule_version(market: str, strategy: str) -> str:
    if market == "taiwan" and strategy == "value":
        return CURRENT_TW_VALUE_RULE
    return "legacy"


def load_attempts(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"schema_version": SCHEMA_VERSION, "slots": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("slots"), dict):
        return {"schema_version": SCHEMA_VERSION, "slots": {}}
    return {"schema_version": SCHEMA_VERSION, "slots": payload["slots"]}


def save_attempts(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def claim_strategies(
    path: Path,
    *,
    slot_key: str,
    target_market: str,
    strategies: list[str],
    now: datetime | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    retry_interval: timedelta = DEFAULT_RETRY_INTERVAL,
) -> dict[str, Any]:
    """Claim strategies that are due for every market in the slot.

    A strategy is allowed only when all selected market/strategy pairs are
    due.  This conservative rule matters for a ``both`` run: it prevents one
    market from consuming a new attempt while the other market is still in its
    hourly cooldown.
    """
    current = _now(now)
    selected = [strategy for strategy in strategies if strategy in STRATEGIES]
    markets = _slot_pairs(slot_key, target_market)
    if target_market == "both" and {market for market, _slot in markets} != {"taiwan", "us"}:
        return {
            "allowed_strategies": [],
            "suppressed": {strategy: "slot_incomplete" for strategy in selected},
            "claims": {},
            "slot_key": slot_key,
            "max_attempts": max_attempts,
            "retry_interval_seconds": int(retry_interval.total_seconds()),
        }
    payload = load_attempts(path)
    slots = payload.setdefault("slots", {})
    allowed: list[str] = []
    suppressed: dict[str, str] = {}
    claims: dict[str, dict[str, Any]] = {}
    for strategy in selected:
        pair_reasons: list[str] = []
        pair_entries: list[tuple[str, str, dict[str, Any]]] = []
        for market, slot in markets:
            identity = f"{slot}:{strategy}:{rule_version(market, strategy)}"
            entry = slots.get(identity) if isinstance(slots.get(identity), dict) else {}
            attempts = int(entry.get("attempts", 0) or 0)
            previous = _parse_time(entry.get("last_attempt_at"))
            if attempts >= max_attempts:
                pair_reasons.append("attempt_limit_reached")
            elif previous is not None and current < previous + retry_interval:
                pair_reasons.append("retry_cooldown")
            pair_entries.append((market, identity, entry))
        if pair_reasons:
            suppressed[strategy] = sorted(set(pair_reasons))[0]
            continue
        if not pair_entries:
            suppressed[strategy] = "slot_unavailable"
            continue
        strategy_claims: dict[str, Any] = {}
        for market, identity, entry in pair_entries:
            attempts = int(entry.get("attempts", 0) or 0) + 1
            next_retry = current + retry_interval
            record = {
                "market": market,
                "strategy": strategy,
                "rule_version": rule_version(market, strategy),
                "attempts": attempts,
                "last_attempt_at": current.isoformat(),
                "next_retry_at": next_retry.isoformat(),
            }
            slots[identity] = record
            strategy_claims[market] = record
        allowed.append(strategy)
        claims[strategy] = strategy_claims
    payload["updated_at"] = current.isoformat()
    save_attempts(path, payload)
    return {
        "allowed_strategies": sorted(allowed),
        "suppressed": suppressed,
        "claims": claims,
        "slot_key": slot_key,
        "max_attempts": max_attempts,
        "retry_interval_seconds": int(retry_interval.total_seconds()),
    }


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Claim a bounded research slot attempt")
    parser.add_argument("--path", default="data/research-attempts.json")
    parser.add_argument("--slot-key", default=os.getenv("RESEARCH_SLOT_KEY", ""))
    parser.add_argument("--target-market", choices=("taiwan", "us", "both"), required=True)
    parser.add_argument("--strategies", default=",".join(STRATEGIES))
    args = parser.parse_args()
    result = claim_strategies(
        Path(args.path), slot_key=args.slot_key, target_market=args.target_market,
        strategies=[item.strip() for item in args.strategies.split(",")],
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
