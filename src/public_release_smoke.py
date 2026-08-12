"""Public Pages release smoke check with safe, non-delivery output."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.release_gate import verify_release_for_delivery


def run_public_release_smoke(
    *, manifest: Path | str = Path("site/data/release-manifest.json"),
    public_url: str,
    expected_snapshot_id: str | None = None,
    attempts: int = 3,
    delay: float = 2.0,
) -> dict[str, Any]:
    """Verify public release identity and hashes without sending notifications."""
    result = verify_release_for_delivery(
        manifest_path=manifest,
        expected_snapshot_id=expected_snapshot_id,
        public_url=public_url,
        public_attempts=attempts,
        public_delay=delay,
    )
    return {
        "ok": result.allowed,
        "release_id": result.release_id,
        "snapshot_id": result.snapshot_id,
        "public_url": public_url,
        "errors": list(result.errors),
        "delivery_performed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("site/data/release-manifest.json"))
    parser.add_argument("--public-url", required=True)
    parser.add_argument("--expected-snapshot-id", default=None)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--delay", type=float, default=2.0)
    args = parser.parse_args()
    report = run_public_release_smoke(
        manifest=args.manifest,
        public_url=args.public_url,
        expected_snapshot_id=args.expected_snapshot_id,
        attempts=args.attempts,
        delay=args.delay,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
