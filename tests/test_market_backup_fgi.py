from __future__ import annotations

import pandas as pd

from src.taiwan_macro_fgi import calculate_taiwan_macro_fgi


def test_fgi_can_use_complete_supabase_history_as_historical_backup(monkeypatch):
    dates = pd.date_range("2025-01-01", periods=260, freq="B")

    def rows(close_scale: float, *, volume: bool = False):
        return [
            {
                "market_date": observed.date().isoformat(),
                "price": close_scale + index * 0.1,
                "volume": 1_000_000 + index * 100 if volume else None,
            }
            for index, observed in enumerate(dates)
        ]

    class Store:
        def history_quotes(self, ticker: str, *, limit: int = 500):
            return {
                "TAIEX": rows(20_000, volume=True),
                "TPEx": rows(200),
                "USD/TWD": rows(32),
            }[ticker]

    import yfinance as yf

    monkeypatch.setattr(yf, "download", lambda *_args, **_kwargs: pd.DataFrame())
    monkeypatch.setattr(
        "src.taiwan_macro_sources.fetch_official_taiwan_components",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr("src.market_backup.from_environment", lambda: Store())

    result = calculate_taiwan_macro_fgi()

    assert result["calculation_state"] == "backup_history"
    assert result["data_quality"] == "backup_history"
    assert all(item["source"] == "supabase_backup" for item in result["component_health"].values())
