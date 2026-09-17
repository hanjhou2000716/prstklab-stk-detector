import numpy as np
import pandas as pd
import pytest

from src.taiwan_macro_fgi import FGIUnavailableError, calculate_taiwan_macro_fgi, fgi_label, percentile_rank


def _frame(seed: int, scale: float = 1.0) -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=260, freq="B")
    values = np.linspace(100 * scale, 150 * scale, len(index)) + np.sin(np.arange(len(index)) + seed)
    return pd.DataFrame({"Close": values, "Volume": np.linspace(1_000_000, 2_000_000, len(index))}, index=index)


def test_percentile_rank_and_bands_match_the_fixed_model_thresholds():
    assert percentile_rank(pd.Series(range(120))) == 100
    assert fgi_label(75) == "極度貪婪"
    assert fgi_label(56) == "貪婪"
    assert fgi_label(45) == "中立"
    assert fgi_label(26) == "恐慌"
    assert fgi_label(25.9) == "極度恐慌"


def test_macro_fgi_returns_all_five_public_components():
    frames = {"^TWII": _frame(1), "^TWOII": _frame(2, 0.1), "TWD=X": _frame(3, 0.3)}
    result = calculate_taiwan_macro_fgi(lambda symbol: frames[symbol])

    assert 0 <= result["score"] <= 100
    assert result["source_label"] == "TAIEX Macro FGI"
    assert set(result["sub_scores"]) == {"動能", "波動", "內資投機", "外資流向", "量能"}
    assert result["data_quality"] == "primary"
    assert set(result["component_health"]) == {"^TWII", "^TWOII", "TWD=X"}


def test_macro_fgi_reports_component_failure_and_uses_legitimate_last_good(tmp_path):
    frames = {"^TWII": _frame(1), "^TWOII": _frame(2, 0.1), "TWD=X": _frame(3, 0.3)}
    cache = tmp_path / "fgi.json"
    good = calculate_taiwan_macro_fgi(lambda symbol: frames[symbol], cache_path=cache)

    def failing(symbol):
        if symbol == "TWD=X":
            raise TimeoutError("provider timeout")
        return frames[symbol]

    stale = calculate_taiwan_macro_fgi(failing, cache_path=cache)
    assert stale["score"] == good["score"]
    assert stale["date"] == good["date"]
    assert stale["data_quality"] == "stale_last_good"
    assert stale["stale_components"] == ["TWD=X"]
    assert stale["component_health"]["TWD=X"]["status"] == "failed"


def test_macro_fgi_fails_closed_when_no_component_or_cache_exists(tmp_path):
    with pytest.raises(FGIUnavailableError) as error:
        calculate_taiwan_macro_fgi(lambda symbol: pd.DataFrame(), cache_path=tmp_path / "missing.json")
    assert error.value.component_health["^TWII"]["status"] == "failed"


def test_macro_fgi_rejects_duplicate_dates_and_boolean_values(tmp_path):
    valid = _frame(1)
    duplicate = pd.concat([valid, valid.iloc[:1]])
    with pytest.raises(FGIUnavailableError) as duplicate_error:
        calculate_taiwan_macro_fgi(
            lambda symbol: duplicate if symbol == "^TWOII" else valid,
            cache_path=tmp_path / "duplicate.json",
        )
    assert duplicate_error.value.component_health["^TWOII"]["status"] == "duplicate_dates"

    boolean_frame = valid.astype(object)
    boolean_frame.iloc[0, 0] = True
    with pytest.raises(FGIUnavailableError) as boolean_error:
        calculate_taiwan_macro_fgi(
            lambda symbol: boolean_frame if symbol == "^TWII" else valid,
            cache_path=tmp_path / "boolean.json",
        )
    assert boolean_error.value.component_health["^TWII"]["status"] == "invalid_type"
