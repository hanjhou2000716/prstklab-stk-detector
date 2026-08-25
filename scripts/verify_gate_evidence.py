"""Validate the Gate-Driven v3 requirement/evidence registry."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.gate_evidence import DEFAULT_PATH, load_registry, validate_registry  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--strict", action="store_true", help="fail when any debt or regression remains OPEN")
    args = parser.parse_args()
    try:
        result = validate_registry(load_registry(args.registry), strict=args.strict)
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"status": "fail", "errors": [f"registry load failed: {type(exc).__name__}"]}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
