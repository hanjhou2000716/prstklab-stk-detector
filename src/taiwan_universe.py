"""Public Taiwan listed/OTC stock-universe discovery for research scans."""
from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd
import requests

ISIN_URL = "https://isin.twse.com.tw/isin/C_public.jsp?strMode={mode}"
# The ISIN HTML page is a convenient discovery source but has repeatedly
# changed shape/returned an empty document.  These public official endpoints
# are the fail-closed fallback for a production scan.
TWSE_OPENAPI_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_CLOSE_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PRStKInvestmentSystem/1.0)"}


_NON_ORDINARY_TERMS = tuple(
    term.lower()
    for term in (
        "ETF", "ETN", "權證", "認購", "認售", "債券", "受益證券", "存託憑證", "特別股",
        "指數股票型", "槓桿型", "反向型", "基金", "公司債", "金融債",
    )
)


def _is_ordinary_share(code: Any, name: Any = "") -> bool:
    """Keep four-digit ordinary shares and exclude derivatives/funds."""
    code_text = str(code or "").strip()
    if len(code_text) != 4 or not code_text.isdigit():
        return False
    name_text = str(name or "").strip().lower()
    return not any(term in name_text for term in _NON_ORDINARY_TERMS)


def _value(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return None


def parse_twse_openapi_records(payload: Any) -> list[dict[str, str]]:
    """Normalize TWSE's official listed-company OpenAPI response."""
    records = payload if isinstance(payload, list) else payload.get("data", []) if isinstance(payload, dict) else []
    items: list[dict[str, str]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        code = _value(record, "公司代號", "公司代碼", "Code", "code")
        name = _value(record, "公司簡稱", "公司名稱", "CompanyName", "name")
        if not _is_ordinary_share(code, name):
            continue
        code_text = str(code).strip()
        items.append({
            "ticker": code_text,
            "name": str(name or code_text).strip(),
            "symbol": f"{code_text}.TW",
            "category": str(_value(record, "產業別", "產業類別", "industry") or "").strip(),
        })
    return items


def parse_tpex_daily_close_records(payload: Any) -> list[dict[str, str]]:
    """Normalize TPEx's official daily-close OpenAPI response."""
    records = payload if isinstance(payload, list) else payload.get("data", []) if isinstance(payload, dict) else []
    items: list[dict[str, str]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        code = _value(record, "SecuritiesCompanyCode", "證券代號", "Code", "code")
        name = _value(record, "CompanyName", "公司名稱", "公司簡稱", "name")
        if not _is_ordinary_share(code, name):
            continue
        code_text = str(code).strip()
        items.append({
            "ticker": code_text,
            "name": str(name or code_text).strip(),
            "symbol": f"{code_text}.TWO",
            "category": "TPEx ordinary share",
        })
    return items


def _official_json(session: Any, url: str) -> Any:
    response = session.get(url, headers=HEADERS, timeout=20)
    response.raise_for_status()
    return response.json()


def fetch_official_taiwan_universe(session: Any = requests) -> list[dict[str, str]]:
    """Fetch listed/OTC ordinary shares from official TWSE/TPEx APIs."""
    errors: list[str] = []
    items: list[dict[str, str]] = []
    try:
        items.extend(parse_twse_openapi_records(_official_json(session, TWSE_OPENAPI_URL)))
    except Exception as error:
        errors.append(f"TWSE OpenAPI: {type(error).__name__}")
    try:
        items.extend(parse_tpex_daily_close_records(_official_json(session, TPEX_CLOSE_URL)))
    except Exception as error:
        errors.append(f"TPEx OpenAPI: {type(error).__name__}")
    unique: dict[str, dict[str, str]] = {}
    for item in items:
        unique.setdefault(item["symbol"], item)
    if unique:
        return list(unique.values())
    detail = "; ".join(errors) or "empty response"
    raise RuntimeError(f"official Taiwan universe sources unavailable: {detail}")

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
            if items:
                return items
            raise ValueError("ISIN source returned no ordinary shares")
        except (requests.RequestException, ValueError, IndexError, TypeError, ImportError) as error:
            last_error = error
    try:
        return fetch_official_taiwan_universe(session)
    except Exception as official_error:
        if last_error is not None:
            raise RuntimeError(f"Taiwan universe discovery failed: {last_error}; {official_error}") from official_error
        raise


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
