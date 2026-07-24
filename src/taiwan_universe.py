"""Public Taiwan listed/OTC stock-universe discovery for research scans."""
from __future__ import annotations
from io import StringIO
import json
from pathlib import Path
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
    """Fetch listed and OTC ordinary-share identifiers, retrying the source once."""
    last_error: Exception | None = None
    for _ in range(2):
        try:
            items = []
            for mode, suffix in ((2, ".TW"), (4, ".TWO")):
                response = session.get(ISIN_URL.format(mode=mode), headers=HEADERS, timeout=20)
                response.raise_for_status()
                items.extend(parse_isin_table(response.text, suffix))
            return items
        except requests.RequestException as error:
            last_error = error
    assert last_error is not None
    raise last_error


def load_or_fetch_taiwan_universe(cache_path: str | Path | None = None) -> list[dict[str, str]]:
    """Reuse a same-run public snapshot when supplied; otherwise fetch a fresh one."""
    if cache_path is not None:
        path = Path(cache_path)
        if path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(saved, list) and all(isinstance(item, dict) for item in saved):
                return saved

    items = fetch_taiwan_universe()
    if cache_path is not None:
        path = Path(cache_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return items
