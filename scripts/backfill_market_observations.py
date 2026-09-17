"""Backfill normalized Taiwan official history into the private market store."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

from src.market_backup import from_environment
from src.taiwan_macro_sources import fetch_official_taiwan_components


def main() -> int:
    store = from_environment()
    if store is None:
        print(json.dumps({"status": "blocked", "reason": "market_backup_not_configured"}))
        return 2
    components = fetch_official_taiwan_components(months=18)
    mapping = {"^TWII": "TAIEX", "^TWOII": "TPEx", "TWD=X": "USD/TWD"}
    counts: dict[str, int] = {}
    errors: list[str] = []
    for symbol, ticker in mapping.items():
        frame = components.get(symbol)
        if frame is None or len(frame) < 120 or "Close" not in frame.columns:
            errors.append(f"{symbol}:insufficient_official_history")
            continue
        rows = 0
        for observed, values in frame.iterrows():
            close_value = values.get("Close")
            if close_value is None:
                continue
            close = float(close_value)
            prior_value = frame.loc[:observed].iloc[-2]["Close"] if len(frame.loc[:observed]) >= 2 else None
            prior = None
            if prior_value is not None:
                try:
                    parsed_prior = float(str(prior_value))
                except (TypeError, ValueError):
                    parsed_prior = 0.0
                if parsed_prior != 0:
                    prior = parsed_prior
            change = close - prior if prior is not None else None
            percent = change / prior * 100 if change is not None and prior else None
            quote: dict[str, object] = {
                "instrument_id": f"market:{ticker.casefold()}",
                "ticker": ticker,
                "market": "taiwan",
                "price": close,
                "previous_close": prior,
                "change": change,
                "change_percent": percent,
                "quote_date": observed.date().isoformat(),
                "quote_source": "TWSE/TPEx official historical backfill",
                "source_label": "TWSE/TPEx",
                "source_tier": "official",
                "quote_basis": "官方歷史收盤",
                "currency": "TWD",
                "freshness": "recent_close",
                "source_url": "https://openapi.twse.com.tw/",
            }
            if symbol == "^TWII" and values.get("Volume") is not None:
                quote["volume"] = float(values["Volume"])
            try:
                store.upsert_quote(quote)
            except Exception as exc:
                errors.append(f"{ticker}:{type(exc).__name__}")
                continue
            rows += 1
        counts[ticker] = rows
    result = {
        "status": "complete" if not errors else "partial",
        "counts": counts,
        "errors": errors,
        "checked_at": datetime.now(UTC).isoformat(),
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
