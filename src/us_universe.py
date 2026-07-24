"""Public US large-cap universe discovery for research scans."""
from __future__ import annotations
from typing import Any
import pandas as pd

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

def normalize_symbol(symbol: str) -> str:
    """Convert share-class dots to Yahoo Finance's public ticker format."""
    return symbol.strip().replace(".", "-")

def parse_constituents(tables: list[pd.DataFrame]) -> list[dict[str, str]]:
    for table in tables:
        if "Symbol" in table.columns and "Security" in table.columns:
            return [{"ticker": normalize_symbol(str(row["Symbol"])), "name": str(row["Security"]), "symbol": normalize_symbol(str(row["Symbol"]))} for _, row in table.iterrows()]
    raise ValueError("找不到美股成分股清單。")

def fetch_us_large_cap_universe(reader: Any = pd.read_html) -> list[dict[str, str]]:
    return parse_constituents(reader(SP500_URL))
