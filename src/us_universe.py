"""Public US large-cap universe discovery for research scans."""
from __future__ import annotations

from datetime import date, timedelta
from io import StringIO
from typing import Any

import pandas as pd
import requests

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
NASDAQ100_URL = "https://indexes.nasdaqomx.com/Index/WeightingData"
NASDAQ100_REFERER = "https://indexes.nasdaqomx.com/Index/Weighting/NDX"

# A transparent, deliberately finite supplemental core. These symbols are
# added even if an index constituent page changes; duplicates are removed.
SEMICONDUCTOR_CORE = (
    ("NVDA", "NVIDIA"), ("AMD", "Advanced Micro Devices"),
    ("AVGO", "Broadcom"), ("TSM", "Taiwan Semiconductor ADR"),
    ("ASML", "ASML Holding"), ("AMAT", "Applied Materials"),
    ("LRCX", "Lam Research"), ("KLAC", "KLA"), ("MU", "Micron Technology"),
    ("INTC", "Intel"), ("QCOM", "Qualcomm"), ("ADI", "Analog Devices"),
    ("MRVL", "Marvell Technology"), ("ARM", "Arm Holdings"),
    ("ON", "onsemi"), ("MCHP", "Microchip Technology"),
)

def normalize_symbol(symbol: str) -> str:
    """Convert share-class dots to Yahoo Finance's public ticker format."""
    return symbol.strip().replace(".", "-")

def parse_constituents(tables: list[pd.DataFrame]) -> list[dict[str, str]]:
    for table in tables:
        if "Symbol" in table.columns and "Security" in table.columns:
            return [{"ticker": normalize_symbol(str(row["Symbol"])), "name": str(row["Security"]), "symbol": normalize_symbol(str(row["Symbol"]))} for _, row in table.iterrows()]
    raise ValueError("找不到美股成分股清單。")

def fetch_us_large_cap_universe(session: Any = requests) -> list[dict[str, str]]:
    """Fetch public constituent page with an explicit user agent."""
    response = session.get(SP500_URL, headers={"User-Agent": "Mozilla/5.0 (compatible; PRStKInvestmentSystem/1.0)"}, timeout=20)
    response.raise_for_status()
    return parse_constituents(pd.read_html(StringIO(response.text)))


def parse_nasdaq100_constituents(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Normalize Nasdaq's public weighting response into scan symbols."""
    rows = payload.get("aaData", [])
    items = [
        {"ticker": normalize_symbol(str(row["Symbol"])), "name": str(row["Name"]), "symbol": normalize_symbol(str(row["Symbol"]))}
        for row in rows
        if isinstance(row, dict) and row.get("Symbol") and row.get("Name")
    ]
    if not items:
        raise ValueError("Nasdaq-100 constituent response unavailable")
    return items


def fetch_us_research_universe(session: Any = requests) -> list[dict[str, str]]:
    """Combine S&P 500, Nasdaq-100 and semiconductor-core public research universes."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; PRStKInvestmentSystem/1.0)", "Referer": NASDAQ100_REFERER}
    sp500 = fetch_us_large_cap_universe(session)
    nasdaq100 = []
    for offset in range(7):
        trade_date = (date.today() - timedelta(days=offset)).isoformat()
        response = session.post(NASDAQ100_URL, data={"id": "NDX", "tradeDate": trade_date, "timeOfDay": "SOD"}, headers=headers, timeout=20)
        response.raise_for_status()
        try:
            nasdaq100 = parse_nasdaq100_constituents(response.json())
            break
        except ValueError:
            continue
    if not nasdaq100:
        raise ValueError("Nasdaq-100 constituents unavailable after seven public dates")
    combined = [*sp500, *nasdaq100, *({"ticker": ticker, "name": name, "symbol": ticker} for ticker, name in SEMICONDUCTOR_CORE)]
    unique: dict[str, dict[str, str]] = {}
    for item in combined:
        unique.setdefault(item["symbol"], item)
    return list(unique.values())
