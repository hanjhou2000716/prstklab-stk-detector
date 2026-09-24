"""Deterministic market-context synthesis for scheduled briefings.

This module is intentionally small and side-effect free.  It turns already
validated event/quote observations into a bounded public projection; it does
not fetch data, classify a source by its URL, or make an investment claim.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

TOPIC_LABELS: dict[str, str] = {
    "taiwan_market": "台股行情、廣度與籌碼",
    "semiconductor_ai": "台積電、半導體與 AI 供應鏈",
    "global_market": "美國與全球股市",
    "rates_fx": "利率、通膨、美元與匯率",
    "energy_geopolitics": "能源、航運與地緣風險",
    "company_industry": "公司、產業與監管事件",
}

JOINT_MARKET_SIGNAL_VERSION = "joint-market-signal-v1"
_JOINT_TAIWAN_TICKERS = ("TAIEX", "TXF")
_JOINT_US_TICKERS = ("NASDAQ", "SOX", "DJIA", "S&P 500", "SP500")

_TOPIC_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("semiconductor_ai", ("半導體", "晶片", "芯片", "台積電", "臺積電", "tsmc", "nvidia", "輝達", "ai", "人工智慧", "矽光子")),
    ("rates_fx", ("fed", "fomc", "聯準會", "央行", "利率", "通膨", "通胀", "cpi", "ppi", "pce", "gdp", "非農", "殖利率", "美元", "日圓", "匯率")),
    ("energy_geopolitics", ("原油", "油價", "石油", "能源", "荷姆茲", "霍爾木茲", "hormuz", "opec", "航運", "制裁", "攻擊", "封鎖", "伊朗", "以色列")),
    ("taiwan_market", ("台股", "加權指數", "櫃買", "外資", "投信", "融資", "廣度", "籌碼")),
    ("global_market", ("nasdaq", "那斯達克", "s&p", "標普", "sox", "費半", "道瓊", "美股", "全球股市")),
)

_ROLE_NAMES: dict[str, str] = {
    "沃勒": "Fed官員",
    "waller": "Fed官員",
    "鮑威爾": "Fed主席",
    "鲍威尔": "Fed主席",
    "powell": "Fed主席",
    "貝森特": "美國財長",
    "贝森特": "美國財長",
    "bessent": "美國財長",
}

_PUBLISHER_TAIL_RE = re.compile(
    r"\s*(?:[｜|]\s*)?(?:[^｜|]{0,60}\s+)?(?:新聞|報導|記者|作者|編輯|編譯)\s*[-–—:]?\s*"
    r"(?:Storm\.mg|Storm|Reuters|Bloomberg|Yahoo Finance|Google News)?\s*$",
    re.IGNORECASE,
)
_MEDIA_TAIL_RE = re.compile(
    r"(?:\s*[-–—]\s*(?:Storm\.mg|Reuters|Bloomberg|Yahoo Finance|Yahoo股市|Yahoo新聞|Google News|CNBC|Financial Times|UDN|聯合新聞網|news\.cnyes\.com|鉅亨網|CMoney投資網誌|CMoney|財經焦點情報站))+\s*[。.!?]?\s*$",
    re.IGNORECASE,
)
_BYLINE_MARKER_RE = re.compile(r"(?:記者|作者|編輯|編譯|新聞\s*[-–—:]|\b(?:by|reporting by)\b)", re.IGNORECASE)
_ROLE_PREFIX_RE = re.compile(
    r"(?P<name>沃勒|鮑威爾|鲍威尔|貝森特|贝森特|Waller|Powell|Bessent)\s*(?P<delimiter>[:：]|表示|指出|稱|称|說|说)",
    re.IGNORECASE,
)
_ACTION_RE = re.compile(
    r"(?:表示|指出|宣稱|帶來|宣布|公布|發布|更新|完成|等待|組成|共組|影響|上漲|下跌|升息|降息|干預|供應|中斷|"
    r"said|says|announc|report|release|rise|fall|jump|drop|increase|decrease|disrupt|supply|rate|outlook|earnings|guidance|forecast|profit|revenue|policy|statement)",
    re.IGNORECASE,
)


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _term_in_text(haystack: str, term: str) -> bool:
    normalized = term.casefold()
    if re.fullmatch(r"[a-z0-9]+", normalized):
        return re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", haystack) is not None
    return normalized in haystack


def _strip_tail(title: str) -> tuple[str, bool, bool]:
    value = _text(title)
    byline_removed = False
    publisher_removed = False
    # The pipe is a transport separator in the observed news feeds.  Only
    # remove a suffix when it carries an attribution marker, never a normal
    # fact separated by punctuation.
    parts = re.split(r"[｜|]", value)
    if len(parts) > 1 and _BYLINE_MARKER_RE.search(parts[-1]):
        value = "｜".join(parts[:-1]).strip()
        byline_removed = True
        publisher_removed = True
    before = value
    value = _PUBLISHER_TAIL_RE.sub("", value).strip(" ｜|:：,，")
    if value != before:
        byline_removed = True
        publisher_removed = True
    before = value
    value = _MEDIA_TAIL_RE.sub("", value).strip(" ｜|:：,，")
    if value != before:
        publisher_removed = True
    return value, byline_removed, publisher_removed


def _role_normalize(value: str, event: dict[str, Any]) -> tuple[str, str, str]:
    actor_name = _text(event.get("actor_name") or event.get("person_name"))
    actor_role = _text(event.get("actor_role") or event.get("role"))
    result = value
    match = _ROLE_PREFIX_RE.search(result)
    if match:
        raw_name = match.group("name")
        replacement = _ROLE_NAMES.get(raw_name.casefold(), _ROLE_NAMES.get(raw_name, ""))
        if replacement:
            actor_name = actor_name or raw_name
            actor_role = actor_role or replacement
            delimiter = match.group("delimiter")
            delimiter = "表示" if delimiter in {":", "："} else delimiter
            result = f"{result[:match.start()]}{replacement}{delimiter}" + result[match.end():]
    elif actor_name and actor_role and actor_name in result:
        result = result.replace(actor_name, actor_role, 1)
    return result, actor_role, actor_name if actor_name else ""


def normalize_headline(event: dict[str, Any], fact: str | None = None) -> dict[str, Any]:
    """Return a public-safe fact while keeping the original title untouched."""
    raw_title = _text(
        event.get("raw_title") or event.get("headline") or event.get("title")
        or event.get("event") or event.get("what_happened") or fact
    )
    source = _text(fact or event.get("event") or event.get("summary") or raw_title)
    source, byline_removed, publisher_removed = _strip_tail(source)
    source, actor_role, actor_name = _role_normalize(source, event)
    # These are editorial transport artefacts, not facts.  Keep attribution
    # institutions (e.g. 經濟部) and replace sensational wording conservatively.
    normalized = source.replace("！", "，").replace("!", ",")
    normalized = normalized.replace("「", "").replace("」", "")
    normalized = re.sub(r"等\s*\d+\s*家(?:巨頭|企業|公司|廠商)", "等業者", normalized)
    normalized = normalized.replace("共組", "組成")
    normalized = re.sub(r"(經濟部|政府|公司管理層)\s*[:：]\s*", r"\1表示", normalized)
    normalized = re.sub(r"供應鏈完全掌握在台灣手上", "供應鏈涵蓋台灣廠商", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip(" ｜|:：,，")
    normalized = normalized.rstrip("。！？.!?，,") + "。" if normalized else ""
    complete = bool(normalized and _ACTION_RE.search(normalized) and len(normalized.rstrip("。")) >= 8)
    topic = classify_market_topic(event, normalized)
    return {
        "raw_title": raw_title,
        "normalized_fact": normalized,
        "market_topic": topic,
        "actor_role": actor_role,
        "actor_name": actor_name,
        "headline_actor": _text(event.get("headline_actor") or actor_role),
        "byline_removed": byline_removed,
        "publisher_removed": publisher_removed,
        "normalization_ruleset": "market_headline_normalizer_v1",
        "normalization_complete": complete,
    }


def classify_market_topic(event: dict[str, Any], fact: str = "") -> str:
    """Map an event to one of the six stable investor-facing topics."""
    category = _text((event.get("event_classification") or {}).get("category") if isinstance(event.get("event_classification"), dict) else event.get("category")).casefold()
    category_map = {
        "semiconductor": "semiconductor_ai", "ai": "semiconductor_ai",
        "macro": "rates_fx", "fed": "rates_fx", "currency": "rates_fx",
        "energy": "energy_geopolitics", "conflict": "energy_geopolitics", "black_swan": "energy_geopolitics",
        "market": "global_market", "taiwan_market": "taiwan_market",
        "policy": "company_industry", "earnings": "company_industry", "guidance": "company_industry",
    }
    if category in category_map:
        return category_map[category]
    haystack = f"{_text(event.get('title'))} {_text(event.get('event'))} {fact}".casefold()
    for topic, terms in _TOPIC_TERMS:
        if any(_term_in_text(haystack, term) for term in terms):
            return topic
    return "company_industry"


def topic_label(topic: str | None) -> str:
    return TOPIC_LABELS.get(str(topic or "company_industry"), TOPIC_LABELS["company_industry"])


def _quote_move(item: dict[str, Any]) -> float | None:
    raw_value = item.get("change_percent")
    if raw_value is None:
        return None
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None
    return value if value == value and abs(value) != float("inf") else None


def _joint_ticker(value: Any) -> str:
    ticker = _text(value).upper()
    return {"TPEX": "TPEX", "TPEX.TW": "TPEX", "SPX": "S&P 500"}.get(ticker, ticker)


def _joint_quote_is_usable(item: dict[str, Any]) -> bool:
    """Accept live data or a validated recent close for the joint signal.

    A recent close is intentionally usable even when the provider marks the
    quote as delayed/stale relative to the current session.  The quote's
    ``quote_date``/``data_status`` remain in the evidence so the UI can show
    that it is historical rather than live.  Truly stale, expired, or
    unavailable rows still fail closed.
    """
    freshness = _text(item.get("freshness")).casefold()
    data_status = _text(item.get("data_status")).casefold()
    recent_close = freshness in {"recent_close", "最近收盤"} or data_status in {"recent_close", "最近收盤"}
    if freshness in {"stale", "delayed", "unavailable", "unknown", "failed"}:
        return False
    if data_status in {"stale", "delayed", "unavailable", "unknown", "failed"}:
        return False
    if item.get("quote_delayed") is True and not recent_close:
        return False
    if item.get("stale_used") is True and not recent_close:
        return False
    price_value = item.get("price")
    if price_value is None:
        return False
    try:
        price = float(price_value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(price) and _quote_move(item) is not None


def _joint_market_direction(rows: list[dict[str, Any]]) -> tuple[str, float | None, list[int]]:
    directions = [
        1 if (move := _quote_move(item)) is not None and move > 0.25
        else -1 if move is not None and move < -0.25
        else 0
        for item in rows
    ]
    if not directions:
        return "資料不足", None, []
    score = round(sum(directions) / len(directions), 3)
    non_zero = {direction for direction in directions if direction}
    if len(non_zero) > 1:
        return "分歧", score, directions
    if score > 0.25:
        return "偏多", score, directions
    if score < -0.25:
        return "偏弱", score, directions
    return "中性", score, directions


def _joint_risk_adjustments(risk: dict[str, Any] | None) -> list[str]:
    """Return panic evidence without converting risk labels into price factors."""
    adjustments: list[str] = []
    for market, item in (risk or {}).items() if isinstance(risk, dict) else ():
        if not isinstance(item, dict):
            continue
        sentiment_value = item.get("sentiment")
        sentiment: dict[str, Any] = sentiment_value if isinstance(sentiment_value, dict) else {}
        # A last-known-good Macro FGI is useful for historical context only.
        # It must never lower the current composite market conclusion as if it
        # were a fresh risk observation.
        if str(sentiment.get("calculation_state") or "").strip().lower() in {
            "backup_history", "stale_last_good", "stale",
        }:
            continue
        sentiment_label = _text(sentiment.get("label"))
        vix_value = item.get("vix")
        vix: dict[str, Any] = vix_value if isinstance(vix_value, dict) else {}
        vix_stage = _text(vix.get("stage"))
        if sentiment_label in {"恐慌", "極度恐慌"}:
            adjustments.append(f"{market}情緒：{sentiment_label}")
        if vix_stage in {"恐慌", "極度恐慌"}:
            adjustments.append(f"{market}波動：{vix_stage}")
    return adjustments


def build_joint_market_signal(
    quotes: list[dict[str, Any]], risk: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a page-only Taiwan/US composite from one validated snapshot.

    This signal is descriptive presentation data. It does not replace the
    existing assessment used by notification policy or delivery identity.
    """
    by_ticker: dict[str, dict[str, Any]] = {}
    excluded: list[dict[str, str]] = []
    for item in quotes:
        if not isinstance(item, dict):
            continue
        ticker = _joint_ticker(item.get("ticker"))
        if ticker not in {*_JOINT_TAIWAN_TICKERS, *_JOINT_US_TICKERS}:
            continue
        if ticker in by_ticker:
            excluded.append({"ticker": ticker, "reason": "duplicate_underlying"})
            continue
        if not _joint_quote_is_usable(item):
            excluded.append({"ticker": ticker, "reason": "quote_unusable"})
            continue
        by_ticker[ticker] = item

    taiwan_rows = [by_ticker[ticker] for ticker in _JOINT_TAIWAN_TICKERS if ticker in by_ticker]
    us_rows = [by_ticker[ticker] for ticker in _JOINT_US_TICKERS if ticker in by_ticker]
    taiwan_label, taiwan_score, taiwan_directions = _joint_market_direction(taiwan_rows)
    us_label, us_score, us_directions = _joint_market_direction(us_rows)
    valid_factors = len(taiwan_rows) + len(us_rows)
    evidence_sufficient = valid_factors >= 3 and bool(taiwan_rows) and bool(us_rows)
    price_score = round((taiwan_score + us_score) / 2, 3) if taiwan_score is not None and us_score is not None else None
    if not evidence_sufficient or price_score is None:
        base_label = "資料不足，台美狀態待確認"
    elif price_score > 0.25:
        base_label = "偏多"
    elif price_score < -0.25:
        base_label = "中性偏謹慎"
    else:
        base_label = "中性"
    divergent = (
        taiwan_score is not None and us_score is not None
        and ((taiwan_score > 0.25 and us_score < -0.25) or (taiwan_score < -0.25 and us_score > 0.25))
    )
    risk_adjustments = _joint_risk_adjustments(risk)
    if evidence_sufficient and risk_adjustments and base_label in {"偏多", "中性"}:
        base_label = "中性偏謹慎"
    label = f"台美分歧，整體{base_label}" if divergent and evidence_sufficient else base_label

    def evidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                key: item[key]
                for key in ("ticker", "name", "price", "change_percent", "currency", "freshness", "data_status", "quote_date", "quote_time", "source_label", "source_url")
                if key in item and item[key] not in (None, "")
            }
            for item in rows
        ]

    return {
        "version": JOINT_MARKET_SIGNAL_VERSION,
        "status": "complete" if evidence_sufficient else "insufficient_evidence",
        "label": label,
        "base_label": base_label,
        "taiwan": {"label": taiwan_label, "score": taiwan_score, "directions": taiwan_directions, "valid_factors": len(taiwan_rows)},
        "us": {"label": us_label, "score": us_score, "directions": us_directions, "valid_factors": len(us_rows)},
        "price_score": price_score,
        "valid_factor_count": valid_factors,
        "minimum_factor_count": 3,
        "risk_adjustments": risk_adjustments,
        "divergent": divergent,
        "evidence": {"taiwan": evidence(taiwan_rows), "us": evidence(us_rows)},
        "excluded_factors": excluded,
        "confidence": "medium" if evidence_sufficient else "low",
    }


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)


