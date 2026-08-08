"""Research-only Price Action scanner using confirmed public OHLCV structure.

The scanner reports completed daily-bar structure. It does not connect to a
broker, create orders, or give a trading recommendation.
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
FUNNEL_SCORE = {
    "Funnel_1": 70,
    "Funnel_2": 70,
    "Funnel_3": 85,
    "Funnel_4": 80,
}


def structure_match_score(funnels: list[str]) -> int:
    """Return transparent structural alignment, never a return forecast."""
    matched = [funnel for funnel in funnels if funnel in FUNNEL_SCORE]
    if not matched:
        return 0
    primary = max(FUNNEL_SCORE[funnel] for funnel in matched)
    confirmation_bonus = min(5 * (len(set(matched)) - 1), 15)
    return min(primary + confirmation_bonus, 100)


class PriceActionResearchScanner:
    """Apply four confirmed daily-bar Price Action structure filters."""

    def __init__(self, atr_window: int = 14, atr_multiplier: float = 1.0, swing_window: int = 5):
        if atr_window < 2 or atr_multiplier <= 0 or swing_window < 1:
            raise ValueError("ATR 與結構窗口參數不合理")
        self.atr_window = atr_window
        self.atr_multiplier = atr_multiplier
        self.swing_window = swing_window

    @staticmethod
    def _validate(df: pd.DataFrame) -> None:
        missing = REQUIRED_COLUMNS - set(df.columns)
        if missing:
            raise ValueError(f"OHLCV 缺少欄位：{', '.join(sorted(missing))}")

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate ATR, candle anatomy and five-bar-confirmed pivots."""
        self._validate(df)
        result = df.copy().sort_index()
        high_low = result["High"] - result["Low"]
        high_close = (result["High"] - result["Close"].shift()).abs()
        low_close = (result["Low"] - result["Close"].shift()).abs()
        result["True_Range"] = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        result["ATR"] = result["True_Range"].rolling(self.atr_window).mean()
        result["Body_Max"] = result[["Open", "Close"]].max(axis=1)
        result["Body_Min"] = result[["Open", "Close"]].min(axis=1)
        result["Body_Size"] = result["Body_Max"] - result["Body_Min"]
        result["Upper_Shadow"] = result["High"] - result["Body_Max"]
        result["Lower_Shadow"] = result["Body_Min"] - result["Low"]
        result["Is_Bullish"] = result["Close"] > result["Open"]
        result["Is_Bearish"] = result["Close"] < result["Open"]
        result["Is_Reversal"] = result["Lower_Shadow"] > result["ATR"].fillna(np.inf) * 0.1
        result["Vol_MA20"] = result["Volume"].rolling(20).mean()
        result["Body_MA20"] = result["Body_Size"].rolling(20).mean()

        # A centered pivot is only admitted after five subsequent completed
        # bars exist. scan_daily below additionally removes the most recent
        # five rows, making the confirmation lag explicit rather than relying
        # on an unconfirmed turning point.
        window = self.swing_window * 2 + 1
        result["Local_High"] = result["High"].rolling(window, center=True).max()
        result["Local_Low"] = result["Low"].rolling(window, center=True).min()
        result["Is_Swing_High"] = result["High"].eq(result["Local_High"])
        result["Is_Swing_Low"] = result["Low"].eq(result["Local_Low"])
        return result

    def _confirmed_history(self, indicators: pd.DataFrame) -> pd.DataFrame:
        """Return structure that had at least ``swing_window`` bars to settle."""
        return indicators.iloc[: -self.swing_window]

    def _order_block_match(self, history: pd.DataFrame, current: pd.Series) -> float | None:
        """Find a first revisit of a high-volume bearish origin plus impulse bar."""
        candidates = history[
            history["Is_Bearish"]
            & (history["Volume"] >= history["Vol_MA20"] * 1.5)
        ]
        for index, order_block in candidates.iloc[::-1].iterrows():
            position = history.index.get_loc(index)
            if position + 1 >= len(history):
                continue
            impulse = history.iloc[position + 1]
            range_size = float(impulse["High"] - impulse["Low"])
            closes_high = range_size > 0 and float((impulse["Close"] - impulse["Low"]) / range_size) >= 0.70
            body_average = 0.0 if pd.isna(impulse["Body_MA20"]) else float(impulse["Body_MA20"])
            atr = 0.0 if pd.isna(impulse["ATR"]) else float(impulse["ATR"])
            is_impulse = bool(
                impulse["Is_Bullish"]
                and impulse["Body_Size"] >= max(body_average * 1.5, atr * 0.8)
                and closes_high
            )
            if not is_impulse:
                continue

            # An order block is only informative on its first public revisit.
            between = history.iloc[position + 2 :]
            already_revisited = not between.empty and bool(
                ((between["Low"] <= order_block["High"]) & (between["High"] >= order_block["Low"])).any()
            )
            revisits_zone = current["Low"] <= order_block["High"] and current["Close"] >= order_block["Low"]
            if not already_revisited and revisits_zone and current["Is_Reversal"]:
                return float(order_block["Low"])
        return None

    def scan_daily(self, df: pd.DataFrame) -> dict[str, Any] | None:
        """Check a completed bar against four confirmed, pullback-only structures."""
        if len(df) < max(self.atr_window + 1, self.swing_window * 3 + 1):
            return None
        indicators = self.prepare_indicators(df)
        current = indicators.iloc[-1]
        if pd.isna(current["ATR"]):
            return None

        # Never call a fresh five-day breakout a pullback structure. It must
        # close below the prior five-bar high and show a meaningful lower wick.
        prior_five_high = float(indicators["High"].iloc[-6:-1].max())
        if current["Close"] >= prior_five_high or not current["Is_Reversal"]:
            return None

        history = self._confirmed_history(indicators)
        if history.empty:
            return None
        swing_highs = history[history["Is_Swing_High"]]
        swing_lows = history[history["Is_Swing_Low"]]
        matches = {key: False for key in FUNNEL_LABELS}
        supports: dict[str, float] = {}

        # Funnel 1: confirmed pressure broken, then revisited as support.
        if not swing_highs.empty:
            last_high = swing_highs.iloc[-1]
            bars_after_high = indicators.loc[indicators.index > last_high.name].iloc[:-1]
            had_breakout = not bars_after_high.empty and bool((bars_after_high["Close"] > last_high["High"]).any())
            revisits_zone = current["Low"] <= last_high["High"] * 1.01 and current["Close"] >= last_high["Body_Max"]
            if had_breakout and revisits_zone:
                matches["Funnel_1"] = True
                supports["Funnel_1"] = float(last_high["Body_Max"])

        # Funnel 2: range boundary / double-bottom right foot. Two confirmed
        # pivot lows must be within 2%, and today's wick must hold the boundary.
        if len(swing_lows) >= 2:
            left, right = swing_lows.iloc[-2], swing_lows.iloc[-1]
            boundary_low = min(float(left["Low"]), float(right["Low"]))
            boundary_high = max(float(left["Low"]), float(right["Low"]))
            within_two_percent = (boundary_high / boundary_low - 1) <= 0.02 if boundary_low > 0 else False
            touches_boundary = current["Low"] <= boundary_high * 1.01 and current["Low"] >= boundary_low * 0.97
            if within_two_percent and touches_boundary and current["Close"] >= boundary_low:
                matches["Funnel_2"] = True
                supports["Funnel_2"] = boundary_low

        # Funnel 3: Wyckoff-style spring / false breakdown recovery.
        if not swing_lows.empty:
            support = swing_lows.iloc[-1]
            if current["Low"] < support["Low"] and current["Close"] >= support["Low"]:
                matches["Funnel_3"] = True
                supports["Funnel_3"] = min(float(current["Low"]), float(support["Low"]))

        # Funnel 4: a strict high-volume bearish order block and impulse origin.
        order_block_support = self._order_block_match(history, current)
        if order_block_support is not None:
            matches["Funnel_4"] = True
            supports["Funnel_4"] = order_block_support

        matched = [key for key, value in matches.items() if value]
        if not matched or not supports:
            return None
        reference_close = float(current["Close"])
        previous_close = float(indicators["Close"].iloc[-2])
        support_edge = min(supports.values())
        reference_boundary = support_edge - self.atr_multiplier * float(current["ATR"])
        if reference_close <= reference_boundary:
            return None
        return {
            "matched_funnels": matched,
            "funnel_labels": [FUNNEL_LABELS[key] for key in matched],
            "reference_close": round(reference_close, 2),
            "previous_close": round(previous_close, 2),
            "change_percent": round((reference_close / previous_close - 1) * 100, 2) if previous_close else None,
            "support_edge": round(support_edge, 2),
            "atr": round(float(current["ATR"]), 2),
            "reference_boundary": round(reference_boundary, 2),
            # Kept for the separate, non-public backtest module. research_report
            # intentionally omits these execution-model fields from Mini App data.
            "reference_stop": round(reference_boundary, 2),
            "reference_risk": round(reference_close - reference_boundary, 2),
            "volume": float(current["Volume"]),
            "turnover": round(float(current["Volume"] * current["Close"]), 2),
            "pullback_confirmed": True,
            "score": structure_match_score(matched),
        }

    def screen(self, market_data: dict[str, pd.DataFrame], limit: int = 5) -> pd.DataFrame:
        """Return qualifying candidates by liquidity-first research priority.

        The ranking is deliberately not a return forecast: cash turnover is
        the first tie-breaker, followed by volume, number of confirmed
        structures, and finally the transparent structure score.
        """
        candidates: list[dict[str, Any]] = []
        for ticker, daily in market_data.items():
            result = self.scan_daily(daily)
            if result:
                candidates.append({
                    "ticker": ticker,
                    **result,
                    "structure_count": len(result.get("matched_funnels") or []),
                })
        if not candidates:
            return pd.DataFrame()
        frame = pd.DataFrame(candidates)
        # Keep the ranking contract robust for research adapters that omit a
        # secondary field; a missing liquidity value ranks below observed data.
        for field in ("turnover", "volume", "structure_count", "score"):
            if field not in frame:
                frame[field] = 0.0
        return (
            frame
            .sort_values(
                ["turnover", "volume", "structure_count", "score"],
                ascending=[False, False, False, False],
                kind="stable",
            )
            .head(limit)
            .reset_index(drop=True)
        )
