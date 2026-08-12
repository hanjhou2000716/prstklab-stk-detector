"""Build a unified public-scan report for the dashboard or an Artifact."""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.instrument_master import InstrumentMaster
from src.release_manifest import content_snapshot_id
from src.research_fragments import merge_taiwan_scan_fragments
from src.research_health import assess_research_health
from src.research_report import build_research_report
from src.research_run_contract import attach_research_run
from src.research_scan_failures import apply_scan_failures, load_scan_failures

SCAN_MODES = {"production", "smoke", "debug"}


def attach_instrument_lineage(report: dict[str, Any], *, extend_from_candidates: bool = False) -> dict[str, Any]:
    """Stamp candidates with the exact public instrument registry used.

    Unknown symbols remain visible as ``unresolved`` research rows; this is
    lineage metadata, not a reason to invent a mapping or remove a candidate.
    """
    master = InstrumentMaster()
    # The compact registry contains only headline instruments.  Production
    # scan rows carry an explicit public ticker/name/market identity, so use
    # that identity to extend this run's registry without fuzzy matching.
    if extend_from_candidates:
        master = master.with_research_rows([
            item for item in report.get("candidates", []) if isinstance(item, dict)
        ])
    artifact = master.artifact()
    for candidate in report.get("candidates", []):
        if not isinstance(candidate, dict):
            continue
        candidate["instrument_master_id"] = artifact["registry_id"]
        candidate["instrument_master_version"] = artifact["schema_version"]
        query = str(candidate.get("ticker") or candidate.get("symbol") or "")
        try:
            resolved = master.resolve(query, market=candidate.get("market"))
        except (KeyError, ValueError):
            candidate["instrument_resolution"] = "unresolved"
            candidate["instrument_id"] = None
        else:
            candidate["instrument_resolution"] = "resolved"
            candidate["instrument_id"] = resolved.instrument_id
    report["instrument_master_id"] = artifact["registry_id"]
    report["instrument_master_version"] = artifact["schema_version"]
    return report


def default_sources(data_dir: Path) -> list[dict[str, str]]:
    return [
        {"path": str(data_dir / "taiwan-momentum-scan-0.csv"), "summary_path": str(data_dir / "taiwan-momentum-summary-0.json"), "market": "taiwan", "strategy": "momentum"},
        {"path": str(data_dir / "us-momentum-scan.csv"), "summary_path": str(data_dir / "us-momentum-summary.json"), "market": "us", "strategy": "momentum"},
        {"path": str(data_dir / "taiwan-price-action-scan-0.csv"), "summary_path": str(data_dir / "taiwan-price-action-summary-0.json"), "market": "taiwan", "strategy": "price_action"},
        {"path": str(data_dir / "us-price-action-scan.csv"), "summary_path": str(data_dir / "us-price-action-summary.json"), "market": "us", "strategy": "price_action"},
        {"path": str(data_dir / "taiwan-resonance-scan-0.csv"), "summary_path": str(data_dir / "taiwan-resonance-summary-0.json"), "market": "taiwan", "strategy": "resonance"},
        {"path": str(data_dir / "us-resonance-scan.csv"), "summary_path": str(data_dir / "us-resonance-summary.json"), "market": "us", "strategy": "resonance"},
        {"path": str(data_dir / "taiwan-value-scan.csv"), "summary_path": str(data_dir / "taiwan-value-summary.json"), "market": "taiwan", "strategy": "value"},
        {"path": str(data_dir / "us-value-scan.csv"), "summary_path": str(data_dir / "us-value-summary.json"), "market": "us", "strategy": "value"},
    ]


