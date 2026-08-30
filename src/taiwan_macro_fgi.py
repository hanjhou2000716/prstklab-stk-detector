"""Taiwan Macro Fear & Greed Index from public daily market data."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

SYMBOLS = ("^TWII", "^TWOII", "TWD=X")
_LAST_GOOD: dict[str, Any] | None = None


class FGIUnavailableError(ValueError):
    """Raised when the fixed five-factor model cannot be calculated safely."""

    def __init__(self, message: str, *, component_health: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.component_health = component_health or {}


def percentile_rank(series: pd.Series, window: int = 120) -> float:
    """Return the latest value's rank in the trailing window on a 0-100 scale."""
    if len(series) < window:
        return 50.0
    history = series.iloc[-window:]
    return float((history <= history.iloc[-1]).sum() / window * 100)


def fgi_label(score: float) -> str:
    """Classify the supplied model bands without making an action recommendation."""
    if score >= 75:
        return "極度貪婪"
    if score >= 56:
        return "貪婪"
    if score >= 45:
        return "中立"
    if score >= 26:
        return "恐慌"
    return "極度恐慌"


def _column(frame: pd.DataFrame, name: str) -> pd.Series:
    result = frame[name]
    if getattr(result, "ndim", 1) > 1:
        result = result.iloc[:, 0]
    return result.dropna()


def calculate_taiwan_macro_fgi(
    downloader: Callable[[str], pd.DataFrame] | None = None,
    *,
    cache_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Calculate the five-component Taiwan Macro FGI from the supplied formula."""
    if downloader is None:
        import yfinance as yf

        def downloader(symbol: str) -> Any:
            return yf.download(
                symbol, period="2y", interval="1d", auto_adjust=False,
                progress=False, threads=False,
            )

    component_health: dict[str, Any] = {}
    raw: dict[str, pd.DataFrame] = {}
    for symbol in SYMBOLS:
        try:
            frame = downloader(symbol)
            if not isinstance(frame, pd.DataFrame) or frame.empty:
                raise ValueError("empty frame")
            raw[symbol] = frame
            component_health[symbol] = {"status": "ok", "source": "primary"}
        except Exception as exc:  # provider-specific failure is retained, never silently treated as no risk
            component_health[symbol] = {"status": "failed", "error_type": type(exc).__name__}

    global _LAST_GOOD
    effective_cache = Path(cache_path or os.environ.get("PRSTK_FGI_CACHE_PATH", "")) if (cache_path or os.environ.get("PRSTK_FGI_CACHE_PATH")) else None
    # An explicitly supplied cache path is authoritative; do not accidentally
    # reuse another test/process's in-memory value when that path is absent.
    cached: dict[str, Any] | None = None if cache_path else _LAST_GOOD
    if cached is None and effective_cache and effective_cache.exists():
        try:
            candidate = json.loads(effective_cache.read_text(encoding="utf-8"))
            if isinstance(candidate, dict) and candidate.get("score") is not None and candidate.get("date"):
                cached = candidate
        except (OSError, ValueError, TypeError):
            cached = None
    if len(raw) != len(SYMBOLS):
        if cached is not None:
            result = dict(cached)
            result["component_health"] = component_health
            result["stale_components"] = [symbol for symbol in SYMBOLS if component_health[symbol]["status"] != "ok"]
            result["data_quality"] = "stale_last_good"
            result["calculation_state"] = "stale_last_good"
            result["cache_as_of"] = cached.get("date")
            return result
        raise FGIUnavailableError("台股 Macro FGI 必要公開資料暫時無法取得", component_health=component_health)
    required_columns = {"^TWII": ("Close", "Volume"), "^TWOII": ("Close",), "TWD=X": ("Close",)}
    malformed = [
        symbol for symbol, columns in required_columns.items()
        if any(column not in raw[symbol] for column in columns)
    ]
    if malformed:
        for symbol in malformed:
            component_health[symbol] = {"status": "malformed", "error_type": "missing_column"}
        if cached is not None:
            result = dict(cached)
            result["component_health"] = component_health
            result["stale_components"] = malformed
            result["data_quality"] = "stale_last_good"
            result["calculation_state"] = "stale_last_good"
            result["cache_as_of"] = cached.get("date")
            return result
        raise FGIUnavailableError("台股 Macro FGI 公開資料欄位不足", component_health=component_health)
    twii, twoii, twd = raw["^TWII"], raw["^TWOII"], raw["TWD=X"]

    frame = pd.DataFrame(index=_column(twii, "Close").index)
    frame["TWII_Close"] = _column(twii, "Close")
    frame["TWII_Vol"] = _column(twii, "Volume")
    frame["TWOII_Close"] = _column(twoii, "Close")
    frame["USD_TWD"] = _column(twd, "Close")
    frame = frame.ffill().dropna()

    frame["MA125"] = frame["TWII_Close"].rolling(125).mean()
    frame["Bias125"] = (frame["TWII_Close"] - frame["MA125"]) / frame["MA125"]
    frame["Volatility"] = frame["TWII_Close"].pct_change().rolling(20).std()
    frame["OTC_Relative_Strength"] = frame["TWOII_Close"] / frame["TWII_Close"]
    frame["TWD_ROC"] = frame["USD_TWD"].pct_change(20)
    frame["Volume_Ratio"] = frame["TWII_Vol"] / frame["TWII_Vol"].rolling(20).mean()
    frame = frame.dropna()
    if len(frame) < 120:
        if cached is not None:
            result = dict(cached)
            result["component_health"] = {symbol: {"status": "insufficient_history"} for symbol in SYMBOLS}
            result["stale_components"] = list(SYMBOLS)
            result["data_quality"] = "stale_last_good"
            result["calculation_state"] = "stale_last_good"
            result["cache_as_of"] = cached.get("date")
            return result
        raise FGIUnavailableError("台股 Macro FGI 歷史資料不足 120 個交易日", component_health=component_health)

    sub_scores = {
        "動能": percentile_rank(frame["Bias125"]),
        "波動": 100 - percentile_rank(frame["Volatility"]),
        "內資投機": percentile_rank(frame["OTC_Relative_Strength"]),
        "外資流向": 100 - percentile_rank(frame["TWD_ROC"]),
        "量能": percentile_rank(frame["Volume_Ratio"]),
    }
    score = (
        sub_scores["動能"] * 0.30
        + sub_scores["波動"] * 0.20
        + sub_scores["內資投機"] * 0.20
        + sub_scores["外資流向"] * 0.15
        + sub_scores["量能"] * 0.15
    )
    result = {
        "score": round(score, 1),
        "label": fgi_label(score),
        "source_label": "TAIEX Macro FGI",
        "date": frame.index[-1].date().isoformat(),
        "index_level": round(float(frame["TWII_Close"].iloc[-1]), 2),
        "sub_scores": {key: round(value, 1) for key, value in sub_scores.items()},
        "method": "加權、櫃買、成交量、歷史波動率、美元兌台幣匯率的 120 日百分位模型",
        "component_health": component_health,
        "stale_components": [],
        "data_quality": "primary",
        "calculation_state": "fresh",
        "calculated_at": datetime.now(UTC).isoformat(),
    }
    _LAST_GOOD = result
    if effective_cache:
        try:
            effective_cache.parent.mkdir(parents=True, exist_ok=True)
            effective_cache.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        except OSError:
            # Cache is an optimisation; a read-only filesystem must not turn a valid calculation into a failure.
            pass
    return result
