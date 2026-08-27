"""Process one asynchronous report job on a GitHub Actions runner.

The job is intentionally idempotent: a completed job is never overwritten by
a retry, and a failed job can only be replaced by an explicit new job ID.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable
from typing import Any

from prstk_app.db.repository import RepositoryError, SupabaseRepository

logger = logging.getLogger("prstk.report_worker")


def build_market_report(*, market: str, intro: str = "", outro: str = "") -> str:
    """Run the existing canonical engine and return a bounded report preview."""
    from src.market_data import build_market_snapshot

    snapshot = build_market_snapshot()
    indices = snapshot.get("indices") if isinstance(snapshot, dict) else []
    if not isinstance(indices, list):
        indices = []
    wanted = "taiwan" if market == "tw" else "us"
    selected = [
        {
            "name": row.get("name"),
            "value": row.get("value"),
            "change_percent": row.get("change_percent"),
            "quote_time": row.get("quote_time") or row.get("as_of"),
            "freshness": row.get("freshness"),
        }
        for row in indices
        if isinstance(row, dict) and (str(row.get("market") or "").casefold() in {wanted, market} or not row.get("market"))
    ][:8]
    report = {
        "market": market,
        "generated_at": snapshot.get("generated_at") if isinstance(snapshot, dict) else None,
        "intro": intro,
        "outro": outro,
        "indices": selected,
        "briefing": snapshot.get("briefing") if isinstance(snapshot, dict) else None,
        "disclaimer": "僅供公開資訊整理與教育性觀察，不構成投資建議。",
    }
    return json.dumps(report, ensure_ascii=False, separators=(",", ":"))


def process_report_job(
    job_id: str,
    *,
    repository: Any,
    builder: Callable[..., str] = build_market_report,
) -> dict[str, Any]:
    """Run a job and persist a terminal state, including sanitized failures."""
    job = repository.get_job(job_id)
    if not job:
        raise RepositoryError("report job was not found")
    if job.get("status") == "completed":
        report = repository.get_report(job_id)
        return {"job_id": job_id, "status": "completed", "report": report}
    if job.get("status") == "failed":
        return {"job_id": job_id, "status": "failed", "error": job.get("error")}
    repository.mark_job_running(job_id)
    market = str(job.get("market") or "")
    try:
        content = builder(market=market, intro=str(job.get("intro") or ""), outro=str(job.get("outro") or ""))
        repository.save_report(job_id=job_id, market=market, content=content)
        repository.mark_job_completed(job_id)
        repository.update_system_status(component="report_engine", status="ok")
        return {"job_id": job_id, "status": "completed", "report": content}
    except Exception as exc:  # noqa: BLE001 - worker must close the job on every error
        safe_error = f"{type(exc).__name__}: {str(exc)[:420]}"
        repository.mark_job_failed(job_id, safe_error)
        repository.update_system_status(component="report_engine", status="error", error=safe_error)
        logger.error("report job failed job_id=%s market=%s error=%s", job_id, market, safe_error)
        return {"job_id": job_id, "status": "failed", "error": safe_error}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Process one PRStK asynchronous report job")
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        result = process_report_job(args.job_id, repository=SupabaseRepository())
    except RepositoryError as exc:
        logger.error("report worker unavailable: %s", exc)
        return 2
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result.get("status") == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
