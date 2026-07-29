import pandas as pd

from src.resonance_smart_money import smart_money_conditions, smart_money_summary


def test_summary_keeps_the_user_priority_order_and_scores_all_four_rules():
    summary = smart_money_summary({
        "absorption": True,
        "liquidity_sweep": True,
        "positive_alpha": True,
        "volatility_expansion": True,
    })

    assert summary == {
        "matched_labels": ["爆量吸收／長下影", "跌破前低後收回", "相對大盤 Alpha > 0", "True Range > 1.1×ATR"],
        "count": 4,
        "score": 100,
        "tier": "四項共振",
    }


def test_alpha_is_unverified_without_a_public_benchmark():
    close = list(range(100, 122))
    frame = pd.DataFrame({
        "Open": close,
        "High": [item + 1 for item in close],
        "Low": [item - 1 for item in close],
        "Close": close,
        "Volume": [1000] * len(close),
    })

    conditions = smart_money_conditions(frame, None)

    assert conditions is not None
    assert conditions["positive_alpha"] is False