def write_report(report: dict, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_backtest_contract(path: Path | None) -> dict[str, Any] | None:
    """Load only the auditable release contract from a walk-forward artifact.

    The full backtest report is intentionally not copied into the public
    research artifact.  A missing, malformed, or blocked study remains an
    explicit observation-only state instead of being treated as a valid
    release.
    """
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {
            "publication_state": "blocked",
            "publish_eligible": False,
            "blocking_reasons": ["backtest artifact unavailable or invalid"],
        }
    contract = payload.get("backtest_release_contract") if isinstance(payload, dict) else None
    if not isinstance(contract, dict):
        return {
            "publication_state": "blocked",
            "publish_eligible": False,
            "blocking_reasons": ["backtest release contract missing"],
        }
    allowed = (
        "backtest_release", "market", "publication_state", "publish_eligible",
        "blocking_reasons", "strategy_registry", "performance_summary",
        "survivorship_audit", "research_only",
    )
    result = {key: contract[key] for key in allowed if key in contract}
    if not isinstance(result.get("blocking_reasons"), list) or not all(
        isinstance(reason, str) for reason in result.get("blocking_reasons", [])
    ):
        result["blocking_reasons"] = ["invalid backtest blocking reasons"]
        result["publish_eligible"] = False
    state = result.get("publication_state")
    if state not in {"ready", "blocked", "unavailable"}:
        result["publication_state"] = "blocked"
        result.setdefault("blocking_reasons", []).append("invalid backtest publication state")
        result["publish_eligible"] = False
    if result.get("publication_state") != "ready":
        result["publish_eligible"] = False
    return result


def attach_backtest_contract(report: dict, path: Path | None) -> dict:
    """Bind a validated walk-forward identity without unlocking advice.

    This is deliberately additive: no path means the report stays compatible
    with existing research scans, while Advice Gate continues to fail closed.
    """
    if path is None:
        report["backtest_release_status"] = "unavailable"
        return report
    contract = _load_backtest_contract(path)
    report["backtest_release_contract"] = contract or {
        "publication_state": "blocked",
        "publish_eligible": False,
        "blocking_reasons": ["backtest artifact unavailable or invalid"],
    }
    report["backtest_release_status"] = report["backtest_release_contract"].get("publication_state", "blocked")
    registry_rows = report["backtest_release_contract"].get("strategy_registry")
    registry_by_strategy = {
        str(item.get("strategy_id")): item
        for item in registry_rows
        if isinstance(item, dict) and item.get("strategy_id")
    } if isinstance(registry_rows, list) else {}
    # Bind the same identity to visible candidates so explainability cards and
    # Advice Gate cannot accidentally read a different or unstamped study.
    for candidate in report.get("candidates", []):
        if isinstance(candidate, dict):
            candidate["backtest_release"] = report["backtest_release_contract"].get("backtest_release")
            candidate["backtest_release_contract"] = report["backtest_release_contract"]
            strategy_id = str(candidate.get("strategy") or candidate.get("strategy_id") or "")
            if strategy_id in registry_by_strategy:
                candidate["strategy_registry"] = registry_by_strategy[strategy_id]
    return report


def attach_scan_contract(report: dict, scan_mode: str) -> dict:
    """Attach publication eligibility without changing candidate semantics."""
    sources = report.get("sources", [])
    def scope(source: dict) -> dict:
        mode = str(source.get("universe_mode") or "unknown")
        expected = int(source.get("universe_expected") or source.get("requested") or 0)
        scanned = int(source.get("universe_scanned") or source.get("requested") or 0)
        completed = int(source.get("universe_completed") or source.get("complete_records") or source.get("data_complete") or 0)
        failed = int(source.get("universe_failed") or source.get("failed_records") or source.get("failed") or 0)
        valid = mode == "full" and expected > 0 and scanned >= expected and completed + failed >= expected
        return {"mode": mode, "expected": expected, "scanned": scanned, "completed": completed, "failed": failed, "valid": valid}
    scopes = [scope(source) for source in sources]
    requested = sum(item["expected"] for item in scopes)
    completed = sum(item["completed"] for item in scopes)
    failed = sum(item["failed"] for item in scopes)
    states = {str(source.get("scan_state") or "failed") for source in sources}
    full_scope = bool(scopes) and all(item["valid"] for item in scopes) and completed >= requested and failed == 0 and states == {"complete"}
    strategy_publication = []
    for source, source_scope in zip(sources, scopes, strict=True):
        source_requested = source_scope["expected"]
        source_completed = source_scope["completed"]
        source_failed = source_scope["failed"]
        source_state = str(source.get("scan_state") or "failed")
        eligible = scan_mode == "production" and source_scope["valid"] and source_completed >= source_requested and source_failed == 0 and source_state == "complete"
        strategy_publication.append({
            "market": source.get("market"), "strategy": source.get("strategy"),
            "eligible": eligible, "state": source_state, "universe_mode": source_scope["mode"],
            "universe_expected": source_requested, "universe_scanned": source_scope["scanned"],
            "blocking_reason": None if eligible else (
                "研究資料尚未完成全市場核對；本策略僅供觀察，不列入正式發布"
            ),
        })
    report.update({
        "scan_mode": scan_mode,
        "scan_scope": "full" if full_scope else "bounded",
        "universe_expected": requested,
        "universe_scanned": completed + failed,
        "universe_completed": completed,
        # A production-shaped report is not automatically publishable. A
        # partial scan is retained as an explicit diagnostic artifact while
        # the workflow keeps the last successful public research snapshot.
        "publish_eligible": scan_mode == "production" and full_scope,
        "production_eligible": scan_mode == "production" and full_scope,
        "publication_state": "production" if scan_mode == "production" and full_scope else "diagnostic",
        "strategy_publication": strategy_publication,
        "blocking_reason": None if scan_mode == "production" and full_scope else (
            "smoke/debug scan is isolated from production publishing"
            if scan_mode != "production"
            else "研究掃描 universe 缺少 full 範圍或仍有資料缺口；拒絕正式發布"
        ),
    })
    return report


def main() -> None:
    run_started_at = datetime.now(UTC)
    parser = argparse.ArgumentParser(description="台美研究摘要")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output", default="site/data/research-report.json")
    parser.add_argument(
        "--scan-mode", choices=sorted(SCAN_MODES), default="production",
        help="production is publishable; smoke/debug are isolated validation runs",
    )
    parser.add_argument(
        "--backtest-release",
        type=Path,
        help="optional walk-forward JSON; only its validated backtest_release_contract is copied",
    )
    parser.add_argument("--scan-failures", type=Path)
    parser.add_argument("--run-id", help="optional external workflow run identifier")
    parser.add_argument("--source-commit-sha", help="source commit used for the scan")
    args = parser.parse_args()
    merge_taiwan_scan_fragments(Path(args.data_dir))
    report = build_research_report(default_sources(Path(args.data_dir)))
    apply_scan_failures(report, load_scan_failures(args.scan_failures) if args.scan_failures else [])
    attach_instrument_lineage(report, extend_from_candidates=True)
    attach_scan_contract(report, args.scan_mode)
    attach_backtest_contract(report, args.backtest_release)
    finished_at = datetime.now(UTC)
    attach_research_run(
        report,
        scan_mode=args.scan_mode,
        scan_scope=report["scan_scope"],
        started_at=run_started_at,
        finished_at=finished_at,
        run_id=args.run_id,
        source_commit_sha=args.source_commit_sha,
    )
    report["generated_at"] = finished_at.astimezone(ZoneInfo("Asia/Taipei")).isoformat()
    report["health"] = assess_research_health(report)
    # Bind research candidates to this exact point-in-time artifact.  The
    # release manifest later uses the ID to prevent mixing old research with
    # a newer market snapshot.
    report["snapshot_id"] = content_snapshot_id(report, "research")
    report["snapshot_published_at"] = datetime.now(ZoneInfo("Asia/Taipei")).isoformat()
    write_report(report, Path(args.output))
    print(f"{report['status']}：{report['summary']['total_candidates']} 筆候選；輸出 {args.output}")


if __name__ == "__main__":
    main()
