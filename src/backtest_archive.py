"""Audit the point-in-time archive required for honest strategy backtests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.four_strategy_walk_forward import survivorship_audit

REQUIRED_MANIFEST_KEYS = {
    "schema_version",
    "market",
    "bars_directory",
    "universe_snapshots",
    "fundamental_snapshots",
    "delisted_symbols_included",
}


def _read_json(path: Path) -> tuple[Any | None, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, f"missing: {path.name}"
    except json.JSONDecodeError:
        return None, f"invalid JSON: {path.name}"


def audit_backtest_archive(root: Path, market: str) -> dict[str, Any]:
    """Return blockers instead of allowing a misleading performance run.

    The archive intentionally requires dated membership and fundamental
    snapshots.  Current ETF constituents are rejected by ``survivorship_audit``
    and missing delisted symbols remain an explicit research blocker.
    """
    root = Path(root)
    manifest_path = root / market / "manifest.json"
    manifest, manifest_error = _read_json(manifest_path)
    reasons: list[str] = [manifest_error] if manifest_error else []
    if not isinstance(manifest, dict):
        return {
            "status": "incomplete",
            "market": market,
            "root": str(root),
            "reasons": reasons or ["manifest must be an object"],
            "bar_file_count": 0,
        }

    missing = sorted(REQUIRED_MANIFEST_KEYS - set(manifest))
    if missing:
        reasons.append(f"manifest fields missing: {', '.join(missing)}")
    if manifest.get("market") != market:
        reasons.append("manifest market does not match requested market")
    if manifest.get("delisted_symbols_included") is not True:
        reasons.append("delisted symbols are not confirmed in the archive")

    universe_path = root / market / str(manifest.get("universe_snapshots", ""))
    fundamentals_path = root / market / str(manifest.get("fundamental_snapshots", ""))
    universe, universe_error = _read_json(universe_path)
    fundamentals, fundamentals_error = _read_json(fundamentals_path)
    if universe_error:
        reasons.append(universe_error)
    if fundamentals_error:
        reasons.append(fundamentals_error)
    if not isinstance(universe, list):
        reasons.append("universe snapshots must be a JSON list")
        universe = []
    if not isinstance(fundamentals, list):
        reasons.append("fundamental snapshots must be a JSON list")
        fundamentals = []

    audit = survivorship_audit(universe, market=market)
    reasons.extend(audit["reasons"])
    if not fundamentals:
        reasons.append("no point-in-time fundamental snapshots supplied")
    elif any(item.get("point_in_time") is not True for item in fundamentals if isinstance(item, dict)):
        reasons.append("one or more fundamental snapshots are not point-in-time")

    bars_directory = root / market / str(manifest.get("bars_directory", "bars"))
    bar_files = sorted(bars_directory.glob("*.csv")) if bars_directory.is_dir() else []
    if not bar_files:
        reasons.append("no archived OHLCV CSV files supplied")
    return {
        "status": "ready" if not reasons else "incomplete",
        "market": market,
        "root": str(root),
        "manifest": str(manifest_path),
        "bar_file_count": len(bar_files),
        "universe_snapshot_count": len(universe),
        "fundamental_snapshot_count": len(fundamentals),
        "survivorship_audit": audit,
        "reasons": reasons,
    }
