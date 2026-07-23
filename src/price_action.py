"""Research-only Price Action scanner using public OHLCV data.

The scanner describes market structure and reference risk boundaries.  It does
not connect to a broker, create orders, or provide a trading recommendation.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


REQUIRED_COLUMNS = {"Open", "High", "Low", "Close", "Volume"}
FUNNEL_LABELS = {
    "Funnel_1": "撐壓互換回踩",
    "Funnel_2": "雙底右腳確認",
    "Funnel_3": "假跌破收復",
    "Funnel_4": "訂單塊回踩",
}


class PriceActionResearchScanner:
    """Apply four transparent daily-bar price-structure research filters."""

    def __init__(self, atr_window: int = 14, atr_multiplier: float = 1.0, swing_window: int = 5):
        if atr_window < 2 or atr_multiplier <= 0 or swing_window < 1:
            raise ValueError("ATR 與結構窗口參數必須為正確的正數。")
        self.atr_window = atr_window
        self.atr_multiplier = atr_multiplier
        self.swing_window = swing_window

    @staticmethod
    def _validate(df: pd.DataFrame) -> None:
        missing = REQUIRED_COLUMNS - set(df.columns)
        if missing:
            raise ValueError(f"OHLCV 資料缺少欄位：{', '.join(sorted(missing))}")

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate ATR, candles, and confirmed historical structure points."""
        self._validate(df)
        result = df.copy().sort_index()
        high_low = result["High"] - result["Low"]
        high_close = (result["High"] - result["Close"].shift()).abs()
        low_close = (result["Low"] - result["Close"].shift()).abs()
        result["ATR"] = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1).rolling(
            self.atr_window
        ).mean()
        result["Body_Max"] = result[["Open", "Close"]].max(axis=1)
        result["Body_Min"] = result[["Open", "Close"]].min(axis=1)
        result["Body_Size"] = result["Body_Max"] - result["Body_Min"]
        result["Upper_Shadow"] = result["High"] - result["Body_Max"]
        result["Lower_Shadow"] = result["Body_Min"] - result["Low"]
        result["Is_Bullish"] = result["Close"] > result["Open"]
        result["Is_Bearish"] = result["Close"] < result["Open"]
        result["Is_Reversal"] = result["Lower_Shadow"] > result["ATR"].fillna(np.inf) * 0.1
        window = self.swing_window * 2 + 1
        result["Local_High"] = result["High"].rolling(window, center=True).max()
        result["Local_Low"] = result["Low"].rolling(window, center=True).min()
        result["Is_Swing_High"] = result["High"].eq(result["Local_High"])
        result["Is_Swing_Low"] = result["Low"].eq(result["Local_Low"])
        return result

    def scan_daily(self, df: pd.DataFrame) -> dict[str, Any] | None:
        """Check the latest completed bar against the four Price Action funnels."""
        if len(df) < max(self.atr_window + 1, self.swing_window * 3):
            return None
        indicators = self.prepare_indicators(df)
        current = indicators.iloc[-1]
        if pd.isna(current["ATR"]):
            return None
        history = indicators.iloc[:-1]
        swing_highs = history[history["Is_Swing_High"]]
        swing_lows = history[history["Is_Swing_Low"]]
        matches = {key: False for key in FUNNEL_LABELS}
        support: float | None = None

        if not swing_highs.empty:
            high = swing_highs.iloc[-1]
            if current["Low"] <= high["High"] and current["Close"] >= high["Body_Max"] and current["Is_Reversal"]:
                matches["Funnel_1"] = True
                support = float(high["Body_Max"])

        if len(swing_lows) >= 2 and current["Is_Reversal"]:
            left_foot = swing_lows.iloc[-2]
            lower, upper = left_foot["Low"] * 0.97, left_foot["Low"] * 1.03
            if lower <= current["Low"] <= upper:
                matches["Funnel_2"] = True
                support = min(float(current["Low"]), float(left_foot["Low"]))

        if not swing_lows.empty:
            last_low = swing_lows.iloc[-1]
            previous = indicators.iloc[-2]
            broke_support = current["Low"] < last_low["Low"] or previous["Close"] < last_low["Low"]
            recovered = current["Close"] >= last_low["Body_Min"]
            if broke_support and recovered:
                matches["Funnel_3"] = True
                support = min(float(current["Low"]), float(last_low["Low"]))

        order_blocks = history[history["Is_Bearish"] & (history["Volume"] > history["Volume"].shift())]
        for index, order_block in order_blocks.iloc[::-1].iterrows():
            position = history.index.get_loc(index)
            if position + 1 >= len(history):
                continue
            next_bar = history.iloc[position + 1]
            is_impulse = next_bar["Is_Bullish"] and next_bar["Body_Size"] > history["Body_Size"].mean()
            revisits_zone = current["Low"] <= order_block["High"] and current["Close"] >= order_block["Low"]
            if is_impulse and revisits_zone and current["Is_Reversal"]:
                matches["Funnel_4"] = True
                support = float(order_block["Low"])
                break

        matched = [key for key, value in matches.items() if value]
        if not matched or support is None:
            return None
        reference_close = float(current["Close"])
        reference_stop = support - self.atr_multiplier * float(current["ATR"])
        reference_risk = reference_close - reference_stop
        if reference_risk <= 0:
            return None
        return {
            "matched_funnels": matched,
            "funnel_labels": [FUNNEL_LABELS[key] for key in matched],
            "reference_close": round(reference_close, 2),
            "support_edge": round(support, 2),
            "atr": round(float(current["ATR"]), 2),
            "reference_stop": round(reference_stop, 2),
            "reference_risk": round(reference_risk, 2),
            "volume": float(current["Volume"]),
            "turnover": round(float(current["Volume"] * current["Close"]), 2),
        }

    def screen(self, market_data: dict[str, pd.DataFrame], limit: int = 5) -> pd.DataFrame:
        """Return qualifying research candidates ranked by latest trading turnover."""
        candidates: list[dict[str, Any]] = []
        for ticker, daily in market_data.items():
            result = self.scan_daily(daily)
            if result:
                candidates.append({"ticker": ticker, **result})
        if not candidates:
            return pd.DataFrame()
        return pd.DataFrame(candidates).sort_values("turnover", ascending=False).head(limit).reset_index(drop=True)
