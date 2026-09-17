"""Parsers and bounded collectors for Taiwan official macro history.

Transport is intentionally kept separate from the FGI formula so parser
fixtures can be tested without network access and a provider outage can fall
back to the existing public adapter.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from io import StringIO
from typing import Any
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

TWSE_INDEX_HISTORY_URL = "https://www.twse.com.tw/indicesReport/MI_5MINS_HIST"
TWSE_MARKET_HISTORY_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"
TPEX_INDEX_HISTORY_URL = "https://www.tpex.org.tw/www/zh-tw/indexInfo/inx"
CBC_HISTORY_URL = "https://www.cbc.gov.tw/tw/lp-2151-1.html"
HEADERS = {"User-Agent": "PRStK-Lab-public-research/1.0"}


def _date_value(value: Any) -> str | None:
    text = str(value or "").strip()
    parts = re.split(r"[/-]", text)
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        year, month, day = (int(part) for part in parts)
        if year < 1911:
            year += 1911
        raw = f"{year:04d}{month:02d}{day:02d}"
    else:
        raw = text.replace("/", "").replace("-", "")
    if len(raw) == 7 and raw.isdigit():
        raw = f"{int(raw[:3]) + 1911}{raw[3:]}"
    if len(raw) != 8 or not raw.isdigit():
        return None
    try:
        return datetime.strptime(raw, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed and abs(parsed) != float("inf") else None


def _rows(payload: Any) -> tuple[list[str], list[list[Any]]]:
    if not isinstance(payload, dict):
        return [], []
    fields = [str(item) for item in (payload.get("fields") or payload.get("Fields") or [])]
    data = payload.get("data") or payload.get("Data") or []
    if not fields or not data:
        # TPEx's current endpoint wraps the selected table in ``tables`` while
        # TWSE still returns fields/data at the top level.  Accept both shapes
        # without weakening the field-based parser below.
        for table in payload.get("tables") or payload.get("Tables") or []:
            if not isinstance(table, dict):
                continue
            candidate_fields = table.get("fields") or table.get("Fields") or []
            candidate_data = table.get("data") or table.get("Data") or []
            if candidate_fields and candidate_data:
                fields = [str(item) for item in candidate_fields]
                data = candidate_data
                break
    return fields, [row for row in data if isinstance(row, list)]


def parse_official_index_history(payload: Any, *, label: str = "index") -> pd.DataFrame:
    """Parse TWSE/TPEx date + close rows using field names, never position guesses."""
    fields, rows = _rows(payload)
    date_index = next((i for i, name in enumerate(fields) if any(token in name for token in ("日期", "Date", "date"))), 0)
    close_index = next(
        (
            i for i, name in enumerate(fields)
            if any(token in name for token in ("收盤", "收市", "Close", "Index", "加權股價", "指數"))
            and not any(token in name for token in ("日期", "Date", "date"))
        ),
        None,
    )
    values: list[tuple[str, float]] = []
    for row in rows:
        if close_index is None or close_index >= len(row):
            continue
        observed = _date_value(row[date_index] if date_index < len(row) else None)
        close = _number(row[close_index])
        if observed and close is not None and close > 0:
            values.append((observed, close))
    if not values:
        return pd.DataFrame(columns=["Close"])
    frame = pd.DataFrame(values, columns=["date", "Close"]).drop_duplicates("date").set_index("date")
    frame.index = pd.to_datetime(frame.index)
    frame["Close"] = pd.to_numeric(frame["Close"], errors="coerce")
    return frame.sort_index().dropna()


def parse_official_market_history(payload: Any) -> pd.DataFrame:
    """Parse the TWSE historical market-statistics volume series."""
    fields, rows = _rows(payload)
    date_index = next((i for i, name in enumerate(fields) if any(token in name for token in ("日期", "Date", "date"))), 0)
    volume_index = next((i for i, name in enumerate(fields) if any(token in name for token in ("成交金額", "成交金額", "TradeValue"))), None)
    values: list[tuple[str, float]] = []
    for row in rows:
        if volume_index is None or volume_index >= len(row):
            continue
        observed = _date_value(row[date_index] if date_index < len(row) else None)
        volume = _number(row[volume_index])
        if observed and volume is not None and volume >= 0:
            values.append((observed, volume))
    if not values:
        return pd.DataFrame(columns=["Volume"])
    frame = pd.DataFrame(values, columns=["date", "Volume"]).drop_duplicates("date").set_index("date")
    frame.index = pd.to_datetime(frame.index)
    return frame.sort_index().dropna()


def parse_cbc_usd_twd_history(payload: Any) -> pd.DataFrame:
    """Parse a CBC-exported date/rate table supplied as JSON or rows."""
    fields, rows = _rows(payload)
    if not rows and isinstance(payload, list):
        rows = [row for row in payload if isinstance(row, list)]
    date_index = next((i for i, name in enumerate(fields) if any(token in name for token in ("日期", "Date", "date"))), 0)
    rate_index = next((i for i, name in enumerate(fields) if any(token in name for token in ("美元", "USD", "本行買入", "即期買入"))), None)
    values: list[tuple[str, float]] = []
    for row in rows:
        if rate_index is None or rate_index >= len(row):
            continue
        observed = _date_value(row[date_index] if date_index < len(row) else None)
        rate = _number(row[rate_index])
        if observed and rate is not None and rate > 0:
            values.append((observed, rate))
    if not values:
        return pd.DataFrame(columns=["Close"])
    frame = pd.DataFrame(values, columns=["date", "Close"]).drop_duplicates("date").set_index("date")
    frame.index = pd.to_datetime(frame.index)
    return frame.sort_index().dropna()


def parse_cbc_html_history(html: str) -> pd.DataFrame:
    """Extract a CBC table when the official page exposes an HTML export."""
    try:
        # pandas 3 treats a raw HTML string as a filename; StringIO keeps this
        # parser compatible with both pandas 2 and 3.
        tables = pd.read_html(StringIO(html))
    except (ValueError, ImportError):
        return pd.DataFrame(columns=["Close"])
    for table in tables:
        if table.empty:
            continue
        fields = [str(value) for value in table.columns]
        rows = [list(row) for row in table.itertuples(index=False, name=None)]
        parsed = parse_cbc_usd_twd_history({"fields": fields, "data": rows})
        if len(parsed) >= 2:
            return parsed
    return pd.DataFrame(columns=["Close"])


def _cbc_year_links(html: str, *, base_url: str) -> dict[int, str]:
    """Return official CBC annual detail pages keyed by calendar year."""
    soup = BeautifulSoup(html, "html.parser")
    links: dict[int, str] = {}
    for anchor in soup.select("section.lp .list a[href]"):
        label = anchor.get_text(" ", strip=True)
        title = anchor.get("title")
        if isinstance(title, str) and title.strip():
            label = f"{label} {title.strip()}"
        match = re.search(r"\b(20\d{2})\s*年", label)
        if match:
            links[int(match.group(1))] = urljoin(base_url, str(anchor["href"]))
    return links


def _month_values(months: int) -> list[str]:
    today = date.today().replace(day=1)
    result: list[str] = []
    year, month = today.year, today.month
    for _ in range(max(1, months)):
        result.append(f"{year:04d}{month:02d}01")
        month -= 1
        if month == 0:
            year -= 1
            month = 12
    return result


def fetch_official_taiwan_components(
    *, session: requests.Session | None = None, months: int = 18,
) -> dict[str, pd.DataFrame]:
    """Collect best-effort official histories; missing months remain explicit."""
    client = session or requests.Session()
    index_frames: list[pd.DataFrame] = []
    tpex_frames: list[pd.DataFrame] = []
    volume_frames: list[pd.DataFrame] = []
    for month in _month_values(months):
        try:
            response = client.get(
                TWSE_INDEX_HISTORY_URL,
                params={"date": month, "response": "json"}, headers=HEADERS, timeout=20,
            )
            response.raise_for_status()
            index_frames.append(parse_official_index_history(response.json(), label="TAIEX"))
        except (OSError, ValueError, requests.RequestException):
            pass
        try:
            response = client.post(
                TPEX_INDEX_HISTORY_URL,
                data={"date": f"{month[:4]}/{month[4:6]}/01", "response": "json"},
                headers=HEADERS, timeout=20,
            )
            response.raise_for_status()
            tpex_frames.append(parse_official_index_history(response.json(), label="TPEx"))
        except (OSError, ValueError, requests.RequestException):
            pass
        try:
            response = client.get(
                TWSE_MARKET_HISTORY_URL,
                params={"date": month, "response": "json", "selectType": "ALL"},
                headers=HEADERS, timeout=20,
            )
            response.raise_for_status()
            volume_frames.append(parse_official_market_history(response.json()))
        except (OSError, ValueError, requests.RequestException):
            pass
    twd = pd.DataFrame(columns=["Close"])
    try:
        response = client.get(CBC_HISTORY_URL, headers=HEADERS, timeout=20)
        response.raise_for_status()
        # CBC publishes the daily series as one HTML page per calendar year.
        # The index page is the stable discovery endpoint; fetch only the
        # years needed for the requested history window.
        raw_content = getattr(response, "content", None)
        encoding = getattr(response, "apparent_encoding", None) or "utf-8"
        index_html = (
            raw_content.decode(encoding, errors="replace")
            if isinstance(raw_content, (bytes, bytearray))
            else str(getattr(response, "text", ""))
        )
        year_links = _cbc_year_links(index_html, base_url=CBC_HISTORY_URL)
        target_years = set(range(date.today().year, date.today().year - max(2, math.ceil(months / 12) + 1), -1))
        annual_frames: list[pd.DataFrame] = []
        for year in sorted(target_years & year_links.keys(), reverse=True):
            try:
                annual = client.get(year_links[year], headers=HEADERS, timeout=20)
                annual.raise_for_status()
                annual_content = getattr(annual, "content", None)
                annual_encoding = getattr(annual, "apparent_encoding", None) or "utf-8"
                annual_html = (
                    annual_content.decode(annual_encoding, errors="replace")
                    if isinstance(annual_content, (bytes, bytearray))
                    else str(getattr(annual, "text", ""))
                )
                parsed = parse_cbc_html_history(annual_html)
                if not parsed.empty:
                    annual_frames.append(parsed)
            except (OSError, ValueError, requests.RequestException):
                continue
        if annual_frames:
            twd = pd.concat(annual_frames).sort_index()
            twd = twd[~twd.index.duplicated(keep="last")]
    except (OSError, ValueError, requests.RequestException):
        pass
    def combine(frames: list[pd.DataFrame], columns: list[str]) -> pd.DataFrame:
        usable = [frame for frame in frames if not frame.empty]
        if not usable:
            return pd.DataFrame(columns=columns)
        combined = pd.concat(usable).sort_index()
        return combined[~combined.index.duplicated(keep="last")]

    return {
        "^TWII": combine(index_frames, ["Close"]),
        "^TWOII": combine(tpex_frames, ["Close"]),
        "TAIEX_VOLUME": combine(volume_frames, ["Volume"]),
        # CBC transport is intentionally injectable.  Its downloadable file
        # has changed shape over time, so the parser remains the stable contract.
        "TWD=X": twd,
    }


__all__ = [
    "CBC_HISTORY_URL", "TPEX_INDEX_HISTORY_URL", "TWSE_INDEX_HISTORY_URL",
    "TWSE_MARKET_HISTORY_URL", "fetch_official_taiwan_components",
    "parse_cbc_html_history", "parse_cbc_usd_twd_history", "parse_official_index_history", "parse_official_market_history",
]
