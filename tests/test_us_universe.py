import pandas as pd

from src.us_universe import SEMICONDUCTOR_CORE, normalize_symbol, parse_constituents, parse_nasdaq100_constituents


def test_parses_public_constituents_and_normalizes_share_classes():
    tables = [pd.DataFrame({"Symbol": ["BRK.B", "NVDA"], "Security": ["Berkshire", "NVIDIA"]})]
    assert normalize_symbol("BRK.B") == "BRK-B"
    assert parse_constituents(tables)[0]["ticker"] == "BRK-B"


def test_parses_nasdaq_and_declares_semiconductor_core():
    payload = {"aaData": [{"Symbol": "MSFT", "Name": "Microsoft"}, {"Symbol": "NVDA", "Name": "NVIDIA"}]}

    assert parse_nasdaq100_constituents(payload)[1]["ticker"] == "NVDA"
    assert ("NVDA", "NVIDIA") in SEMICONDUCTOR_CORE
