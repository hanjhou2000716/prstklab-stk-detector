"""Central, public-only rules for the finance intelligence monitor."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


POLICY_PATH = Path(__file__).resolve().parents[1] / "config" / "finance_intel_policy.json"


@lru_cache(maxsize=1)
def load_finance_intel_policy() -> dict[str, Any]:
    """Load the versioned policy without ever reading credentials or accounts."""
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def polling_rule(name: str) -> Any:
    return load_finance_intel_policy()["polling"][name]


def threshold_rule(name: str) -> Any:
    return load_finance_intel_policy()["thresholds"][name]
