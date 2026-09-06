"""Phase 2 public sources: KOFIA and crypto MACD.

Every function is read-only and returns a status record instead of raising a
provider error into the dashboard.  API keys are read only from environment
variables and are never included in returned data.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import requests

from src.provider_health import classify_provider_error, error_token

KOFIA_URL = "https://freesis.kofia.or.kr/stat/FreeSIS.do?parentDivId=MSIS10000000000000&serviceId=STATSCU0100000070"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
BINANCE_US_KLINES_URL = "https://api.binance.us/api/v3/klines"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _health(key: str, label: str, url: str, status: str, checked_at: str, **extra: Any) -> dict[str, Any]:
    state = {
        "healthy": "healthy",
        "missing_api_key": "configuration_required",
        "data_gap": "optional_degraded" if key == "kofia_margin" else "critical_gap",
        "partial": "optional_degraded" if key == "kofia_margin" else "critical_gap",
        "failed": "optional_degraded" if key == "kofia_margin" else "failed",
    }.get(status, "critical_gap")
    role = "optional" if key in {"kofia_margin", "fred", "eia", "crypto_macd"} else "required_for_core"
    return {"key": key, "label": label, "source_tier": "official", "source_url": url,
            "status": "healthy" if status == "healthy" else "partial", "state": state, "role": role,
            "provider_status": status, "checked_at": checked_at, **extra}


def _percentile(values: Iterable[float], latest: float) -> float | None:
    numbers = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not numbers:
        return None
    return round(sum(value <= latest for value in numbers) / len(numbers) * 100, 1)


def _to_float(value: Any) -> float | None:
    try:
        number = float(str(value).replace(",", "").replace("%", "").strip())
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def fetch_kofia_credit_margin(*, timeout: int = 20) -> dict[str, Any]:
    """Read the public KOFIA FreeSIS credit-balance table when available.

    FreeSIS has changed its HTML/JSON shape over time, so parsing is defensive:
    a successful HTTP response with no unambiguous balance is reported as a
    data gap, never as a guessed value.
    """
    checked_at = _now()
    try:
        response = requests.get(KOFIA_URL, headers={"User-Agent": "PRStK Lab public research"}, timeout=timeout)
        response.raise_for_status()
        text = response.text
        candidates: list[tuple[str, float]] = []
        date_pattern = re.compile(r"(20\d{2}[./-]\d{1,2}[./-]\d{1,2})")
        number_pattern = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")
        for row in re.split(r"<tr|\n", text, flags=re.I):
            date_match = date_pattern.search(row)
            if not date_match or not any(token in row for token in ("신용", "융자", "잔고", "credit", "margin")):
                continue
            numbers = [_to_float(value) for value in number_pattern.findall(row)]
            numbers = [value for value in numbers if value is not None]
            if numbers:
                value = numbers[-1]
                assert value is not None
                candidates.append((date_match.group(1).replace(".", "-"), float(value)))
        if not candidates:
            return {"status": "data_gap", "data_gap": "KOFIA response has no unambiguous balance", "health": _health("kofia_margin", "KOFIA 韓國全市場信用融資", KOFIA_URL, "partial", checked_at)}
        candidates.sort(key=lambda item: item[0])
        latest_date, latest_value = candidates[-1]
        percentile = _percentile((value for _, value in candidates[-20:]), latest_value)
        level = "高位" if percentile is not None and percentile >= 75 else "低位" if percentile is not None and percentile <= 25 else "中位"
        return {"status": "ok", "source_label": "KOFIA 韓國全市場信用融資", "source_url": KOFIA_URL,
                "date": latest_date, "balance": latest_value, "unit": "兆韓元", "sample_days": len(candidates),
                "percentile": percentile, "level": level, "fetched_at": checked_at,
                "health": _health("kofia_margin", "KOFIA 韓國全市場信用融資", KOFIA_URL, "healthy", checked_at, item_count=len(candidates), data_gap=None)}
    except Exception as exc:
        return {"status": "failed", "data_gap": type(exc).__name__, "fetched_at": checked_at,
                "health": _health("kofia_margin", "KOFIA 韓國全市場信用融資", KOFIA_URL, "failed", checked_at, item_count=0, data_gap=type(exc).__name__)}


def _ema(values: list[float], period: int) -> list[float]:
    alpha = 2 / (period + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append(alpha * value + (1 - alpha) * result[-1])
    return result


def _macd_state(closes: list[float]) -> dict[str, Any]:
    if len(closes) < 35:
        raise ValueError("MACD 歷史樣本不足")
    fast, slow = _ema(closes, 12), _ema(closes, 26)
    macd = [left - right for left, right in zip(fast, slow, strict=True)]
    signal = _ema(macd, 9)
    previous_diff, current_diff = macd[-2] - signal[-2], macd[-1] - signal[-1]
    bearish = previous_diff >= 0 and current_diff < 0
    near = current_diff < 0 and abs(current_diff) <= max(abs(signal[-1]) * 0.05, 0.01)
    return {"macd": round(macd[-1], 6), "signal": round(signal[-1], 6), "bearish_cross": bearish, "near_bearish_cross": near,
            "label": "死叉" if bearish else "警戒：接近死叉" if near else "未見死叉"}


def fetch_crypto_macd(*, timeout: int = 20) -> dict[str, Any]:
    """Read Binance public candles and classify weekly/monthly BTC/ETH MACD."""
    checked_at = _now()
    results: dict[str, Any] = {}
    errors: list[str] = []
    error_details: list[dict[str, Any]] = []
    fallback_used = False
    success_count = 0
    for asset in ("BTCUSDT", "ETHUSDT"):
        results[asset] = {}
        for interval in ("1w", "1M"):
            try:
                response = requests.get(BINANCE_KLINES_URL, params={"symbol": asset, "interval": interval, "limit": 80}, timeout=timeout)
                response.raise_for_status()
                rows = response.json()
                state = _macd_state([float(row[4]) for row in rows])
                state.update({"interval": interval, "source_url": BINANCE_KLINES_URL, "fetched_at": checked_at})
                results[asset][interval] = state
                success_count += 1
            except Exception as exc:
                try:
                    response = requests.get(BINANCE_US_KLINES_URL, params={"symbol": asset, "interval": interval, "limit": 80}, timeout=timeout)
                    response.raise_for_status()
                    rows = response.json()
                    state = _macd_state([float(row[4]) for row in rows])
                    state.update({"interval": interval, "source_url": BINANCE_US_KLINES_URL, "fetched_at": checked_at, "fallback_used": True})
                    results[asset][interval] = state
                    fallback_used = True
                    success_count += 1
                except Exception as fallback_exc:
                    errors.extend([error_token("binance", f"{asset}:{interval}", exc), error_token("binance_us", f"{asset}:{interval}", fallback_exc)])
                    error_details.extend([
                        {"provider": "binance", "item": f"{asset}:{interval}", **classify_provider_error(exc)},
                        {"provider": "binance_us", "item": f"{asset}:{interval}", **classify_provider_error(fallback_exc)},
                    ])
    status = "healthy" if success_count == 4 else "partial" if success_count else "failed"
    return {"status": status, "data": results, "errors": errors, "error_details": error_details, "fallback_used": fallback_used, "fetched_at": checked_at,
            "health": _health("crypto_macd", "BTC／ETH MACD", BINANCE_KLINES_URL, status, checked_at, item_count=4, data_gap=errors or None)}


def build_phase_two_snapshot() -> dict[str, Any]:
    """Collect Phase 2 sources independently and expose one health list."""
    from src.crypto_spot_sources import fetch_crypto_spot_snapshot
    from src.public_market_secondary import fetch_public_market_secondary

    kofia = fetch_kofia_credit_margin()
    crypto = fetch_crypto_macd()
    crypto_spot = fetch_crypto_spot_snapshot()
    public_market_secondary = fetch_public_market_secondary()
    return {
        "kofia": kofia,
        "crypto_macd": crypto,
        "crypto_spot": crypto_spot,
        "public_market_secondary": public_market_secondary,
        "sources": [item["health"] for item in (kofia, crypto, crypto_spot, public_market_secondary) if item.get("health")],
    }
