"""Phase 2 public sources: KOFIA, crypto MACD, FRED and EIA.

Every function is read-only and returns a status record instead of raising a
provider error into the dashboard.  API keys are read only from environment
variables and are never included in returned data.
"""

from __future__ import annotations

from datetime import UTC, datetime
import math
import os
import re
from typing import Any, Iterable

import requests


KOFIA_URL = "https://freesis.kofia.or.kr/stat/FreeSIS.do?parentDivId=MSIS10000000000000&serviceId=STATSCU0100000070"
FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
EIA_URL = "https://api.eia.gov/v2/petroleum/pri/spt/data/"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
DEFAULT_FRED_SERIES = {"DFF": "effective federal funds rate", "DGS10": "US 10-year Treasury yield", "CPIAUCSL": "US CPI"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _health(key: str, label: str, url: str, status: str, checked_at: str, **extra: Any) -> dict[str, Any]:
    return {"key": key, "label": label, "source_tier": "official", "source_url": url,
            "status": "healthy" if status == "healthy" else "partial",
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
                candidates.append((date_match.group(1).replace(".", "-"), numbers[-1]))
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


def fetch_fred_snapshot(series_ids: dict[str, str] | None = None, *, timeout: int = 20) -> dict[str, Any]:
    """Fetch selected FRED observations using ``FRED_API_KEY`` only."""
    checked_at = _now()
    key = os.getenv("FRED_API_KEY", "").strip()
    series = series_ids or DEFAULT_FRED_SERIES
    if not key:
        return {"status": "missing_api_key", "data": {}, "health": _health("fred", "FRED 官方總經資料", FRED_URL, "missing_api_key", checked_at, item_count=0, data_gap="FRED_API_KEY 未設定")}
    data: dict[str, Any] = {}
    errors: list[str] = []
    for series_id, label in series.items():
        try:
            response = requests.get(FRED_URL, params={"api_key": key, "file_type": "json", "series_id": series_id, "sort_order": "desc", "limit": 1}, timeout=timeout)
            response.raise_for_status()
            observations = response.json().get("observations", [])
            if not observations or observations[0].get("value") in {None, "."}:
                raise ValueError("no observation")
            data[series_id] = {"label": label, "date": observations[0].get("date"), "value": _to_float(observations[0].get("value"))}
        except Exception as exc:
            errors.append(f"{series_id}:{type(exc).__name__}")
    status = "healthy" if data and not errors else "partial" if data else "failed"
    return {"status": status, "data": data, "errors": errors, "fetched_at": checked_at,
            "health": _health("fred", "FRED 官方總經資料", FRED_URL, status, checked_at, item_count=len(data), data_gap=errors or None)}


def fetch_eia_snapshot(*, timeout: int = 20) -> dict[str, Any]:
    """Fetch the latest public EIA spot petroleum observation."""
    checked_at = _now()
    key = os.getenv("EIA_API_KEY", "").strip()
    if not key:
        return {"status": "missing_api_key", "data": {}, "health": _health("eia", "EIA 官方能源資料", EIA_URL, "missing_api_key", checked_at, item_count=0, data_gap="EIA_API_KEY 未設定")}
    try:
        response = requests.get(EIA_URL, params={"api_key": key, "frequency": "weekly", "data[0]": "value", "facets[seriesId][]": "RWTC", "sort[0][column]": "period", "sort[0][direction]": "desc", "length": 1}, timeout=timeout)
        response.raise_for_status()
        rows = response.json().get("response", {}).get("data", [])
        if not rows:
            raise ValueError("no EIA observation")
        row = rows[0]
        data = {"series": "RWTC", "period": row.get("period"), "value": _to_float(row.get("value")), "unit": row.get("unit") or "USD per barrel"}
        return {"status": "ok", "data": data, "fetched_at": checked_at, "health": _health("eia", "EIA 官方能源資料", EIA_URL, "healthy", checked_at, item_count=1, data_gap=None)}
    except Exception as exc:
        return {"status": "failed", "data": {}, "data_gap": type(exc).__name__, "fetched_at": checked_at,
                "health": _health("eia", "EIA 官方能源資料", EIA_URL, "failed", checked_at, item_count=0, data_gap=type(exc).__name__)}


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
    macd = [left - right for left, right in zip(fast, slow)]
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
            except Exception as exc:
                errors.append(f"{asset}:{interval}:{type(exc).__name__}")
    status = "healthy" if not errors else "partial" if results else "failed"
    return {"status": status, "data": results, "errors": errors, "fetched_at": checked_at,
            "health": _health("crypto_macd", "BTC／ETH MACD", BINANCE_KLINES_URL, status, checked_at, item_count=4, data_gap=errors or None)}


def build_phase_two_snapshot() -> dict[str, Any]:
    """Collect Phase 2 sources independently and expose one health list."""
    from src.crypto_spot_sources import fetch_crypto_spot_snapshot

    kofia = fetch_kofia_credit_margin()
    crypto = fetch_crypto_macd()
    crypto_spot = fetch_crypto_spot_snapshot()
    fred = fetch_fred_snapshot()
    eia = fetch_eia_snapshot()
    return {
        "kofia": kofia,
        "crypto_macd": crypto,
        "crypto_spot": crypto_spot,
        "fred": fred,
        "eia": eia,
        "sources": [item["health"] for item in (kofia, crypto, crypto_spot, fred, eia) if item.get("health")],
    }
