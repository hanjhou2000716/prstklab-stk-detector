"""Run one research worker with bounded retries and an auditable failure record."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path


def _now() -> str:
    return datetime.now(UTC).isoformat()


def run_worker(
    command: Sequence[str],
    *,
    market: str,
    strategy: str,
    ledger: Path,
    retries: int = 2,
    timeout_seconds: int | None = None,
    retry_delay_seconds: float = 2.0,
) -> int:
    """Run a worker and append one record only when all attempts fail.

    The wrapper intentionally returns success after recording a failure. This
    keeps the eight-worker workflow moving so the unified report can publish a
    fail-closed diagnostic state instead of silently aborting at the first
    network timeout. No candidate data is fabricated by this helper.
    """
    attempts = max(1, int(retries) + 1)
    errors: list[str] = []
    started_at = _now()
    for attempt in range(1, attempts + 1):
        try:
            completed = subprocess.run(
                list(command),
                check=False,
                capture_output=True,
                text=True,
                timeout=(max(1, int(timeout_seconds)) if timeout_seconds else None),
            )
        except subprocess.TimeoutExpired:
            errors.append(f"attempt {attempt}: timeout after {timeout_seconds}s")
            return_code = 124
        except OSError as exc:
            errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
            return_code = 127
        else:
            return_code = int(completed.returncode)
            if return_code == 0:
                return 0
            stderr = (completed.stderr or completed.stdout or "").strip().replace("\r", " ").replace("\n", " ")
            errors.append(f"attempt {attempt}: exit {return_code}" + (f": {stderr[-500:]}" if stderr else ""))
        if attempt < attempts:
            time.sleep(max(0.0, retry_delay_seconds) * attempt)

    ledger.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "market": market,
        "strategy": strategy,
        "exit_code": return_code,
        "attempts": attempts,
        "started_at": started_at,
        "finished_at": _now(),
        "error": "; ".join(errors)[-1200:],
        "state": "failed",
        "publish_eligible": False,
    }
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"::warning::research worker failed after {attempts} attempts: {market}/{strategy}", file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="bounded research worker runner")
    parser.add_argument("--market", required=True)
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument(
        "--timeout-seconds", type=int, default=0,
        help="optional per-attempt timeout; 0 defers to the workflow job timeout",
    )
    parser.add_argument("--retry-delay-seconds", type=float, default=2.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("a worker command is required after --")
    return run_worker(
        command,
        market=args.market,
        strategy=args.strategy,
        ledger=args.ledger,
        retries=args.retries,
        timeout_seconds=args.timeout_seconds,
        retry_delay_seconds=args.retry_delay_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