def _quote_factors(
    quotes: Iterable[dict[str, Any]], *, slot: str = "",
) -> tuple[dict[str, float], set[str], set[str], dict[str, list[str]], list[str]]:
    """Build scope-aware factors instead of treating every asset as peers.

    A Nasdaq move and a Taiwan cash-index move are different evidence
    dimensions.  They can be compared, but one opposite print must not turn
    an otherwise coherent Taiwan session into a generic ``分歧`` label.
    """
    rows: dict[str, dict[str, Any]] = {}
    for item in quotes:
        ticker = _text(item.get("ticker")).upper()
        move = _quote_move(item)
        if ticker and move is not None:
            rows[ticker] = {"move": move, "item": item}

    def sign(move: float, threshold: float = 0.25) -> float:
        return 1.0 if move > threshold else -1.0 if move < -threshold else 0.0

    groups: dict[str, tuple[str, ...]] = {
        "taiwan_core": ("TAIEX", "TXF", "TPEX", "2330"),
        "us_tech": ("SOX", "NASDAQ"),
        "us_broad": ("S&P 500", "DJIA"),
        "us_futures": ("ES", "NQ", "YM"),
        "asia_tech": ("NIKKEI", "KOSPI"),
        "rates_fx": ("US10Y", "DXY", "USD/TWD"),
        "commodities": ("WTI", "BRENT", "GOLD"),
    }
    group_values: dict[str, list[float]] = {}
    group_tickers: dict[str, list[str]] = {}
    for group, tickers in groups.items():
        values: list[float] = []
        names: list[str] = []
        for ticker in tickers:
            row = rows.get(ticker)
            if not row:
                continue
            move = float(row["move"])
            threshold = 0.75 if group == "commodities" else 0.25
            value = sign(move, threshold)
            if group in {"rates_fx", "commodities"}:
                # Rising rates/USD/oil are descriptive headwinds; rising gold
                # is a defensive signal and does not receive an equity boost.
                if ticker in {"US10Y", "DXY", "USD/TWD", "WTI", "BRENT"}:
                    value *= -1.0
            values.append(value)
            names.append(ticker)
        if values:
            group_values[group] = values
            group_tickers[group] = names

    # The report scope determines which groups can dominate the conclusion.
    if slot in {"pre_open", "intraday", "midday", "afternoon", "post_close"}:
        weights = {"taiwan_core": 2.0, "us_tech": 0.5, "asia_tech": 0.35, "rates_fx": 0.25, "commodities": 0.25}
    elif slot in {"us_premarket", "us_open"}:
        weights = {"us_tech": 1.5, "us_broad": 1.25, "asia_tech": 0.5, "rates_fx": 0.5, "commodities": 0.35}
    else:
        weights = {"taiwan_core": 1.25, "us_tech": 1.0, "us_broad": 0.75, "asia_tech": 0.5, "rates_fx": 0.5, "commodities": 0.35}

    factors: dict[str, float] = {}
    valid_dimensions: set[str] = set()
    positive: set[str] = set()
    negative: set[str] = set()
    for group, values in group_values.items():
        average = sum(values) / len(values)
        weighted = round(average * weights.get(group, 0.0), 3)
        factors[f"group:{group}"] = weighted
        if group == "taiwan_core":
            valid_dimensions.add("taiwan_equity")
        elif group in {"us_tech", "us_broad", "asia_tech"}:
            valid_dimensions.add("us_equity" if group != "asia_tech" else "asia_equity")
        elif group == "us_futures":
            valid_dimensions.add("us_index_futures")
        elif group == "rates_fx":
            valid_dimensions.add("rates_fx")
        else:
            valid_dimensions.add("commodity")
        if weighted > 0:
            positive.update(group_tickers[group])
        elif weighted < 0:
            negative.update(group_tickers[group])

    recognised_tickers = [ticker for tickers in group_tickers.values() for ticker in tickers]
    return factors, valid_dimensions, positive | negative, group_tickers, recognised_tickers


