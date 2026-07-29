import pandas as pd

from src.research_contract import latest_quote_context


def test_latest_quote_context_uses_completed_bar_and_common_fields():
    frame = pd.DataFrame(
        {"Close": [100.0, 105.0], "Volume": [10, 20]},
        index=pd.to_datetime(["2026-07-27", "2026-07-28"]),
    )

    context = latest_quote_context(frame)

    assert context == {
        "close": 105.0,
        "previous_close": 100.0,
        "change_percent": 5.0,
        "turnover": 2100.0,
        "as_of": "2026-07-28",
    }
