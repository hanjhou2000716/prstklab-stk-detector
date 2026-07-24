"""Build a unified public-scan report for the dashboard or an Artifact."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.research_report import build_research_report
from src.research_health import assess_research_health


def default_sources(data_dir: Path) -> list[dict[str, str]]:
    return [
        {"path": str(data_dir / "taiwan-momentum-scan-0.csv"), "market": "taiwan", "strategy": "momentum"},
        {"path": str(data_dir / "us-momentum-scan.csv"), "market": "us", "strategy": "momentum"},
        {"path": str(data_dir / "taiwan-price-action-scan-0.csv"), "market": "taiwan", "strategy": "price_action"},
        {"path": str(data_dir / "us-price-action-scan.csv"), "market": "us", "strategy": "price_action"},
    ]


def write_report(report: dict, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="台美研究摘要")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output", default="site/data/research-report.json")
    args = parser.parse_args()
    report = build_research_report(default_sources(Path(args.data_dir)))
    report["generated_at"] = datetime.now(ZoneInfo("Asia/Taipei")).isoformat()
    report["health"] = assess_research_health(report)
    write_report(report, Path(args.output))
    print(f"{report['status']}：{report['summary']['total_candidates']} 筆候選；輸出 {args.output}")


if __name__ == "__main__":
    main()
