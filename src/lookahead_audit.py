"""Audit individual walk-forward rows for look-ahead and survivorship leakage."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence


def audit_signal_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    reasons: list[str] = []
    checked = 0
    for row in rows:
        checked += 1
        try:
            signal = date.fromisoformat(str(row["signal_date"])[:10])
            entry = date.fromisoformat(str(row["entry_date"])[:10])
        except (KeyError, TypeError, ValueError):
            reasons.append("row missing valid signal_date or entry_date")
            continue
        if entry <= signal:
            reasons.append(f"{row.get('ticker', 'unknown')}: entry is not after signal close")
        for field in ("fundamental_published_at", "membership_as_of", "price_as_of"):
            if field in row and row[field] and str(row[field])[:10] > signal.isoformat():
                reasons.append(f"{row.get('ticker', 'unknown')}: {field} is after signal date")
        if row.get("delisted") is True and not row.get("delisting_date"):
            reasons.append(f"{row.get('ticker', 'unknown')}: delisted record lacks date")
    return {"status": "pass" if not reasons else "failed", "rows_checked": checked,
            "reasons": reasons, "lookahead_free": not reasons}