def _stance(score: float, factor_count: int, dimensions: set[str], conflict: bool) -> tuple[str, str, str]:
    if conflict:
        return "divergent", "分歧", "medium"
    if factor_count < 3 or len(dimensions) < 2:
        return "insufficient_evidence", "資料不足", "low"
    if score >= 2:
        return "bullish", "偏多", "high" if factor_count >= 4 else "medium"
    if score >= 0.5:
        return "mildly_bullish", "中性偏多", "medium"
    if score > -0.5:
        return "divergent", "分歧", "medium"
    if score > -2:
        return "cautious", "中性偏謹慎", "medium"
    return "bearish", "偏空", "high" if factor_count >= 4 else "medium"


def _topic_driver(theme: dict[str, Any] | None) -> str:
    if not isinstance(theme, dict):
        return "市場焦點待價格確認"
    topic = str(theme.get("market_topic") or "company_industry")
    return {
        "taiwan_market": "台股盤面焦點",
        "semiconductor_ai": "半導體與AI焦點",
        "global_market": "外圍股市焦點",
        "rates_fx": "利率與美元焦點",
        "energy_geopolitics": "能源與地緣焦點",
        "company_industry": "公司與產業焦點",
    }.get(topic, "市場焦點待價格確認")


def _quote_highlights(quotes: list[dict[str, Any]], slot: str = "") -> str:
    names = {
        "TAIEX": "加權指數", "TXF": "台指期", "TPEX": "櫃買",
        "S&P 500": "標普500", "NASDAQ": "那斯達克綜合", "SOX": "費半", "DJIA": "道瓊",
        "ES": "ES期貨", "NQ": "NQ期貨（Nasdaq-100）", "YM": "YM期貨",
        "NIKKEI": "日經", "KOSPI": "韓股",
    }
    parts: list[str] = []
    preferred = (
        ("TAIEX", "TXF", "TPEX", "2330", "SOX", "NASDAQ", "US10Y", "DXY", "WTI", "GOLD")
        if slot in {"pre_open", "intraday", "midday", "afternoon", "post_close"}
        else ("S&P 500", "NASDAQ", "DJIA", "ES", "NQ", "YM", "SOX", "US10Y", "DXY", "WTI", "GOLD")
    )
    ordered = sorted(quotes, key=lambda item: preferred.index(_text(item.get("ticker")).upper()) if _text(item.get("ticker")).upper() in preferred else len(preferred))
    for item in ordered:
        move = _quote_move(item)
        ticker = _text(item.get("ticker")).upper()
        if move is None or ticker not in names:
            continue
        freshness = _text(item.get("freshness") or item.get("data_status")).casefold()
        prefix = "最近收盤" if freshness in {"recent_close", "stale", "delayed"} else ""
        parts.append(f"{prefix}{names[ticker]}{move:+.2f}%")
    return "、".join(parts[:3]) or "目前缺乏可用行情證據"


