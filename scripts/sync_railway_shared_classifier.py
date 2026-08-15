"""Generate the classifier bundle used by Railway's root-only image.

The Railway service is currently built with ``railway-monitor`` as its root
directory, so it cannot import the repository-level ``src`` package.  The
bundle is generated from the canonical classifier rather than maintained as a
second implementation.  CI uses ``--check`` to fail on drift.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "event_classifier.py"
TARGET = ROOT / "railway-monitor" / "shared_event_classifier.py"
MARKER = '_KEYWORD_PATH = Path(__file__).resolve().parents[1] / "config" / "event_keywords.json"'
REPLACEMENT = (
    '_KEYWORD_PATH = Path(__file__).resolve().with_name("event_keywords.json")\n'
    'BUNDLE_SOURCE = "src/event_classifier.py"\n'
)


def render(source: str) -> str:
    if source.count(MARKER) != 1:
        raise ValueError("canonical classifier keyword path changed; update bundle generator")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    body = source.replace(MARKER, REPLACEMENT, 1)
    header = (
        "# GENERATED FILE: do not edit manually.\n"
        "# Run scripts/sync_railway_shared_classifier.py to refresh it.\n"
        f"# Canonical source SHA256: {digest}\n\n"
    )
    return header + body


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if the tracked bundle is stale")
    args = parser.parse_args()
    expected = render(SOURCE.read_text(encoding="utf-8"))
    actual = TARGET.read_text(encoding="utf-8") if TARGET.exists() else None
    if args.check:
        if actual != expected:
            print("railway shared classifier bundle is stale")
            return 1
        return 0
    TARGET.write_text(expected, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
