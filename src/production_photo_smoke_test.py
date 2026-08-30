"""Deprecated compatibility entry point for the retired photo gate.

Production acceptance is text-only; this alias is retained only so historical
dispatch links fail closed into the release-gated text acceptance.
"""

from src.production_text_acceptance import main, run

__all__ = ["main", "run"]


if __name__ == "__main__":
    raise SystemExit(main())
