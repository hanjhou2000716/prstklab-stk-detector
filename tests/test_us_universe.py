import pandas as pd
from src.us_universe import normalize_symbol, parse_constituents

def test_parses_public_constituents_and_normalizes_share_classes():
    tables = [pd.DataFrame({"Symbol": ["BRK.B", "NVDA"], "Security": ["Berkshire", "NVIDIA"]})]
    assert normalize_symbol("BRK.B") == "BRK-B"
    assert parse_constituents(tables)[0]["ticker"] == "BRK-B"
