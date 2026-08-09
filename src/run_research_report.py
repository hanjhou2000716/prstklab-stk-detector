"""Build a unified public-scan report for the dashboard or an Artifact."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.release_manifest import content_snapshot_id
from src.research_health import assess_research_health
from src.research_report import build_research_report

SCAN_MODES = {"production", "smoke", "debug"}


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


def attach_scan_contract(report: dict, scan_mode: str) -> dict:
    """Attach publication eligibility without changing candidate semantics."""
    sources = report.get("sources", [])
    requested = sum(int(source.get("requested") or 0) for source in sources)
    completed = sum(
        int(source.get("complete_records") or source.get("data_complete") or 0)
        for source in sources
    )
    failed = sum(int(source.get("failed_records") or source.get("failed") or 0) for source in sources)
    states = {str(source.get("scan_state") or "failed") for source in sources}
    full_scope = requested > 0 and completed >= requested and failed == 0 and states == {"complete"}
    strategy_publication = []
    for source in sources:
        source_requested = int(source.get("requested") or 0)
        source_completed = int(source.get("complete_records") or source.get("data_complete") or 0)
        source_failed = int(source.get("failed_records") or source.get("failed") or 0)
        source_state = str(source.get("scan_state") or "failed")
        eligible = scan_mode == "production" and source_requested > 0 and source_completed >= source_requested and source_failed == 0 and source_state == "complete"
        strategy_publication.append({
            "market": source.get("market"), "strategy": source.get("strategy"),
            "eligible": eligible, "state": source_state,
            "blocking_reason": None if eligible else (
                "研究資料尚未完成全市場核對；本策略僅供觀察，不列入正式發布"
            ),
        })
    report.update({
        "scan_mode": scan_mode,
        "scan_scope": "full" if scan_mode == "production" else "bounded",
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
            else "一個以上研究來源尚未完成或發生失敗；等待下一輪完整掃描"
        ),
    })
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="台美研究摘要")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output", default="site/data/research-report.json")
    parser.add_argument(
        "--scan-mode", choices=sorted(SCAN_MODES), default="production",
        help="production is publishable; smoke/debug are isolated validation runs",
    )
    args = parser.parse_args()
    report = build_research_report(default_sources(Path(args.data_dir)))
    attach_scan_contract(report, args.scan_mode)
    report["generated_at"] = datetime.now(ZoneInfo("Asia/Taipei")).isoformat()
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
