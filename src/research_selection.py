"""Resolve the market strategies required for one due research slot."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path
from typing import Any

from src.research_attempts import STRATEGIES, claim_strategies, rule_version


def _slot_dates(slot_key: str, target_market: str) -> dict[str, str]:
    markets = ("taiwan", "us") if target_market == "both" else (target_market,)
    result: dict[str, str] = {}
    for token in str(slot_key or "").split(","):
        parts = token.strip().split(":")
        if len(parts) < 3 or parts[0] not in markets:
            continue
        try:
            result[parts[0]] = date.fromisoformat(parts[1]).isoformat()
        except ValueError:
            continue
    if set(result) != set(markets):
        raise ValueError("research_slot_market_date_incomplete")
    return result


def _source_is_current(
    source: dict[str, Any] | None, *, market: str, strategy: str, trading_date: str,
) -> bool:
    if not isinstance(source, dict):
        return False
    source_date = str(source.get("scan_trading_date") or "")[:10]
    if source_date != trading_date:
        return False
    if (
        source.get("scan_state") != "complete"
        or source.get("historical_fallback") is True
        or source.get("strategy_version_state") in {"historical", "unavailable"}
        or source.get("candidate_state") in {"building", "data_gap", "data_unavailable", "failed"}
        or str(source.get("rule_version") or "") != rule_version(market, strategy)
    ):
        return False
    return True


def resolve_strategy_selection(
    *, target_market: str, requested_strategy: str, action: str,
    slot_key: str, previous_report: dict[str, Any] | None,
) -> dict[str, Any]:
    if target_market not in {"taiwan", "us", "both"}:
        raise ValueError("research_target_market_invalid")
    if requested_strategy not in {"all", *STRATEGIES}:
        raise ValueError("research_target_strategy_invalid")
    if action not in {"scan", "resume_incomplete", "repair_state"}:
        raise ValueError("research_action_invalid")

    slot_dates = _slot_dates(slot_key, target_market)
    markets = tuple(slot_dates)
    source_rows = previous_report.get("sources", []) if isinstance(previous_report, dict) else []
    if not isinstance(source_rows, list):
        source_rows = []
    indexed: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in source_rows:
        if isinstance(row, dict):
            indexed.setdefault((str(row.get("market") or ""), str(row.get("strategy") or "")), []).append(row)

    requested = list(STRATEGIES) if requested_strategy == "all" else [requested_strategy]
    required_pairs: list[str] = []
    selected: list[str] = []
    current_pairs: list[str] = []
    if action == "repair_state":
        status = "repair_state"
    elif action == "resume_incomplete":
        strategies_to_check = list(STRATEGIES) if requested_strategy == "all" else [requested_strategy]
        if not source_rows:
            selected = strategies_to_check
            required_pairs = [f"{market}:{strategy}" for market in markets for strategy in selected]
        else:
            for strategy in strategies_to_check:
                strategy_needs_scan = False
                for market in markets:
                    rows = indexed.get((market, strategy), [])
                    current = len(rows) == 1 and _source_is_current(
                        rows[0], market=market, strategy=strategy,
                        trading_date=slot_dates[market],
                    )
                    if current:
                        current_pairs.append(f"{market}:{strategy}")
                    else:
                        strategy_needs_scan = True
                        required_pairs.append(f"{market}:{strategy}")
                if strategy_needs_scan:
                    selected.append(strategy)
        status = "scan_selected" if required_pairs else "current_noop"
    else:
        selected = requested
        required_pairs = [f"{market}:{strategy}" for market in markets for strategy in selected]
        status = "scan_selected"

    return {
        "schema_version": "research-selection-v1",
        "slot_key": slot_key,
        "slot_dates": slot_dates,
        "target_market": target_market,
        "action": action,
        "requested_strategy": requested_strategy,
        "selection_status": status,
        "selected_strategies": sorted(set(selected)),
        "selected_market_strategy_pairs": sorted(set(required_pairs)),
        "required_market_strategy_pairs": sorted(set(required_pairs)),
        "already_current_pairs": sorted(set(current_pairs)),
        "suppressed_market_strategy_pairs": {},
        "reason": "research_slot_already_current" if status == "current_noop" else "",
    }


def _write_env(result: dict[str, Any], *, due: bool) -> None:
    env_path = os.environ.get("GITHUB_ENV")
    if not env_path:
        return
    selected = set(result.get("selected_strategies", []))
    selected_pairs = set(result.get("selected_market_strategy_pairs", []))
    lines = [
        f"RUN_{strategy.upper()}={'true' if strategy in selected else 'false'}"
        for strategy in STRATEGIES
    ]
    for market in ("taiwan", "us"):
        for strategy in STRATEGIES:
            lines.append(
                f"RUN_{market.upper()}_{strategy.upper()}="
                f"{'true' if f'{market}:{strategy}' in selected_pairs else 'false'}"
            )
    noop = result.get("selection_status") == "current_noop"
    lines.extend((
        "SCANNED_STRATEGIES=" + ",".join(sorted(selected)),
        "SCANNED_PAIRS=" + ",".join(sorted(selected_pairs)),
        f"RESEARCH_NOOP={'true' if noop else 'false'}",
        f"RESEARCH_DUE={'false' if noop else 'true' if due else 'false'}",
        f"RESEARCH_SELECTION_STATUS={result.get('selection_status', 'unknown')}",
        f"RESEARCH_SELECTION_REASON={result.get('reason', '')}",
    ))
    with Path(env_path).open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-market", required=True)
    parser.add_argument("--target-strategy", default="all")
    parser.add_argument("--action", required=True)
    parser.add_argument("--slot-key", required=True)
    parser.add_argument("--previous-report", type=Path, required=True)
    parser.add_argument("--attempts", type=Path, default=Path("data/research-attempts.json"))
    args = parser.parse_args()
    try:
        try:
            previous = json.loads(args.previous_report.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            previous = {}
        result = resolve_strategy_selection(
            target_market=args.target_market,
            requested_strategy=args.target_strategy,
            action=args.action,
            slot_key=args.slot_key,
            previous_report=previous if isinstance(previous, dict) else {},
        )
        if (
            result["selection_status"] == "scan_selected"
            and os.getenv("SCAN_MODE", "production") == "production"
            and args.action != "repair_state"
        ):
            selected_pairs = set(result["selected_market_strategy_pairs"])
            allowed_pairs: set[str] = set()
            suppressed_pairs: dict[str, str] = {}
            claim_rows: dict[str, Any] = {}
            for market in result["slot_dates"]:
                market_strategies = sorted(
                    strategy for pair in selected_pairs
                    for pair_market, strategy in [pair.split(":", 1)]
                    if pair_market == market
                )
                if not market_strategies:
                    continue
                claim = claim_strategies(
                    args.attempts,
                    slot_key=args.slot_key,
                    target_market=market,
                    strategies=market_strategies,
                )
                allowed_pairs.update(f"{market}:{strategy}" for strategy in claim["allowed_strategies"])
                suppressed_pairs.update({
                    f"{market}:{strategy}": reason
                    for strategy, reason in claim["suppressed"].items()
                })
                claim_rows[market] = claim
            result["suppressed_market_strategy_pairs"] = suppressed_pairs
            result["selected_market_strategy_pairs"] = sorted(allowed_pairs)
            result["selected_strategies"] = sorted({pair.split(":", 1)[1] for pair in allowed_pairs})
            if not allowed_pairs and selected_pairs:
                result["selection_status"] = "blocked"
                result["reason"] = "research_attempts_suppressed_all_selected_strategies"
            elif allowed_pairs:
                result["selection_status"] = (
                    "scan_selected_with_suppressed_pairs" if suppressed_pairs else "scan_selected"
                )
                if suppressed_pairs:
                    result["reason"] = "some_due_market_strategy_pairs_suppressed_by_attempt_policy"
            result["attempt_claim"] = {
                "market_claims": claim_rows,
                "allowed_market_strategy_pairs": sorted(allowed_pairs),
                "suppressed_market_strategy_pairs": suppressed_pairs,
            }
        result_path = Path("research-artifacts/research-selection.json")
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        _write_env(result, due=os.getenv("RESEARCH_DUE") == "true")
        output_path = os.environ.get("GITHUB_OUTPUT")
        if output_path:
            with Path(output_path).open("a", encoding="utf-8") as handle:
                handle.write(f"status={result['selection_status']}\n")
                handle.write(f"reason={result['reason']}\n")
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_path:
            with Path(summary_path).open("a", encoding="utf-8") as handle:
                handle.write("## Research strategy selection\n\n")
                handle.write(f"- status: `{result['selection_status']}`\n")
                handle.write(f"- due slot: `{args.slot_key}`\n")
                handle.write(f"- selected: `{', '.join(result['selected_strategies']) or 'none'}`\n")
                handle.write(f"- selected market/strategy pairs: `{', '.join(result['selected_market_strategy_pairs']) or 'none'}`\n")
                handle.write(f"- already current: `{', '.join(result['already_current_pairs']) or 'none'}`\n")
                handle.write(f"- suppressed pairs: `{json.dumps(result['suppressed_market_strategy_pairs'], sort_keys=True)}`\n")
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if result["selection_status"] == "blocked":
            return 1
        return 0
    except (ValueError, OSError, UnicodeError) as exc:
        print(f"research_selection_error:{type(exc).__name__}:{str(exc)[:160]}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
