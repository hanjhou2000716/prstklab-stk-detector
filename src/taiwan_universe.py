"""Public Taiwan listed/OTC stock-universe discovery for research scans."""
from __future__ import annotations
from io import StringIO
from typing import Any
import pandas as pd
import requests

ISIN_URL = "https://isin.twse.com.tw/isin/C_public.jsp?strMode={mode}"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PRStKInvestmentSystem/1.0)"}

def parse_isin_table(html: str, suffix: str) -> list[dict[str, str]]:
    table = pd.read_html(StringIO(html), header=None)[0]
    items = []
    for _, row in table.iterrows():
        parts = str(row.iloc[0]).split()
        category = str(row.iloc[-1]) if len(row) else ""
        if len(parts) != 2 or len(parts[0]) != 4 or category in {"權證", "牛熊證", "認購(售)權證"}:
            continue
        items.append({"ticker": parts[0], "name": parts[1], "symbol": f"{parts[0]}{suffix}", "category": category})
    return items

def fetch_taiwan_universe(session: Any = requests) -> list[dict[str, str]]:
    """Fetch listed and OTC ordinary-share identifiers; source errors propagate."""
    items = []
    for mode, suffix in ((2, ".TW"), (4, ".TWO")):
        response = session.get(ISIN_URL.format(mode=mode), headers=HEADERS, timeout=20)
        response.raise_for_status()
        items.extend(parse_isin_table(response.text, suffix))
    return items
