"""Validate checked-in Mini App artifacts without contacting external APIs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.production_acceptance import validate_production_bundle


def _load_json(path: Path, label: str, issues: list[str]) -> dict[str, Any] | None:
    if not path.is_file():
        issues.append(f"{label} missing: {path}")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        issues.append(f"{label} invalid JSON: {type(exc).__name__}")
        return None
    if not isinstance(value, dict):
        issues.append(f"{label} must be a JSON object")
        return None
    return value


def _require_keys(value: dict[str, Any], keys: tuple[str, ...], label: str, issues: list[str]) -> None:
    missing = [key for key in keys if key not in value]
    if missing:
        issues.append(f"{label} missing keys: {', '.join(missing)}")


def _audit_market(value: dict[str, Any], issues: list[str], warnings: list[str]) -> dict[str, int]:
    _require_keys(value, ("generated_at", "scan", "indices", "quotes", "source_health"), "market", issues)
    if not isinstance(value.get("scan"), dict):
        issues.append("market.scan must be an object")
    indices = value.get("indices")
    quotes = value.get("quotes")
    if not isinstance(indices, list) or not indices:
        issues.append("market.indices must contain at least one card")
        indices = []
    if not isinstance(quotes, list):
        issues.append("market.quotes must be an array")
        quotes = []
    required_quote_keys = ("ticker", "price", "quote_date", "source_label", "quote_basis_label", "freshness")
    for number, row in enumerate([*indices, *quotes], start=1):
        if not isinstance(row, dict):
            issues.append(f"market quote {number} must be an object")
            continue
        _require_keys(row, required_quote_keys, f"market quote {number}", issues)
    health = value.get("source_health")
    if not isinstance(health, dict):
        issues.append("market.source_health must be an object")
    else:
        gaps = health.get("data_gaps")
        if isinstance(gaps, list) and gaps:
            warnings.append(f"market source gaps: {len(gaps)}")
    return {"indices": len(indices), "quotes": len(quotes)}


def _audit_research(value: dict[str, Any], issues: list[str], warnings: list[str]) -> dict[str, int]:
    _require_keys(value, ("schema_version", "sources", "candidates", "health", "generated_at"), "research", issues)
    sources = value.get("sources")
    candidates = value.get("candidates")
    if not isinstance(sources, list) or not sources:
        issues.append("research.sources must contain at least one strategy source")
        sources = []
    if not isinstance(candidates, list):
        issues.append("research.candidates must be an array")
        candidates = []
    for number, source in enumerate(sources, start=1):
        if not isinstance(source, dict):
            issues.append(f"research source {number} must be an object")
            continue
        _require_keys(source, ("market", "strategy", "scan_state", "status"), f"research source {number}", issues)
        if source.get("scan_state") in {"failed", "building"}:
            warnings.append(f"research source {number} state: {source.get('scan_state')}")
    health = value.get("health")
    if isinstance(health, dict) and health.get("is_expired"):
        warnings.append("research report is expired")
    elif not isinstance(health, dict):
        issues.append("research.health must be an object")
    return {"sources": len(sources), "candidates": len(candidates)}


def audit_artifacts(
    *,
    market_path: Path = Path("site/data/market.json"),
    research_path: Path = Path("site/data/research-report.json"),
    index_path: Path = Path("site/index.html"),
    manifest_path: Path = Path("site/data/release-manifest.json"),
) -> dict[str, Any]:
    """Return a non-secret structural audit of the files published to Pages."""
    issues: list[str] = []
    warnings: list[str] = []
    market = _load_json(market_path, "market", issues)
    research = _load_json(research_path, "research", issues)
    manifest = _load_json(manifest_path, "release manifest", issues)
    if not index_path.is_file() or index_path.stat().st_size == 0:
        issues.append(f"Mini App entry missing or empty: {index_path}")
    market_counts = _audit_market(market, issues, warnings) if market else {"indices": 0, "quotes": 0}
    research_counts = _audit_research(research, issues, warnings) if research else {"sources": 0, "candidates": 0}
    if manifest and market and research and manifest.get("event_snapshot_id"):
        events = _load_json(Path("site/data/event-ledger.json"), "events", issues)
        if events:
            acceptance = validate_production_bundle(manifest=manifest, market=market, research=research, events=events)
            warnings.extend(f"production acceptance: {error}" for error in acceptance.errors)
    return {
        "ok": not issues,
        "issues": issues,
        "warnings": warnings,
        "market": market_counts,
        "research": research_counts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate checked-in Mini App artifacts")
    parser.add_argument("--market", type=Path, default=Path("site/data/market.json"))
    parser.add_argument("--research", type=Path, default=Path("site/data/research-report.json"))
    parser.add_argument("--index", type=Path, default=Path("site/index.html"))
    parser.add_argument("--manifest", type=Path, default=Path("site/data/release-manifest.json"))
    args = parser.parse_args()
    report = audit_artifacts(market_path=args.market, research_path=args.research, index_path=args.index, manifest_path=args.manifest)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