def _market_driver(
    slot: str, quotes: list[dict[str, Any]], themes: list[dict[str, Any]],
    group_tickers: dict[str, list[str]],
) -> tuple[str, str | None]:
    """Select one conclusion-compatible driver; news is only a named cause when confirmed."""
    by_ticker = {_text(item.get("ticker")).upper(): item for item in quotes}

    def average(tickers: tuple[str, ...]) -> float | None:
        values: list[float] = [
            value
            for ticker in tickers
            if ticker in by_ticker
            for value in [_quote_move(by_ticker[ticker])]
            if isinstance(value, (int, float))
        ]
        return sum(values) / len(values) if values else None

    taiwan = average(("TAIEX", "TXF", "TPEX", "2330"))
    tech = average(("SOX", "NASDAQ", "NQ"))
    broad = average(("S&P 500", "DJIA", "ES", "YM"))
    if slot in {"pre_open", "intraday", "midday", "afternoon", "post_close"}:
        if taiwan is not None and tech is not None and taiwan > 0.25 and tech > 0.25:
            return "台股與半導體同步偏強", None
        if taiwan is not None and taiwan > 0.25:
            return "台股核心指數偏強", None
        if taiwan is not None and taiwan < -0.25:
            return "台股核心指數偏弱", None
    else:
        if tech is not None and broad is not None and tech > 0.25 and broad > 0.25:
            return "美股科技與大盤同步偏強", None
        if tech is not None and tech > 0.25:
            return "美股科技股偏強", None
        if tech is not None and tech < -0.25:
            return "美股科技股偏弱", None
        if broad is not None and broad < -0.25:
            return "美股大盤偏弱", None

    for theme in themes:
        # The quote theme is already represented by the measured driver
        # above.  It has a hydration-dependent key and must never become an
        # event identity in a decision fingerprint.
        if str(theme.get("title") or "") == "市場價格":
            continue
        if theme.get("quote_evidence") and theme.get("source_evidence") and theme.get("normalization_complete"):
            return _topic_driver(theme), str(theme.get("canonical_event_key") or theme.get("event_key") or "") or None
    return "市場焦點待價格確認", None


