"""Taiwan Macro Fear & Greed Index from public daily market data."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd


SYMBOLS = ("^TWII", "^TWOII", "TWD=X")


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
) -> dict[str, Any]:
    """Calculate the five-component Taiwan Macro FGI from the supplied formula."""
    if downloader is None:
        import yfinance as yf

        downloader = lambda symbol: yf.download(
            symbol, period="2y", interval="1d", auto_adjust=False,
            progress=False, threads=False,
        )

    raw = {symbol: downloader(symbol) for symbol in SYMBOLS}
    twii, twoii, twd = raw["^TWII"], raw["^TWOII"], raw["TWD=X"]
    if any(frame.empty for frame in raw.values()):
        raise ValueError("台股 Macro FGI 必要公開資料暫時無法取得")

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
        raise ValueError("台股 Macro FGI 歷史資料不足 120 個交易日")

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
    return {
        "score": round(score, 1),
        "label": fgi_label(score),
        "source_label": "TAIEX Macro FGI",
        "date": frame.index[-1].date().isoformat(),
        "index_level": round(float(frame["TWII_Close"].iloc[-1]), 2),
        "sub_scores": {key: round(value, 1) for key, value in sub_scores.items()},
        "method": "加權、櫃買、成交量、歷史波動率、美元兌台幣匯率的 120 日百分位模型",
    }