def build_market_assessment(
    *,
    slot: str,
    as_of: datetime,
    quotes: list[dict[str, Any]],
    themes: list[dict[str, Any]],
    intelligence: dict[str, Any] | None = None,
    market_status: dict[str, Any] | None = None,
    risk: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a five-level stance with explicit evidence sufficiency."""
    factors, dimensions, directional, group_tickers, quote_tickers = _quote_factors(quotes, slot=slot)
    score = sum(factors.values())
    # Conflict is local to a comparable evidence group.  A rising Taiwan
    # market alongside a softer Nasdaq is a cross-market relationship to
    # explain, not proof that Taiwan's own stance is automatically divergent.
    group_signs: dict[str, set[int]] = {}
    for group, tickers in group_tickers.items():
        values = []
        by_ticker = {_text(item.get("ticker")).upper(): _quote_move(item) for item in quotes}
        for ticker in tickers:
            move = by_ticker.get(ticker)
            if move is not None and abs(move) >= (0.75 if group == "commodities" else 0.25):
                values.append(1 if move > 0 else -1)
        group_signs[group] = set(values)
    if slot in {"pre_open", "intraday", "midday", "afternoon", "post_close"}:
        # A softer Nasdaq against a stronger Taiwan/semiconductor session is
        # a cross-market relationship to explain, not a Taiwan-core conflict.
        relevant_groups = {"taiwan_core"}
    elif slot in {"us_premarket", "us_open"}:
        relevant_groups = {"us_tech", "us_broad", "us_futures"}
    else:
        relevant_groups = set(group_signs)
    conflict_groups = [
        group for group, signs in group_signs.items()
        if group in relevant_groups and len(signs) > 1
    ]
    conflict = bool(conflict_groups)
    factor_source = "quote_factors"
    if isinstance(intelligence, dict):
        regime = intelligence.get("market_regime")
        if isinstance(regime, dict) and isinstance(regime.get("score"), (int, float)):
            # Use the regime only as an additional bounded factor when its
            # contract is present.  Never combine its score with a different
            # conflict model.
            supplied_score = max(-2.0, min(2.0, float(regime["score"])))
            score = round((score + supplied_score) / 2, 3)
            factor_source = "quote_factors+market_regime"
            conflict = conflict or bool(regime.get("conflict_flags"))
    factor_count = sum(
        1 for item in quotes
        if _quote_move(item) is not None and _text(item.get("ticker")).upper() in set(quote_tickers)
    )
    # A previously stored assessment is presentation state, not fresh
    # evidence. Recompute the stance from the same quote/regime inputs for
    # every release so an old label cannot override current market facts.
    stance, stance_label, confidence = _stance(score, factor_count, dimensions, conflict)
    taipei = as_of.astimezone(timezone(timedelta(hours=8)))
    weekend = taipei.weekday() >= 5
    taiwan_slot = slot in {"pre_open", "intraday", "midday", "afternoon", "post_close"}
    taiwan_status = market_status.get("taiwan") if isinstance(market_status, dict) else None
    us_status = market_status.get("us") if isinstance(market_status, dict) else None
    taiwan_closed = isinstance(taiwan_status, dict) and taiwan_status.get("is_trading_day") is False
    us_closed = isinstance(us_status, dict) and us_status.get("is_trading_day") is False
    if taiwan_slot:
        market_scope = "台股"
    elif slot in {"us_premarket", "us_open"}:
        market_scope = "美股"
    else:
        market_scope = "台美市場"
    if (weekend or taiwan_closed) and slot != "us_premarket":
        market_summary = "台股休市，以下為最近可核對資料"
    elif (us_closed or (weekend and slot == "us_premarket")) and slot == "us_premarket":
        market_summary = "美股休市、使用最近收盤資料"
    else:
        market_summary = f"{market_scope}{stance_label}"
    driver, dominant_key = _market_driver(slot, quotes, themes, group_tickers)
    highlights = _quote_highlights(quotes, slot)
    if conflict:
        risk_summary = "核心證據方向有衝突，等待下一次收盤或官方資料核對。"
    elif confidence == "low":
        risk_summary = "有效因子不足，暫不把新聞或單一行情視為方向確認。"
    else:
        risk_summary = "留意利率、美元與能源變化是否改變目前市場傳導。"
    quote_driven = driver in {
        "台股與半導體同步偏強", "台股核心指數偏強", "台股核心指數偏弱",
        "美股科技與大盤同步偏強", "美股科技股偏弱", "美股大盤偏弱",
    }
    if dominant_key is None and themes and not quote_driven:
        risk_summary = f"{driver}，仍待價格確認。"
    return {
        "stance": stance,
        "stance_label": stance_label,
        "confidence": confidence,
        "market_scope": market_scope,
        "dominant_driver": driver,
        "dominant_driver_key": dominant_key,
        # Market-price themes are hydrated on every release and therefore do
        # not have a stable event identity.  Only real event themes belong in
        # the assessment's supporting identity set.
        "supporting_theme_keys": [
            str(theme.get("canonical_event_key") or theme.get("event_key"))
            for theme in themes
            if str(theme.get("title") or "") != "市場價格"
            and (theme.get("canonical_event_key") or theme.get("event_key"))
        ],
        "conflict_flags": ["directional_quote_conflict", *[f"group:{group}" for group in conflict_groups]] if conflict else [],
        "summary_sections": {
            "summary": market_summary,
            "market_highlights": highlights,
            "risk": risk_summary,
        },
        "joint_market_signal": build_joint_market_signal(quotes, risk),
        "evidence_as_of": as_of.isoformat(),
        "factor_count": factor_count,
        "evidence_dimensions": sorted(dimensions),
        "evidence_groups": {key: sorted(signs) for key, signs in group_signs.items() if signs},
        "score": round(score, 3),
        "factor_source": factor_source,
        "weekend_market": weekend and taiwan_slot,
        "directional_quote_count": len(directional),
    }


def _overview_clause(value: Any) -> str:
    return _text(value).rstrip("。！？.!?；;，,")


def project_overview(assessment: dict[str, Any], limit: int = 140) -> str:
    raw_sections = assessment.get("summary_sections")
    sections: dict[str, Any] = raw_sections if isinstance(raw_sections, dict) else {}
    summary = _overview_clause(sections.get("summary"))
    highlights = _overview_clause(sections.get("market_highlights"))
    risk = _overview_clause(sections.get("risk"))
    if not summary or not highlights or not risk:
        return ""
    candidates = [
        f"總結｜{summary}。行情重點｜{highlights}。風險｜{risk}。",
        f"總結｜{summary}。行情重點｜{highlights}。風險｜待後續核對。",
        f"總結｜{summary}。行情重點｜{highlights}。風險｜留意市場變化。",
        f"總結｜{summary}。行情重點｜市場資料已整理。風險｜待後續核對。",
    ]
    return next((item for item in candidates if len(item) <= limit), "")


def project_public_message(label: str, assessment: dict[str, Any], limit: int = 60) -> str:
    """Render the shared scheduled-report summary from bounded market facts.

    The conclusion and the strongest available quote are separate structured
    inputs.  Keeping the quote as evidence (rather than a generic driver
    label) makes the notification useful at a glance while the shared
    formatter remains the only final 60-character boundary.
    """
    raw_sections = assessment.get("summary_sections")
    sections: dict[str, Any] = raw_sections if isinstance(raw_sections, dict) else {}
    conclusion = _overview_clause(sections.get("summary"))
    highlights = _overview_clause(sections.get("market_highlights"))
    strongest_quote = next(
        (part.strip() for part in re.split(r"[、,，]", highlights) if part.strip()),
        "",
    )
    driver = _overview_clause(assessment.get("dominant_driver"))
    from src.telegram_client import canonical_short_message, is_valid_public_summary

    for body in (
        f"{conclusion}；{strongest_quote}。" if strongest_quote and "目前缺乏" not in strongest_quote else "",
        f"{conclusion}；{driver}。" if driver else "",
        f"{conclusion}。",
    ):
        if not body:
            continue
        result = canonical_short_message(
            f"{label}｜{body}",
            limit=limit,
            message_kind="scheduled_brief",
            label=label,
        )
        if is_valid_public_summary(result, source="scheduled_brief"):
            return result
    return ""
