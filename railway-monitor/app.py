"""Railway bridge: Jin10 MCP Flash -> signed GitHub repository_dispatch.

The service intentionally performs no scraping.  It calls Jin10's official MCP
``list_flash`` tool, records seen IDs locally, and only forwards in-scope events.
GitHub independently verifies the HMAC signature and de-duplicates the event.
"""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
import threading
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunsplit

import httpx

# Railway is currently configured with ``/railway-monitor`` as its root
# directory.  In that layout the repository-level ``src`` package is not
# copied into the image, so importing the shared classifier would crash the
# process before the health server starts.  Prefer the shared implementation
# when the service is deployed from the repository root, but keep a small,
# auditable compatibility implementation for the standalone service image.
_RUNTIME_ACTIVE_BLACK_SWAN_CONTEXT_TERMS = (
    "war begins", "war began", "war breaks out", "war erupted",
    "military escalation", "armed conflict", "airstrike", "missile attack",
    "invasion", "attack", "strike", "escalation", "major disaster",
)
_USING_STANDALONE_CLASSIFIER = False

try:
    from src.event_classifier import classify_event_fields, has_active_black_swan_context
except ModuleNotFoundError as error:
    if error.name not in {"src", "src.event_classifier"}:
        raise
    _USING_STANDALONE_CLASSIFIER = True

    def _runtime_haystack(record: Any) -> str:
        values: list[str] = []

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                for child in value.values():
                    visit(child)
            elif isinstance(value, (list, tuple, set)):
                for child in value:
                    visit(child)
            elif isinstance(value, (str, int, float)):
                values.append(str(value))

        visit(record)
        return normalized_event_text(" ".join(values))

    def _runtime_hit(terms: Iterable[str], haystack: str) -> str:
        # ``_keyword_hit`` is defined below the compatibility block and is
        # therefore resolved when the monitor actually classifies an item.
        return str(_keyword_hit(tuple(terms), haystack) or "")

    def has_active_black_swan_context(haystack: str) -> bool:
        normalized = normalized_event_text(haystack)
        for term in _RUNTIME_ACTIVE_BLACK_SWAN_CONTEXT_TERMS:
            candidate = normalized_event_text(term)
            start = 0
            while candidate:
                index = normalized.find(candidate, start)
                if index < 0:
                    break
                prefix = normalized[max(0, index - 36):index]
                if not re.search(r"\b(?:since|after|before|not|no|without|historical|former)\b", prefix):
                    return True
                start = index + len(candidate)
        return False

    def classify_event_fields(record: dict[str, Any] | str) -> dict[str, Any]:
        haystack = _runtime_haystack(record)
        positive = _runtime_hit(MATERIAL_POSITIVE_TERMS, haystack)
        if positive:
            return {"category": "material_positive", "reason": "material_positive_keyword", "matched_terms": [positive], "text": haystack}
        energy = _runtime_hit(CATEGORY_KEYWORDS.get("energy", ()), haystack)
        context = _runtime_hit(ENERGY_CONTEXT_TERMS, haystack)
        production = _runtime_hit(ENERGY_PRODUCTION_TERMS, haystack)
        if energy and context and production and not has_active_black_swan_context(haystack):
            return {"category": "energy", "reason": "energy_material_keyword", "matched_terms": [energy, context], "text": haystack}
        black = _runtime_hit(BLACK_SWAN_TERMS, haystack)
        if black:
            return {"category": "black_swan", "reason": "black_swan_keyword", "matched_terms": [black], "text": haystack}
        trump = KEYWORD_DATABASE.get("trump") or {}
        entity = _runtime_hit(tuple(trump.get("entities", ())), haystack)
        action = _runtime_hit(tuple(trump.get("policy_actions", ())), haystack)
        taco = _runtime_hit(tuple(trump.get("taco", ())), haystack)
        if taco:
            return {"category": "policy", "reason": "trump_taco_keyword", "matched_terms": [taco], "text": haystack}
        if entity and action:
            return {"category": "policy", "reason": "trump_policy_keyword", "matched_terms": [action], "text": haystack}
        for category in ("conflict", "policy", "fed", "macro", "semiconductor", "market", "energy"):
            hit = _runtime_hit(CATEGORY_KEYWORDS.get(category, ()), haystack)
            if hit:
                if category == "energy" and not context:
                    return {"category": None, "reason": "energy_requires_material_context", "matched_terms": [hit], "text": haystack}
                return {"category": category, "reason": f"{category}_keyword", "matched_terms": [hit], "text": haystack}
        return {"category": None, "reason": "keyword_no_match", "matched_terms": [], "text": haystack}


JIN10_MCP_URL = "https://mcp.jin10.com/mcp"
GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
DEFAULT_GDELT_QUERY = '(war OR invasion OR ceasefire OR sanctions OR Hormuz OR tariff OR "export controls" OR semiconductor OR earthquake OR tsunami OR cyberattack OR ransomware OR pandemic OR Bitcoin OR Ethereum OR Trump OR "cancel attack" OR "call off attack" OR Iran OR "White House")'
GDELT_QUERY = DEFAULT_GDELT_QUERY
GITHUB_API_VERSION = "2022-11-28"
EVENT_COOLDOWN_SECONDS = 30 * 60
ALLOWED_CATEGORIES = {"fed", "macro", "policy", "conflict", "energy", "semiconductor", "market", "black_swan", "material_positive"}
CATEGORY_LABELS = {
    "black_swan": "黑天鵝",
    "material_positive": "重大正向",
    "fed": "Fed",
    "macro": "宏觀",
    "policy": "政策",
    "conflict": "地緣",
    "energy": "能源",
    "semiconductor": "半導體",
    "market": "市場",
}

def _load_keyword_database() -> dict[str, Any]:
    # The normal repository deployment reads the canonical database.  When
    # Railway's Root Directory is ``/railway-monitor``, the service image only
    # contains this folder, so also look for the bundled copy beside app.py.
    candidate_paths = (
        Path(__file__).resolve().parents[1] / "config" / "event_keywords.json",
        Path(__file__).resolve().with_name("event_keywords.json"),
    )
    last_error: Exception | None = None
    for path in candidate_paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("keyword database must be an object")
            logging.info("Loaded event keyword database from %s", path)
            return payload
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            last_error = error
    # A deployment mistake must not silently disable the monitor.  The
    # minimal fallback keeps the high-signal safety terms available while
    # the health log exposes the configuration problem.
    logging.error("event keyword database unavailable: %s", type(last_error).__name__ if last_error else "unknown")
    return {
            "categories": {"fed": ["fomc", "聯準會"], "macro": ["cpi", "非農"], "policy": ["tariff", "關稅"],
                           "conflict": ["war", "戰爭", "trump", "川普"], "energy": ["wti", "原油"],
                           "semiconductor": ["nvidia", "台積電"], "market": ["crash", "熔斷"]},
            "black_swan": ["war", "戰爭", "earthquake", "地震", "tsunami", "海嘯"],
            "material_positive": ["ceasefire", "停火", "rate cut", "降息"],
            "energy_context": ["supply", "供應", "opec", "attack", "攻擊", "%"],
            "escalation": ["escalation", "升級", "attack", "攻擊"],
            "trump": {
                "entities": ["donald trump", "president trump", "trump", "川普", "特朗普", "白宮", "白宫"],
                "taco": ["taco", "taco trade", "trump always chickens out", "川普taco", "特朗普taco"],
                "policy_actions": ["tariff", "tariffs", "關稅", "关税", "sanction", "制裁", "export control", "出口管制"],
                "deescalation_actions": ["backs down", "walks back", "tariff pause", "tariff delay", "暫緩關稅", "暂缓关税", "反悔", "退縮", "退缩"],
            },
            "iran_gulf_context": {
                "anchors": ["iran", "iranian", "gulf", "hormuz", "伊朗", "海灣", "海湾", "荷姆茲海峽", "霍尔木兹海峡"],
                "actions": ["geopolitical", "tension", "conflict", "escalation", "attack", "ceasefire", "supply disruption", "shipping", "negotiation", "negotiations", "deadline", "agreement", "failed talks", "talks collapse", "地緣", "地缘", "緊張", "紧张", "衝突", "冲突", "供應中斷", "供应中断", "航運", "航运", "談判", "谈判", "協議", "协议", "未談妥", "未谈妥", "談判破裂", "谈判破裂", "最後期限", "最后期限"],
                "high_signal_actions": ["geopolitical", "conflict", "escalation", "attack", "supply disruption", "shipping", "negotiation", "negotiations", "deadline", "failed talks", "talks collapse", "地緣", "地缘", "衝突", "冲突", "升級", "升级", "供應中斷", "供应中断", "航運", "航运", "談判破裂", "谈判破裂", "未談妥", "未谈妥", "最後期限", "最后期限"],
                "regional_anchors": ["persian gulf", "gulf", "hormuz", "波斯灣", "波斯湾", "海灣", "海湾", "荷姆茲海峽", "霍尔木兹海峡"],
                "market_context": ["oil", "wti", "brent", "shipping", "usd", "treasury", "原油", "油價", "航運", "美元", "美債", "股市", "市场"],
            },
            "gdelt": {"query": "(war OR ceasefire OR tariff OR earthquake OR semiconductor OR 戰爭 OR 停火 OR 關稅 OR 地震 OR 半導體)", "entities": [], "actions": {}}
        }


KEYWORD_DATABASE = _load_keyword_database()
CATEGORY_KEYWORDS = {key: tuple(values) for key, values in KEYWORD_DATABASE.get("categories", {}).items()}
BLACK_SWAN_TERMS = tuple(KEYWORD_DATABASE.get("black_swan", ()))
MATERIAL_POSITIVE_TERMS = tuple(KEYWORD_DATABASE.get("material_positive", ()))
ENERGY_CONTEXT_TERMS = tuple(KEYWORD_DATABASE.get("energy_context", ()))
ENERGY_PRODUCTION_TERMS = (
    "oil production", "crude production", "oil output", "production increase",
    "output increase", "output cut", "production cut", "石油產量", "石油产量", "原油產量", "原油产量",
    "產油量", "产油量", "增產", "增产", "減產", "减产", "提高產量", "提高产量",
)
ESCALATION_TERMS = tuple(KEYWORD_DATABASE.get("escalation", ()))
TRUMP_RULES = KEYWORD_DATABASE.get("trump") or {}
TRUMP_ENTITY_TERMS = tuple(TRUMP_RULES.get("entities", ()))
TRUMP_POLICY_ACTION_TERMS = tuple(TRUMP_RULES.get("policy_actions", ()))
TRUMP_TACO_TERMS = tuple(TRUMP_RULES.get("taco", ()))
TRUMP_DEESCALATION_TERMS = tuple(TRUMP_RULES.get("deescalation_actions", ()))
IRAN_GULF_RULES = KEYWORD_DATABASE.get("iran_gulf_context") or {}
IRAN_GULF_ANCHOR_TERMS = tuple(IRAN_GULF_RULES.get("anchors", ()))
IRAN_GULF_ACTION_TERMS = tuple(IRAN_GULF_RULES.get("actions", ()))
IRAN_GULF_HIGH_SIGNAL_ACTION_TERMS = tuple(IRAN_GULF_RULES.get("high_signal_actions", ()))
IRAN_GULF_REGIONAL_ANCHOR_TERMS = tuple(IRAN_GULF_RULES.get("regional_anchors", ()))
IRAN_GULF_MARKET_TERMS = tuple(IRAN_GULF_RULES.get("market_context", ()))
GDELT_QUERY = str((KEYWORD_DATABASE.get("gdelt") or {}).get("query") or DEFAULT_GDELT_QUERY)
# GDELT is a discovery feed rather than an authority. Keep the configured
# query, but explicitly include Gulf oil-production wording so a headline
# such as "Kuwait output reaches a high since the war began" is discoverable.
GDELT_QUERY = (
    f"({GDELT_QUERY} OR Kuwait OR Kuwaiti OR \"oil production\" OR "
    f"\"crude production\" OR \"oil output\" OR OPEC OR "
    "科威特 OR 科威特國 OR 科威特国 OR 石油產量 OR 石油产量 OR 原油產量 OR 原油产量)"
)

# A discovery item is never sufficient on its own. GDELT candidates must have
# two independent domains from this conservative set and share a concrete
# event anchor before they can reach the signed GitHub dispatch bridge.
TRUSTED_NEWS_DOMAINS = {
    "reuters.com", "apnews.com", "bloomberg.com", "ft.com", "wsj.com",
    "nytimes.com", "bbc.com", "cnbc.com", "nikkei.com",
}
DISCOVERY_ANCHORS = {
    "energy": ("wti", "brent", "crude oil", "oil", "oil supply", "oil production", "crude production", "oil output", "opec", "production", "output", "kuwait", "kuwaiti", "gulf", "middle east", "原油", "石油", "石油產量", "石油产量", "原油產量", "原油产量", "產量", "产量", "科威特", "科威特國", "科威特国", "海灣", "海湾"),
    "conflict": ("iran", "israel", "ukraine", "russia", "hormuz", "persian gulf", "gulf", "taiwan", "伊朗", "以色列", "波斯灣", "波斯湾", "海灣", "海湾", "荷姆茲海峽", "霍尔木兹海峡", "烏克蘭", "乌克兰", "俄羅斯", "俄罗斯", "台灣", "台湾"),
    "policy": ("tariff", "sanction", "export control", "duties", "taco", "trump always chickens out", "backs down", "walks back", "tariff pause", "tariff delay", "關稅", "关税", "制裁", "出口管制", "暫緩關稅", "暂缓关税", "延後關稅", "延后关税"),
    # De-escalation headlines (for example, a president cancelling a planned
    # strike) are material-positive events, not ordinary conflict coverage.
    # Keep actor/place anchors so GDELT can cross-check them across two trusted
    # domains instead of silently dropping the cluster.
    "material_positive": ("iran", "israel", "ukraine", "russia", "trump", "ceasefire", "truce", "peace deal", "伊朗", "以色列", "烏克蘭", "乌克兰", "俄羅斯", "俄罗斯", "川普", "特朗普", "停火", "和平協議", "和平协议"),
    "fed": ("federal reserve", "fed", "powell", "bessent", "scott bessent", "boj", "bank of japan", "聯準會", "联准会", "美聯儲", "美联储", "貝森特", "贝森特", "日本央行", "日本銀行", "日本银行"),
    "macro": ("yen", "japanese yen", "currency intervention", "fx intervention", "intervention", "japan", "日圓", "日元", "匯率干預", "汇率干预", "外匯干預", "外汇干预", "聯合干預", "联合干预"),
    "energy": ("wti", "brent", "oil", "opec", "crude", "原油", "石油", "能源"),
    "semiconductor": ("nvidia", "tsmc", "asml", "semiconductor", "輝達", "英伟达", "台積電", "台积电", "半導體", "半导体"),
    "black_swan": ("earthquake", "tsunami", "ransomware", "cyberattack", "pandemic", "war", "invasion", "airstrike", "missile", "escalation", "military escalation", "重大地震", "地震", "海嘯", "海啸", "戰爭", "战争", "入侵", "空襲", "空袭", "重大攻擊", "重大攻击", "軍事升級", "军事升级", "戰事升級", "战事升级"),
    "material_positive": ("iran", "israel", "ukraine", "russia", "trump", "ceasefire", "truce", "peace deal", "tariff exemption", "rate cut", "cancel attack", "call off attack", "trade war easing", "trade war de-escalation", "trade war deescalation", "de-escalation", "deescalation", "peace optimism", "peace hopes", "global relief rally", "geopolitical tensions ease", "伊朗", "以色列", "川普", "特朗普", "停火", "和平協議", "和平协议", "降息", "貿易戰緩和", "贸易战缓和", "貿易戰降溫", "贸易战降温", "緊張局勢緩和", "紧张局势缓和", "和平希望", "全球風險偏好改善", "全球风险偏好改善", "地緣緊張緩和", "地缘紧张缓和"),
}

# GDELT is only a discovery feed.  Two headlines must describe the same
# actor/place and the same action, rather than merely repeat a broad topic.
# The small vocabulary is deliberately conservative: a missed headline is
# preferable to publishing a misleading same-topic alert.
_GDELT_KEYWORDS = KEYWORD_DATABASE.get("gdelt") or {}
DISCOVERY_ENTITIES = tuple(_GDELT_KEYWORDS.get("entities") or (
    "iran", "israel", "ukraine", "russia", "taiwan", "japan", "china", "hormuz",
    "trump", "powell", "netanyahu", "putin", "zelenskyy", "nvidia", "tsmc", "asml",
))
DISCOVERY_ENTITY_ANCHORS = {
    "nvidia", "tsmc", "asml", "bessent", "scott bessent", "federal reserve", "fed", "boj",
    "bank of japan", "yen", "japan", "聯準會", "联准会", "貝森特", "贝森特", "日圓", "日元",
}
DISCOVERY_ALIAS_GROUPS = {
    # Gulf states are one event-region for cross-source matching; the action
    # intersection still prevents unrelated Gulf headlines from merging.
    "gulf_region": ("persian gulf", "gulf states", "gulf", "hormuz", "kuwait", "kuwaiti", "bahrain", "qatar", "saudi arabia", "uae", "united arab emirates", "oman", "波斯灣", "波斯湾", "海灣", "海湾", "海灣國家", "海湾国家", "科威特", "科威特國", "科威特国", "巴林", "卡達", "卡达", "沙烏地阿拉伯", "沙特阿拉伯", "阿聯酋", "阿联酋", "阿曼", "荷姆茲海峽", "霍尔木兹海峡"),
    "fed": ("federal reserve", "fed", "聯準會", "联准会", "美聯儲", "美联储"),
    "bessent": ("bessent", "scott bessent", "貝森特", "贝森特"),
    "boj": ("boj", "bank of japan", "日本央行", "日本銀行", "日本银行"),
    "yen": ("yen", "japanese yen", "日圓", "日元"),
    "japan": ("japan", "日本"),
    "black_swan_conflict": ("war", "invasion", "airstrike", "missile", "attack", "strike", "escalation", "military escalation", "armed conflict", "戰爭", "战争", "入侵", "空襲", "空袭", "攻擊", "攻击", "襲擊", "袭击", "軍事升級", "军事升级", "戰事升級", "战事升级"),
    "positive_deescalation": ("trade war easing", "trade war de-escalation", "trade war deescalation", "de-escalation", "deescalation", "peace optimism", "peace hopes", "global relief rally", "geopolitical tensions ease", "cancel planned attack", "cancel planned attacks", "canceled planned attack", "canceled planned attacks", "cancelled planned attack", "cancelled planned attacks", "cancel iran strike", "cancel iran strikes", "canceled strikes on iran", "cancelled strikes on iran", "call off planned attacks", "call off planned strike", "call off planned strikes", "calls off planned strikes", "called off planned strikes", "halt military strikes on iran", "取消對伊朗的攻擊", "取消对伊朗的攻击", "取消對伊朗的襲擊", "取消对伊朗的袭击", "取消對伊朗的攻擊計畫", "取消对伊朗的攻击计划", "取消對伊朗的襲擊計畫", "取消对伊朗的袭击计划", "貿易戰緩和", "贸易战缓和", "貿易戰降溫", "贸易战降温", "緊張局勢緩和", "紧张局势缓和", "和平樂觀", "和平乐观", "和平希望", "全球風險偏好改善", "全球风险偏好改善", "地緣緊張緩和", "地缘紧张缓和", "撤回對伊朗的襲擊計畫", "撤回对伊朗的袭击计划"),
}
DISCOVERY_ACTION_ALIAS_GROUPS = {
    # Negotiation verbs are one semantic action across English, Traditional
    # Chinese and Simplified Chinese. GDELT often paraphrases one event as
    # talks, dialogue or negotiations; canonicalising them keeps the second
    # source/entity/action gate from silently rejecting a valid match.
    "negotiation": (
        "talk", "talks", "talking", "in talks", "peace talks", "ceasefire talks",
        "diplomatic talks", "dialogue", "dialog", "negotiating", "negotiation",
        "negotiations", "會談", "談判", "協商", "對話", "和談",
        "会谈", "谈判", "协商", "对话", "和谈",
    ),
    # Pressure/coercion language is a common Reuters Chinese and GDELT
    # paraphrase of the same Iran/US geopolitical action.
    "coercive_pressure": (
        "pressure", "pressures", "pressured", "ramp up pressure",
        "ramping up pressure", "increase pressure", "increased pressure",
        "mount pressure", "force concessions", "forcing concessions",
        "seek concessions", "demand concessions", "coercion", "coerce",
        "coercive pressure", "maximum pressure", "施壓", "施压",
        "加大施壓", "加大施压", "擴大施壓", "扩大施压", "施壓加劇",
        "施压加剧", "加大壓力", "加大压力", "擴大壓力", "扩大压力",
        "迫使讓步", "迫使让步", "逼迫讓步", "逼迫让步", "迫使美國讓步",
        "迫使美国让步", "要求讓步", "要求让步", "脅迫", "胁迫",
        "強硬施壓", "强硬施压",
    ),
    "fed_support": ("federal reserve support", "fed support", "urges the fed", "敦促聯準會", "敦促联准会"),
    "currency_intervention": ("currency intervention", "fx intervention", "joint yen intervention", "coordinated currency intervention", "匯率干預", "汇率干预", "外匯干預", "外汇干预", "聯合干預", "联合干预"),
    "black_swan_conflict": ("war", "invasion", "airstrike", "missile", "missile attack", "attack", "strike", "escalation", "military escalation", "armed conflict", "戰爭", "战争", "入侵", "空襲", "空袭", "攻擊", "攻击", "襲擊", "袭击", "軍事升級", "军事升级", "戰事升級", "战事升级"),
    "positive_deescalation": ("trade war easing", "trade war de-escalation", "trade war deescalation", "de-escalation", "deescalation", "peace optimism", "peace hopes", "global relief rally", "geopolitical tensions ease", "cancel planned attack", "cancel planned attacks", "canceled planned attack", "canceled planned attacks", "cancelled planned attack", "cancelled planned attacks", "cancel iran strike", "cancel iran strikes", "canceled strikes on iran", "cancelled strikes on iran", "call off planned attacks", "call off planned strike", "call off planned strikes", "calls off planned strikes", "called off planned strikes", "halt military strikes on iran", "取消對伊朗的攻擊", "取消对伊朗的攻击", "取消對伊朗的襲擊", "取消对伊朗的袭击", "取消對伊朗的攻擊計畫", "取消对伊朗的攻击计划", "取消對伊朗的襲擊計畫", "取消对伊朗的袭击计划", "貿易戰緩和", "贸易战缓和", "貿易戰降溫", "贸易战降温", "緊張局勢緩和", "紧张局势缓和", "和平樂觀", "和平乐观", "和平希望", "全球風險偏好改善", "全球风险偏好改善", "地緣緊張緩和", "地缘紧张缓和", "撤回對伊朗的襲擊計畫", "撤回对伊朗的袭击计划"),
}
DISCOVERY_ACTIONS = {
    key: tuple(values) for key, values in (_GDELT_KEYWORDS.get("actions") or {}).items()
}
ENERGY_DISCOVERY_ACTIONS = (
    "oil supply", "oil production", "crude production", "oil output",
    "production", "output", "production increase", "production cut",
    "opec", "supply disruption", "石油供應", "石油供应", "石油產量", "石油产量",
    "原油產量", "原油产量", "產油量", "产油量", "增產", "增产", "減產", "减产",
    "提高產量", "提高产量",
)
DISCOVERY_ACTION_ALIAS_GROUPS["energy_supply"] = ENERGY_DISCOVERY_ACTIONS
# Keep the runtime vocabulary resilient when an older keyword database is
# deployed. This is additive and does not weaken the two-source gate.
DISCOVERY_ENTITIES = tuple(dict.fromkeys((*DISCOVERY_ENTITIES, "kuwait", "kuwaiti", "bahrain", "qatar", "saudi arabia", "uae", "oman", "科威特", "科威特國", "科威特国")))
DISCOVERY_ACTIONS["energy"] = tuple(dict.fromkeys((*DISCOVERY_ACTIONS.get("energy", ()), *ENERGY_DISCOVERY_ACTIONS)))

# Public, non-secret runtime diagnostics for Railway's /health endpoint.  This
# deliberately contains timestamps, counts and error classes only; credentials
# and response bodies never enter the health payload.
HEALTH_LOCK = threading.Lock()
HEALTH_STATE: dict[str, Any] = {
    "status": "ok",
    "service": "prstk-jin10-monitor",
    "started_at": datetime.now(timezone.utc).isoformat(),
    "jin10": {"status": "not_checked", "last_success_at": None, "last_failure_at": None, "item_count": 0, "error": None},
    "gdelt": {"enabled": True, "status": "not_checked", "last_success_at": None, "last_failure_at": None, "article_count": 0, "alert_count": 0, "pending_count": 0, "pending_reasons": {}, "error": None},
    "classification": {
        "status": "not_checked",
        "updated_at": None,
        "classification_counts": {},
        "unclassified_count": 0,
        "reason_counts": {},
    },
    "delivery": {
        "status": "not_checked",
        "last_trace_id": None,
        "last_outbox_status": None,
        "last_receipt_status": None,
        "counts": {},
        "last_updated_at": None,
        "last_error": None,
    },
}
DELIVERY_STORE: SeenStore | None = None


def update_health(component: str, **values: Any) -> None:
    with HEALTH_LOCK:
        HEALTH_STATE.setdefault(component, {}).update(values)


def health_snapshot() -> dict[str, Any]:
    with HEALTH_LOCK:
        return json.loads(json.dumps(HEALTH_STATE))


@dataclass(frozen=True)
class Flash:
    event_id: str
    title: str
    content: str
    occurred_at: str

    @property
    def text(self) -> str:
        return " ".join(part for part in (self.title, self.content) if part).strip()


@dataclass(frozen=True)
class Alert:
    event_id: str
    category: str
    summary: str
    occurred_at: str
    source: str = "jin10"
    evidence: tuple[DiscoveryArticle, ...] = ()
    # Discovery alerts are deliberately warning-level until a first-party
    # source confirms the facts.  The two booleans are carried through the
    # signed repository-dispatch payload so the GitHub workflow cannot
    # accidentally promote an unverified headline to high risk.
    risk_level: str = "警戒"
    official_confirmed: bool = False
    market_sync_confirmed: bool = False
    market_sync: tuple[str, ...] = ()

    @property
    def evidence_payload(self) -> list[dict[str, str]]:
        return [
            {"domain": item.domain, "url": item.url, "seen_at": item.seen_at}
            for item in sorted(self.evidence, key=lambda item: (item.domain, item.url, item.seen_at))
        ]

    @property
    def canonical(self) -> str:
        trace = json.dumps(self.evidence_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        confirmation = json.dumps({
            "risk_level": self.risk_level,
            "official_confirmed": self.official_confirmed,
            "market_sync_confirmed": self.market_sync_confirmed,
            "market_sync": list(self.market_sync),
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return "\n".join((self.source, self.event_id, self.category, self.summary, self.occurred_at, trace, confirmation))


def alert_trace_id(alert: Alert) -> str:
    """Stable correlation ID shared by Railway, GitHub Actions and logs."""
    return f"prstk-{alert.source}-{alert_canonical_key(alert)[:20]}"


def normalize_source_url(value: str) -> str:
    """Keep a stable URL identity while dropping analytics parameters."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if not host:
        return ""
    path = (parsed.path or "/").rstrip("/") or "/"
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
             if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid", "ref"}]
    return urlunsplit((parsed.scheme.lower() or "https", host, path, urlencode(sorted(query)), ""))


def alert_fact_fingerprints(text: str) -> dict[str, str]:
    """Hash only public event anchors so syndicated headlines converge safely."""
    value = str(text or "").casefold()
    vocab = {
        "person": ("trump", "powell", "netanyahu", "putin", "zelensky", "台積電", "nvidia"),
        "location": ("iran", "israel", "ukraine", "russia", "hormuz", "taiwan", "japan", "china", "日本", "台灣"),
        "action": ("attack", "airstrike", "war", "ceasefire", "truce", "tariff", "sanction", "earthquake", "tsunami", "ransomware", "停火", "關稅", "供應中斷"),
    }
    result: dict[str, str] = {}
    for kind, terms in vocab.items():
        hits = sorted({term for term in terms if term.casefold() in value})
        result[kind] = hashlib.sha256("|".join(hits).encode("utf-8")).hexdigest()[:16] if hits else ""
    return result


def alert_canonical_key(alert: Alert) -> str:
    """Canonical key independent of a provider's transient event id."""
    urls = [normalize_source_url(item.url) for item in alert.evidence if item.url]
    facts = alert_fact_fingerprints(alert.summary)
    identity = "|".join((alert.category, alert.risk_level, facts["person"], facts["location"], facts["action"], alert.occurred_at[:13]))
    # If a provider gives no concrete anchors, retain its normalized URL or
    # summary as a conservative fallback instead of merging unrelated items.
    material = identity if any(facts.values()) else "|".join((identity, alert.summary.casefold(), *sorted(urls)))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class DiscoveryArticle:
    title: str
    url: str
    domain: str
    seen_at: str
    snippet: str = ""


def configured(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required Railway variable: {name}")
    return value


def normalized_event_text(value: str) -> str:
    """Normalize multilingual headlines before keyword matching.

    NFKC folds full-width Latin/numeric characters into their ASCII forms,
    while casefold handles English casing.  Whitespace is normalized so that
    feeds using non-breaking or ideographic spaces do not silently miss a
    rule.  Punctuation is intentionally retained because phrases such as
    ``CPI/PCE`` remain useful evidence in the audit trail.
    """
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", " ", text).strip()


def _keyword_in_text(keyword: str, normalized: str, compact: str) -> bool:
    candidate = normalized_event_text(keyword)
    if not candidate:
        return False
    candidate_compact = candidate.replace(" ", "")
    # ASCII aliases must match token boundaries.  A raw substring check would
    # classify ``warning`` as ``war`` and ``escalation`` as ``deescalation``.
    # Both false positives split GDELT clusters or promote routine headlines.
    if all(ord(char) < 128 for char in candidate_compact):
        boundary = rf"(?<![a-z0-9]){re.escape(candidate)}(?![a-z0-9])"
        if re.search(boundary, normalized):
            return True
    elif candidate in normalized or candidate_compact in compact:
        return True

    # Fuzzy matching is deliberately bounded to a single token/phrase.  A
    # similarity check against the whole headline would turn unrelated words
    # into false alerts.  It catches harmless feed typos such as ``trunmp``
    # while exact multilingual aliases remain the primary path.
    if len(candidate_compact) < 3:
        return False
    if all(ord(char) < 128 for char in candidate_compact):
        words = re.findall(r"[a-z0-9]+(?:['-][a-z0-9]+)*", normalized)
        candidate_words = candidate.split()
        width = len(candidate_words)
        windows = (words if width == 1 else (" ".join(words[index:index + width]) for index in range(max(0, len(words) - width + 1))))
        return any(
            abs(len(candidate_compact) - len(window.replace(" ", ""))) <= 1
            and difflib.SequenceMatcher(None, candidate, window).ratio() >= 0.90
            for window in windows
        )
    # Chinese typo tolerance uses short character windows and a stricter
    # threshold; this avoids treating similar two-character finance terms as
    # interchangeable.
    window_size = len(candidate_compact)
    return any(
        abs(len(candidate_compact) - len(compact[index:index + window_size])) <= 1
        and difflib.SequenceMatcher(None, candidate_compact, compact[index:index + window_size]).ratio() >= 0.93
        for index in range(max(0, len(compact) - window_size + 1))
    )


def _keyword_hit(terms: Iterable[str], text: str) -> str:
    """Return the first matching alias, including bounded fuzzy matches."""
    normalized = normalized_event_text(text)
    compact = normalized.replace(" ", "")
    return next((keyword for keyword in terms if _keyword_in_text(keyword, normalized, compact)), "")


def classify_flash_with_reason(flash: Flash) -> tuple[str | None, str]:
    """Classify a flash and return an auditable reason for the decision."""
    haystack = normalized_event_text(flash.text)
    compact = haystack.replace(" ", "")
    # Trump-related tariff headlines need a dedicated rule path.  A bare
    # mention of Trump is intentionally not enough; require a policy action
    # or the TACO phrase so speeches and routine political coverage do not
    # become market alerts.  Explicit de-escalation is material-positive,
    # while the broader TACO/policy reversal remains a policy alert.
    has_trump = any(_keyword_in_text(term, haystack, compact) for term in TRUMP_ENTITY_TERMS)
    has_taco = any(_keyword_in_text(term, haystack, compact) for term in TRUMP_TACO_TERMS)
    has_trump_action = any(_keyword_in_text(term, haystack, compact) for term in TRUMP_POLICY_ACTION_TERMS)
    has_trump_deescalation = any(_keyword_in_text(term, haystack, compact) for term in TRUMP_DEESCALATION_TERMS)
    if has_taco:
        return "policy", "trump_taco_keyword"
    if has_trump and has_trump_deescalation:
        return "material_positive", "trump_deescalation_keyword"
    if has_trump and has_trump_action:
        return "policy", "trump_policy_keyword"
    # De-escalation has priority over the generic ``attack`` alias.  A
    # confirmed cancellation/ceasefire is material-positive, not a black-swan
    # escalation merely because the original conflict is mentioned.
    if any(_keyword_in_text(keyword, haystack, compact) for keyword in MATERIAL_POSITIVE_TERMS):
        return "material_positive", "material_positive_keyword"
    # A current oil-production/supply story that only refers to a historical
    # war must stay in the energy/news path. Without this branch, a generic
    # ``war`` alias wins first and the strict black-swan gate silently holds
    # the event even when the report is a real oil-market development.
    energy_keyword = _keyword_hit(CATEGORY_KEYWORDS.get("energy", ()), haystack)
    energy_context = _keyword_hit(ENERGY_CONTEXT_TERMS, haystack)
    energy_production = _keyword_hit(ENERGY_PRODUCTION_TERMS, haystack)
    if energy_keyword and energy_context and energy_production and not has_active_black_swan_context(haystack):
        return "energy", "energy_material_keyword"
    if any(_keyword_in_text(keyword, haystack, compact) for keyword in BLACK_SWAN_TERMS):
        return "black_swan", "black_swan_keyword"
    # Gulf/Iran headlines often lead with a regional-market move and put the
    # geopolitical reason in the body. Require an anchor plus an action, and
    # require either a concrete regional anchor (Gulf/Hormuz) or a high-signal
    # geopolitical/supply/shipping action. A bare "Gulf stocks rise" remains
    # outside the alert scope. Market context is retained for audit and can
    # strengthen the downstream official-price synchronization gate.
    iran_gulf_anchor = _keyword_hit(IRAN_GULF_ANCHOR_TERMS, haystack)
    iran_gulf_action = _keyword_hit(IRAN_GULF_ACTION_TERMS, haystack)
    iran_gulf_high_signal = _keyword_hit(IRAN_GULF_HIGH_SIGNAL_ACTION_TERMS, haystack)
    iran_gulf_region = _keyword_hit(IRAN_GULF_REGIONAL_ANCHOR_TERMS, haystack)
    iran_gulf_market = _keyword_hit(IRAN_GULF_MARKET_TERMS, haystack)
    if iran_gulf_anchor and iran_gulf_action and (iran_gulf_region or iran_gulf_high_signal):
        reason = "iran_gulf_context_market_keyword" if iran_gulf_market else "iran_gulf_context_keyword"
        return "conflict", reason
    # Oil headlines are material only when supply, a large move, or a
    # geopolitical catalyst is also present. This avoids routine daily oil
    # commentary becoming a Telegram emergency alert.
    energy_without_context = any(_keyword_in_text(keyword, haystack, compact) for keyword in CATEGORY_KEYWORDS["energy"])
    if energy_without_context:
        if any(_keyword_in_text(term, haystack, compact) for term in ENERGY_CONTEXT_TERMS):
            return "energy", "energy_material_keyword"
    for category, keywords in CATEGORY_KEYWORDS.items():
        if category == "energy":
            continue
        if any(_keyword_in_text(keyword, haystack, compact) for keyword in keywords):
            return category, f"{category}_keyword"
    # Use the same all-fields classifier as the scheduled news report as a
    # final fallback.  This keeps future aliases and description/summary
    # fields aligned without changing the conservative legacy paths above.
    shared = classify_event_fields({"title": flash.title, "content": flash.content, "summary": flash.text})
    if shared.get("category") in ALLOWED_CATEGORIES:
        return str(shared["category"]), str(shared.get("reason") or "shared_classifier_keyword")
    return None, "energy_requires_material_context" if energy_without_context else "keyword_no_match"


def classify_flash(flash: Flash) -> str | None:
    return classify_flash_with_reason(flash)[0]


def compact_summary(flash: Flash, category: str) -> str:
    """Keep the eventual Telegram body below 30 characters.

    GitHub forms ``緊急｜分類｜摘要``.  A 20-character summary leaves room for
    every currently allowed Chinese category label and avoids watch truncation.
    """
    text = re.sub(r"\s+", " ", flash.text).strip()
    label = CATEGORY_LABELS[category]
    prefix = f"{label}："
    available = 20 - len(prefix)
    return f"{prefix}{text[:max(1, available)]}".rstrip("，。；： ")


def alert_from_flash(flash: Flash) -> Alert | None:
    category = classify_flash_with_reason(flash)[0]
    if category is None or category not in ALLOWED_CATEGORIES:
        return None
    # A commercial flash can be an early warning, but it is not the official
    # confirmation required for a black-swan push.  USGS/GDACS/TWSE and other
    # first-party monitors remain the only delivery route for that category.
    if category == "black_swan":
        return None
    return Alert(
        event_id=f"jin10-{flash.event_id}",
        category=category,
        summary=compact_summary(flash, category),
        occurred_at=flash.occurred_at,
    )


def extract_flashes(value: Any) -> list[Flash]:
    """Extract the documented Flash item fields from an MCP tool response."""
    found: list[Flash] = []

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            event_id = item.get("id")
            content = item.get("content")
            occurred_at = item.get("time")
            if event_id is not None and content is not None and occurred_at is not None:
                found.append(
                    Flash(
                        event_id=str(event_id),
                        title=str(item.get("title") or ""),
                        content=str(content),
                        occurred_at=str(occurred_at),
                    )
                )
            for nested in item.values():
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    deduped: dict[str, Flash] = {flash.event_id: flash for flash in found}
    return list(deduped.values())


def result_payload(result: Any) -> Any:
    structured = getattr(result, "structuredContent", None)
    if structured:
        return structured
    texts: list[Any] = []
    for block in getattr(result, "content", []) or []:
        raw = getattr(block, "text", None)
        if raw is None:
            continue
        try:
            texts.append(json.loads(raw))
        except json.JSONDecodeError:
            texts.append(raw)
    return texts


class SeenStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.owner_thread_id = threading.get_ident()
        # The monitor loop and the HTTP delivery callback are different
        # threads.  Keep the long-lived loop connection for normal work, but
        # allow the callback to use a short-lived connection of its own.
        # WAL/busy_timeout prevent a callback arriving during a monitor commit
        # from becoming an unexplained 500 response.
        self.connection = sqlite3.connect(path, timeout=5)
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS seen (event_id TEXT PRIMARY KEY, first_seen_at TEXT NOT NULL)"
        )
        # Older Railway volumes have a two-column ``seen`` table.  Keep those
        # rows, but make them eligible for one post-deploy classification pass
        # so a headline that was previously outside the keyword scope can be
        # re-evaluated after a rule update.
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(seen)").fetchall()}
        if "classification" not in columns:
            self.connection.execute(
                "ALTER TABLE seen ADD COLUMN classification TEXT NOT NULL DEFAULT 'unclassified'"
            )
        if "classified_at" not in columns:
            self.connection.execute("ALTER TABLE seen ADD COLUMN classified_at TEXT")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS dispatched (category TEXT NOT NULL, summary TEXT NOT NULL, dispatched_at TEXT NOT NULL)"
        )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS cache (cache_key TEXT PRIMARY KEY, payload TEXT NOT NULL, refreshed_at TEXT NOT NULL)"
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS event_ledger (
                canonical_key TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                source_url TEXT,
                person_fingerprint TEXT,
                location_fingerprint TEXT,
                action_fingerprint TEXT,
                first_discovered_at TEXT NOT NULL,
                last_reminded_at TEXT,
                escalated INTEGER NOT NULL DEFAULT 0,
                verified_sources_json TEXT NOT NULL DEFAULT '[]',
                last_title TEXT,
                updated_at TEXT NOT NULL
            )"""
        )
        # Formal Railway outbox: dispatch attempts survive GitHub Actions
        # cache eviction and can be retried/inspected without replaying every
        # source event.
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS delivery_outbox (
                trace_id TEXT PRIMARY KEY,
                canonical_key TEXT NOT NULL,
                source TEXT NOT NULL,
                event_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                next_retry_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS incoming_events (
                event_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                title TEXT,
                content TEXT,
                occurred_at TEXT,
                classification TEXT NOT NULL DEFAULT 'unclassified',
                classification_reason TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                last_error TEXT
            )"""
        )
        incoming_columns = {
            row[1] for row in self.connection.execute("PRAGMA table_info(incoming_events)").fetchall()
        }
        if "classification_reason" not in incoming_columns:
            self.connection.execute(
                "ALTER TABLE incoming_events ADD COLUMN classification_reason TEXT"
            )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS delivery_receipts (
                trace_id TEXT NOT NULL,
                recipient_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                error TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(trace_id, recipient_hash)
            )"""
        )
        self.connection.commit()

    def record_incoming_flash(self, flash: Flash, classification_reason: str | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.connection.execute(
            """INSERT INTO incoming_events(event_id,source,title,content,occurred_at,classification_reason,first_seen_at,last_seen_at)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(event_id) DO UPDATE SET title=excluded.title, content=excluded.content,
                 occurred_at=excluded.occurred_at,
                 classification_reason=CASE WHEN incoming_events.classification='unclassified'
                   THEN COALESCE(excluded.classification_reason, incoming_events.classification_reason)
                   ELSE incoming_events.classification_reason END,
                 last_seen_at=excluded.last_seen_at""",
            (flash.event_id, "jin10", flash.title, flash.content, flash.occurred_at, classification_reason, now, now),
        )
        self.connection.commit()

    def set_classification_reason(self, event_id: str, reason: str, error: str | None = None) -> None:
        """Persist the rule path even when an event is not dispatchable."""
        now = datetime.now(timezone.utc).isoformat()
        self.connection.execute(
            "UPDATE incoming_events SET classification_reason=?, last_error=?, last_seen_at=? WHERE event_id=?",
            (str(reason)[:200], error[:500] if error else None, now, event_id),
        )
        self.connection.commit()

    def classification_reason_counts(self) -> dict[str, int]:
        rows = self.connection.execute(
            """SELECT COALESCE(classification_reason, 'unknown'), COUNT(*)
               FROM incoming_events WHERE classification='unclassified'
               GROUP BY COALESCE(classification_reason, 'unknown')"""
        ).fetchall()
        return {str(reason): int(count) for reason, count in rows}

    def classification_diagnostics(self) -> dict[str, Any]:
        rows = self.connection.execute(
            """SELECT COALESCE(classification, 'unknown'), COUNT(*)
               FROM incoming_events GROUP BY COALESCE(classification, 'unknown')"""
        ).fetchall()
        reason_counts = self.classification_reason_counts()
        return {
            "classification_counts": {str(label): int(count) for label, count in rows},
            "reason_counts": reason_counts,
            "unclassified_count": sum(reason_counts.values()),
        }

    def record_outbox(self, alert: Alert, payload: dict[str, Any]) -> str:
        trace_id = alert_trace_id(alert)
        now = datetime.now(timezone.utc).isoformat()
        self.connection.execute(
            """INSERT INTO delivery_outbox(trace_id,canonical_key,source,event_id,payload_json,status,created_at,updated_at)
               VALUES(?,?,?,?,?,'pending',?,?)
               ON CONFLICT(trace_id) DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at""",
            (trace_id, alert_canonical_key(alert), alert.source, alert.event_id, json.dumps(payload, ensure_ascii=False), now, now),
        )
        self.connection.commit()
        update_health("delivery", **self.delivery_diagnostics())
        return trace_id

    def mark_outbox(self, trace_id: str, status: str, error: str | None = None) -> None:
        if status not in {"pending", "sent", "partial", "failed"}:
            raise ValueError(f"unsupported outbox status: {status}")
        self.connection.execute(
            "UPDATE delivery_outbox SET status=?, attempts=attempts+1, last_error=?, updated_at=? WHERE trace_id=?",
            (status, error, datetime.now(timezone.utc).isoformat(), trace_id),
        )
        self.connection.commit()
        update_health("delivery", **self.delivery_diagnostics())

    def delivery_diagnostics(self, db: sqlite3.Connection | None = None) -> dict[str, Any]:
        """Return non-secret delivery state for Railway's health endpoint."""
        database = db or self.connection
        rows = database.execute(
            "SELECT status, COUNT(*) FROM delivery_outbox GROUP BY status"
        ).fetchall()
        counts = {str(status): int(count) for status, count in rows}
        latest = database.execute(
            """SELECT trace_id, status, last_error, updated_at
               FROM delivery_outbox ORDER BY updated_at DESC LIMIT 1"""
        ).fetchone()
        receipt = database.execute(
            """SELECT status, updated_at FROM delivery_receipts
               WHERE recipient_hash='__aggregate__' ORDER BY updated_at DESC LIMIT 1"""
        ).fetchone()
        outbox_status = str(latest[1]) if latest else None
        receipt_status = str(receipt[0]) if receipt else None
        return {
            "status": receipt_status or outbox_status or "not_checked",
            "last_trace_id": str(latest[0]) if latest else None,
            "last_outbox_status": outbox_status,
            "last_receipt_status": receipt_status,
            "counts": counts,
            "last_updated_at": (receipt[1] if receipt else latest[3]) if (receipt or latest) else None,
            "last_error": str(latest[2]) if latest and latest[2] else None,
        }

    def record_delivery_status(self, payload: dict[str, Any]) -> bool:
        """Persist an authenticated GitHub per-run delivery receipt."""
        trace_id = str(payload.get("trace_id") or "").strip()
        status = str(payload.get("delivery_status") or "unknown").strip()
        if not trace_id or status not in {"delivered", "partial", "failed"}:
            raise ValueError("invalid delivery receipt")
        failed_hashes = payload.get("failed_recipient_hashes") or []
        if not isinstance(failed_hashes, list) or any(not isinstance(item, str) for item in failed_hashes):
            raise ValueError("invalid failed recipient hashes")
        callback_connection = threading.get_ident() != self.owner_thread_id
        db = sqlite3.connect(self.path, timeout=5) if callback_connection else self.connection
        try:
            db.execute("PRAGMA busy_timeout=5000")
            now = datetime.now(timezone.utc).isoformat()
            exists = db.execute(
                "SELECT 1 FROM delivery_outbox WHERE trace_id = ?", (trace_id,)
            ).fetchone()
            if exists is None:
                logging.warning("delivery receipt for unknown trace_id=%s", trace_id)
                return False
            db.execute(
                "UPDATE delivery_outbox SET status=?, last_error=?, updated_at=? WHERE trace_id=?",
                (status, None if status == "delivered" else "recipient delivery incomplete", now, trace_id),
            )
            for recipient_hash in failed_hashes:
                db.execute(
                    "INSERT OR REPLACE INTO delivery_receipts(trace_id,recipient_hash,status,error,updated_at) VALUES(?,?,?,?,?)",
                    (trace_id, recipient_hash[:128], "failed", "recipient delivery failed", now),
                )
            db.execute(
                "INSERT OR REPLACE INTO delivery_receipts(trace_id,recipient_hash,status,error,updated_at) VALUES(?,?,?,?,?)",
                (trace_id, "__aggregate__", status, json.dumps({
                    "delivered_count": payload.get("delivered_count", 0),
                    "failed_count": payload.get("failed_count", 0),
                    "reported_at": payload.get("reported_at"),
                }, ensure_ascii=False), now),
            )
            db.commit()
            update_health("delivery", **self.delivery_diagnostics(db))
            return True
        finally:
            if callback_connection:
                db.close()

    def release_classification(self, event_id: str, error: str) -> None:
        """Return a failed dispatch to the retryable state."""
        now = datetime.now(timezone.utc).isoformat()
        self.connection.execute(
            "UPDATE seen SET classification='unclassified', classified_at=NULL WHERE event_id=?",
            (event_id,),
        )
        self.connection.execute(
            "UPDATE incoming_events SET classification='unclassified', classification_reason=?, last_error=?, last_seen_at=? WHERE event_id=?",
            (f"dispatch_failed:{error[:120]}" if error else "dispatch_failed", error[:500], now, event_id),
        )
        self.connection.commit()

    def add_if_new(self, event_id: str) -> bool:
        """Backward-compatible insert helper for callers outside the poll loop."""
        cursor = self.connection.execute(
            "INSERT OR IGNORE INTO seen(event_id, first_seen_at, classification) VALUES (?, ?, 'unclassified')",
            (event_id, datetime.now(timezone.utc).isoformat()),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def claim_classification(self, event_id: str, classification: str) -> bool:
        """Claim an event once, while allowing legacy unknown rows to retry.

        The old monitor inserted every ID before classification.  That made a
        transiently unrecognised headline permanent and explains why adding a
        better keyword later did not recover the missed Trump/Iran event.  A
        row in ``unclassified`` is deliberately re-claimable; once it becomes
        in-scope, out-of-scope, or baseline it is stable and will not loop.
        """
        allowed = {"unclassified", "in_scope", "out_of_scope", "baseline"}
        if classification not in allowed:
            raise ValueError(f"unsupported event classification: {classification}")
        now = datetime.now(timezone.utc).isoformat()
        row = self.connection.execute(
            "SELECT classification FROM seen WHERE event_id = ?", (event_id,)
        ).fetchone()
        if row is None:
            self.connection.execute(
                "INSERT INTO seen(event_id, first_seen_at, classification, classified_at) VALUES (?, ?, ?, ?)",
                (event_id, now, classification, now if classification != "unclassified" else None),
            )
            self.connection.commit()
            return classification != "unclassified"
        previous = str(row[0] or "unclassified")
        if previous != "unclassified":
            return False
        if classification == "unclassified":
            return False
        self.connection.execute(
            "UPDATE seen SET classification = ?, classified_at = ? WHERE event_id = ? AND classification = 'unclassified'",
            (classification, now, event_id),
        )
        self.connection.execute(
            "UPDATE incoming_events SET classification = ?, last_seen_at = ? WHERE event_id = ?",
            (classification, now, event_id),
        )
        self.connection.commit()
        return True

    def classification_for(self, event_id: str) -> str | None:
        row = self.connection.execute(
            "SELECT classification FROM seen WHERE event_id = ?", (event_id,)
        ).fetchone()
        return str(row[0]) if row and row[0] else None

    def set_classification(self, event_id: str, classification: str) -> None:
        """Finalize a claimed event (used for first-cycle baseline rows)."""
        if classification not in {"in_scope", "out_of_scope", "baseline"}:
            raise ValueError(f"unsupported event classification: {classification}")
        self.connection.execute(
            "UPDATE seen SET classification = ?, classified_at = ? WHERE event_id = ?",
            (classification, datetime.now(timezone.utc).isoformat(), event_id),
        )
        self.connection.execute(
            "UPDATE incoming_events SET classification = ?, last_seen_at = ? WHERE event_id = ?",
            (classification, datetime.now(timezone.utc).isoformat(), event_id),
        )
        self.connection.commit()

    def may_dispatch(self, alert: Alert, cooldown_seconds: int) -> bool:
        """Allow a category update after cooldown, or immediately on escalation."""
        row = self.connection.execute(
            "SELECT summary, dispatched_at FROM dispatched WHERE category = ? ORDER BY rowid DESC LIMIT 1",
            (alert.category,),
        ).fetchone()
        if row is None:
            return True
        previous_summary, previous_time = row
        try:
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(previous_time)).total_seconds()
        except ValueError:
            return True
        if elapsed >= cooldown_seconds:
            return True
        current = alert.summary.casefold()
        previous = str(previous_summary).casefold()
        return any(term.casefold() in current and term.casefold() not in previous for term in ESCALATION_TERMS)

    def record_dispatch(self, alert: Alert) -> None:
        self.connection.execute(
            "INSERT INTO dispatched(category, summary, dispatched_at) VALUES (?, ?, ?)",
            (alert.category, alert.summary, datetime.now(timezone.utc).isoformat()),
        )
        self.connection.commit()

    def observe_alert(self, alert: Alert) -> dict[str, Any]:
        """Observe an alert in the durable ledger and return its identity."""
        key = alert_canonical_key(alert)
        now = datetime.now(timezone.utc).isoformat()
        urls = sorted({normalize_source_url(item.url) for item in alert.evidence if normalize_source_url(item.url)})
        fingerprints = alert_fact_fingerprints(alert.summary)
        row = self.connection.execute(
            "SELECT first_discovered_at, last_reminded_at, escalated, verified_sources_json FROM event_ledger WHERE canonical_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            self.connection.execute(
                "INSERT INTO event_ledger(canonical_key,event_type,source_url,person_fingerprint,location_fingerprint,action_fingerprint,first_discovered_at,last_reminded_at,escalated,verified_sources_json,last_title,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (key, alert.category, urls[0] if urls else "", fingerprints["person"], fingerprints["location"], fingerprints["action"], now, None, 0, json.dumps(urls), alert.summary, now),
            )
            self.connection.commit()
            return {"canonical_key": key, "is_new": True, "last_reminded_at": None, "escalated": False}
        previous_sources = json.loads(row[3] or "[]") if row[3] else []
        merged_sources = sorted(set(previous_sources) | set(urls))
        self.connection.execute(
            "UPDATE event_ledger SET verified_sources_json = ?, updated_at = ? WHERE canonical_key = ?",
            (json.dumps(merged_sources), now, key),
        )
        self.connection.commit()
        return {"canonical_key": key, "is_new": False, "last_reminded_at": row[1], "escalated": bool(row[2])}

    def mark_alert_reminded(self, alert: Alert, *, escalated: bool = False) -> None:
        key = alert_canonical_key(alert)
        self.connection.execute(
            "UPDATE event_ledger SET last_reminded_at = ?, escalated = CASE WHEN ? THEN 1 ELSE escalated END, updated_at = ? WHERE canonical_key = ?",
            (datetime.now(timezone.utc).isoformat(), int(escalated), datetime.now(timezone.utc).isoformat(), key),
        )
        self.connection.commit()

    def ledger_may_dispatch(self, record: dict[str, Any], cooldown_seconds: int) -> bool:
        if record.get("is_new") or record.get("escalated"):
            return True
        raw = record.get("last_reminded_at")
        if not raw:
            return True
        try:
            return (datetime.now(timezone.utc) - datetime.fromisoformat(str(raw))).total_seconds() >= cooldown_seconds
        except ValueError:
            return True

    def prune_event_ledger(self, retention_days: int = 30) -> None:
        cutoff = datetime.now(timezone.utc).timestamp() - max(30, retention_days) * 86400
        self.connection.execute(
            "DELETE FROM event_ledger WHERE strftime('%s', COALESCE(last_reminded_at, first_discovered_at)) < ?",
            (str(int(cutoff)),),
        )
        self.connection.commit()

    def read_cache(self, cache_key: str, max_age_seconds: int) -> list[dict[str, str]] | None:
        row = self.connection.execute(
            "SELECT payload, refreshed_at FROM cache WHERE cache_key = ?", (cache_key,)
        ).fetchone()
        if row is None:
            return None
        payload, refreshed_at = row
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(refreshed_at)).total_seconds()
            cached = json.loads(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return cached if age <= max_age_seconds and isinstance(cached, list) else None

    def write_cache(self, cache_key: str, payload: list[dict[str, str]]) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO cache(cache_key, payload, refreshed_at) VALUES (?, ?, ?)",
            (cache_key, json.dumps(payload), datetime.now(timezone.utc).isoformat()),
        )
        self.connection.commit()


def sign(alert: Alert, shared_secret: str) -> str:
    digest = hmac.new(shared_secret.encode("utf-8"), alert.canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def dispatch_alert(alert: Alert, *, token: str, repository: str, shared_secret: str) -> None:
    trace_id = alert_trace_id(alert)
    payload = {
        "event_type": "external-market-alert",
        "client_payload": {
            "source": alert.source,
            "event_id": alert.event_id,
            "category": alert.category,
            "summary": alert.summary,
            "risk_level": alert.risk_level,
            "official_confirmed": alert.official_confirmed,
            "market_sync_confirmed": alert.market_sync_confirmed,
            "market_sync": list(alert.market_sync),
            "occurred_at": alert.occurred_at,
            "evidence": alert.evidence_payload,
            "canonical_key": alert_canonical_key(alert),
            "source_url": normalize_source_url(alert.evidence_payload[0]["url"] if alert.evidence_payload else ""),
            "verified_sources": [normalize_source_url(item["url"]) for item in alert.evidence_payload],
            "event_ledger_retention_days": 30,
            "trace_id": trace_id,
            "signature": sign(alert, shared_secret),
        },
    }
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }
    endpoint = f"https://api.github.com/repos/{repository}/dispatches"
    async with httpx.AsyncClient(timeout=20) as client:
        for attempt in range(3):
            try:
                response = await client.post(endpoint, headers=headers, json=payload)
            except httpx.HTTPError as exc:
                if attempt == 2:
                    logging.error("dispatch failed trace_id=%s error=%s", trace_id, type(exc).__name__)
                    raise
                await asyncio.sleep(2**attempt)
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == 2:
                    response.raise_for_status()
                retry_after = 0
                try:
                    retry_after = int(response.json().get("parameters", {}).get("retry_after", 0))
                except (TypeError, ValueError, AttributeError):
                    pass
                await asyncio.sleep(min(60, max(1, retry_after)) if retry_after else 2**attempt)
                continue
            response.raise_for_status()
            logging.info("dispatch accepted trace_id=%s status=%s", trace_id, response.status_code)
            return


async def dispatch_monitor_health(*, token: str, repository: str, gdelt: dict[str, Any]) -> None:
    """Publish non-secret GDELT pending diagnostics for the Mini App.

    This is deliberately a separate repository-dispatch event: pending
    candidates are not alerts and must never enter the Telegram path. Only
    bounded counts/reason codes are sent; article bodies, URLs and secrets
    stay inside Railway's local audit store.
    """
    if not token or not repository:
        logging.warning("monitor health dispatch skipped: GitHub credentials are not configured")
        return
    payload = {
        "event_type": "monitor-health",
        "client_payload": {
            "component": "gdelt",
            "status": str(gdelt.get("status") or "unknown"),
            "checked_at": gdelt.get("last_success_at") or gdelt.get("last_failure_at"),
            "pending_count": int(gdelt.get("pending_count") or 0),
            "pending_reasons": {
                str(key): int(value or 0)
                for key, value in (gdelt.get("pending_reasons") or {}).items()
            },
            "market_sync_status": str(gdelt.get("market_sync_status") or "not_confirmed"),
            "error": str(gdelt.get("error") or "") or None,
        },
    }
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }
    endpoint = f"https://api.github.com/repos/{repository}/dispatches"
    async with httpx.AsyncClient(timeout=20) as client:
        for attempt in range(3):
            try:
                response = await client.post(endpoint, headers=headers, json=payload)
            except httpx.HTTPError as exc:
                if attempt == 2:
                    logging.error("monitor health dispatch failed error=%s", type(exc).__name__)
                    raise
                await asyncio.sleep(2**attempt)
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == 2:
                    response.raise_for_status()
                await asyncio.sleep(2**attempt)
                continue
            response.raise_for_status()
            logging.info("monitor health dispatch accepted status=%s", response.status_code)
            return


def default_flash_arguments(schema: dict[str, Any], requested_limit: int) -> dict[str, Any]:
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    return {"limit": requested_limit} if "limit" in properties else {}


async def fetch_jin10_flashes(token: str, requested_limit: int) -> list[Flash]:
    """Call only the official MCP endpoint; no HTML or feed scraping occurs."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(headers=headers, timeout=30, follow_redirects=True) as client:
        async with streamable_http_client(JIN10_MCP_URL, http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                tool = next((item for item in tools.tools if item.name == "list_flash"), None)
                if tool is None:
                    raise RuntimeError("Jin10 MCP did not expose the list_flash tool")
                arguments = default_flash_arguments(getattr(tool, "inputSchema", {}), requested_limit)
                try:
                    result = await session.call_tool("list_flash", arguments=arguments)
                except Exception:
                    if not arguments:
                        raise
                    logging.warning("list_flash rejected the optional limit; retrying without arguments")
                    result = await session.call_tool("list_flash", arguments={})
    return extract_flashes(result_payload(result))


def _gdelt_seen_at(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _trusted_domain(url: str, supplied_domain: str) -> str:
    host = (supplied_domain or urlparse(url).hostname or "").lower().removeprefix("www.")
    # Reuters publishes localized editions (for example reuters.cn).  Treat
    # them as the same publisher so two Reuters editions cannot masquerade as
    # independent corroboration, while still accepting the Chinese feed.
    if host == "reuters.cn" or host.endswith(".reuters.cn"):
        return "reuters.com"
    return next((domain for domain in TRUSTED_NEWS_DOMAINS if host == domain or host.endswith(f".{domain}")), "")


def _discovery_category_and_anchor(title: str, snippet: str = "") -> tuple[str, str] | None:
    text = " ".join(part for part in (title, snippet) if part).strip()
    normalized = normalized_event_text(text)
    category = classify_flash(Flash("discovery", title, snippet, ""))
    if category is None:
        return None
    anchor = _keyword_hit(DISCOVERY_ANCHORS.get(category, ()), normalized)
    anchor = _canonical_discovery_alias(anchor)
    return (category, anchor) if anchor else None


def _canonical_discovery_alias(value: str) -> str:
    normalized = normalized_event_text(value)
    for canonical, aliases in DISCOVERY_ALIAS_GROUPS.items():
        if normalized in {normalized_event_text(alias) for alias in aliases}:
            return canonical
    return value


def _canonical_discovery_action(value: str) -> str:
    normalized = normalized_event_text(value)
    for canonical, aliases in DISCOVERY_ACTION_ALIAS_GROUPS.items():
        if normalized in {normalized_event_text(alias) for alias in aliases}:
            return canonical
    return value


def _discovery_facts(title: str, category: str, anchor: str, snippet: str = "") -> tuple[set[str], set[str]]:
    """Extract the concrete actor/place and action facts used for agreement."""
    text = " ".join(part for part in (title, snippet) if part).strip()
    normalized = normalized_event_text(text)
    compact = normalized.replace(" ", "")
    entities = {
        canonical
        for canonical, aliases in DISCOVERY_ALIAS_GROUPS.items()
        if any(_keyword_in_text(alias, normalized, compact) for alias in aliases)
    }
    entities.update(
        _canonical_discovery_alias(term)
        for term in DISCOVERY_ENTITIES
        if _keyword_in_text(term, normalized, compact)
    )
    if anchor in DISCOVERY_ENTITY_ANCHORS:
        entities.add(_canonical_discovery_alias(anchor))
    actions = {
        _canonical_discovery_action(term)
        for term in DISCOVERY_ACTIONS.get(category, ())
        if _keyword_in_text(term, normalized, compact)
    }
    return entities, actions


def _matching_discovery_evidence(
    cluster: list[DiscoveryArticle], category: str, anchor: str
) -> tuple[DiscoveryArticle, ...]:
    """Return only multi-domain articles agreeing on entity/place and action."""
    supported: dict[str, DiscoveryArticle] = {}
    facts = [(article, *_discovery_facts(article.title, category, anchor, article.snippet)) for article in cluster]
    for index, (left, left_entities, left_actions) in enumerate(facts):
        for right, right_entities, right_actions in facts[index + 1:]:
            if left.domain == right.domain:
                continue
            if not (left_entities & right_entities) or not (left_actions & right_actions):
                continue
            for article in (left, right):
                current = supported.get(article.domain)
                if current is None or article.seen_at < current.seen_at:
                    supported[article.domain] = article
    return tuple(supported[domain] for domain in sorted(supported))


def _decode_discovery_articles(rows: list[dict[str, str]]) -> list[DiscoveryArticle]:
    return [DiscoveryArticle(**row) for row in rows]


async def fetch_gdelt_articles(store: SeenStore | None = None) -> list[DiscoveryArticle]:
    """Fetch discovery headlines with a 15-minute cache and 120-minute fallback."""
    fresh_cache_seconds = max(60, int(os.environ.get("GDELT_CACHE_MINUTES", "15")) * 60)
    stale_cache_seconds = max(fresh_cache_seconds, int(os.environ.get("GDELT_STALE_CACHE_MINUTES", "120")) * 60)
    fresh_age_seconds = max(60, int(os.environ.get("GDELT_MAX_FRESH_AGE_MINUTES", "45")) * 60)
    if store:
        cached = store.read_cache("gdelt-success", fresh_cache_seconds)
        if cached is not None:
            return _decode_discovery_articles(cached)
    params = {"query": os.environ.get("GDELT_QUERY", GDELT_QUERY), "mode": "artlist", "format": "json", "sort": "datedesc", "maxrecords": 75}
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(GDELT_DOC_URL, params=params)
        response.raise_for_status()
    except Exception:
        if store:
            stale = store.read_cache("gdelt-success", stale_cache_seconds)
            if stale is not None:
                logging.warning("GDELT temporarily unavailable; using the most recent cached success")
                return _decode_discovery_articles(stale)
        raise
    cutoff = datetime.now(timezone.utc).timestamp() - fresh_age_seconds
    articles: list[DiscoveryArticle] = []
    for row in response.json().get("articles", []):
        title = str(row.get("title") or "").strip()
        # GDELT DOC commonly provides only a title, but some response modes and
        # cached adapters include a short description/snippet.  Preserve it so
        # the action/entity cross-check can see facts that are absent from a
        # generic title such as "US-Iran situation".
        snippet = str(row.get("snippet") or row.get("description") or row.get("summary") or "").strip()
        url = str(row.get("url") or "").strip()
        seen_at = str(row.get("seendate") or "").strip()
        observed = _gdelt_seen_at(seen_at)
        domain = _trusted_domain(url, str(row.get("domain") or ""))
        if not title or not url or not observed or observed.timestamp() < cutoff or not domain:
            continue
        articles.append(DiscoveryArticle(title=title, url=url, domain=domain, seen_at=observed.isoformat(), snippet=snippet))
    if store:
        store.write_cache("gdelt-success", [article.__dict__ for article in articles])
    return articles


async def fetch_market_sync_snapshot() -> dict[str, Any]:
    """Read the latest public market snapshot used to confirm event impact.

    The monitor is intentionally read-only.  Railway can point
    ``MARKET_SNAPSHOT_URL`` at the deployed Mini App JSON; otherwise the
    configured dashboard URL is used.  A missing or stale snapshot is a
    deliberate *no-confirmation* result, never a reason to guess.
    """
    base = os.environ.get("MARKET_SNAPSHOT_URL", "").strip()
    if not base:
        base = os.environ.get("DASHBOARD_URL", "").strip().rstrip("/")
        if base:
            base = f"{base}/data/market.json"
    if not base:
        return {}
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            response = await client.get(base)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}
    except (httpx.HTTPError, ValueError, TypeError) as error:
        logging.warning("market sync snapshot unavailable error=%s", type(error).__name__)
        return {}


def _market_sync_details(
    event_time: str, snapshot: dict[str, Any] | None,
) -> tuple[str, ...]:
    """Return independently quoted markets moving with a breaking event.

    Price confirmation is conservative: delayed rows are ignored, quotes must
    be close to the discovery timestamp when both timestamps exist, and the
    move must be material (1% for broad equity indices, 2% for commodities or
    crypto).  This is a confirmation signal, not a prediction.
    """
    if not snapshot:
        return ()
    records = list(snapshot.get("indices") or []) + list(snapshot.get("quotes") or [])
    confirmed: list[str] = []
    source_at: datetime | None = None
    try:
        source_at = datetime.fromisoformat(str(event_time).replace("Z", "+00:00"))
        if source_at.tzinfo is None:
            source_at = source_at.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        source_at = None
    for item in records:
        if not isinstance(item, dict) or item.get("quote_delayed"):
            continue
        ticker = str(item.get("ticker") or "").upper()
        if ticker not in {"TAIEX", "NASDAQ", "SOX", "S&P 500", "DJIA", "NIKKEI", "KOSPI", "WTI", "BRENT", "GOLD", "BTC", "ETH"}:
            continue
        try:
            move = abs(float(item.get("change_percent")))
        except (TypeError, ValueError):
            continue
        threshold = 2.0 if ticker in {"WTI", "BRENT", "GOLD", "BTC", "ETH"} else 1.0
        if move < threshold:
            continue
        quote_at = item.get("quote_time") or item.get("fetched_at")
        if source_at and quote_at:
            try:
                observed = datetime.fromisoformat(str(quote_at).replace("Z", "+00:00"))
                if observed.tzinfo is None:
                    observed = observed.replace(tzinfo=timezone.utc)
                if abs((observed - source_at).total_seconds()) > 60 * 60:
                    continue
            except (TypeError, ValueError):
                continue
        confirmed.append(ticker)
    return tuple(dict.fromkeys(confirmed))


def _gdelt_candidate_clusters(articles: Iterable[DiscoveryArticle]) -> dict[tuple[str, str], list[DiscoveryArticle]]:
    clusters: dict[tuple[str, str], list[DiscoveryArticle]] = {}
    for article in articles:
        classified = _discovery_category_and_anchor(article.title, article.snippet)
        if classified:
            clusters.setdefault(classified, []).append(article)
    return clusters


def pending_gdelt_candidates(
    articles: Iterable[DiscoveryArticle], market_sync: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Expose candidates that are waiting for evidence instead of dropping them silently.

    The returned records intentionally contain only category, anchor, counts and a
    reason.  Article bodies and URLs remain in the audit ledger, not the public
    health payload.  A candidate is still not dispatchable until the normal
    multi-domain and action-intersection gate succeeds.
    """
    clusters = _gdelt_candidate_clusters(articles)
    pending: list[dict[str, Any]] = []
    for (category, anchor), cluster in clusters.items():
        domains = {article.domain for article in cluster}
        if len(domains) < 2:
            pending.append({"category": category, "anchor": anchor, "article_count": len(cluster), "domain_count": len(domains), "reason": "waiting_second_trusted_source"})
            continue
        evidence = _matching_discovery_evidence(cluster, category, anchor)
        if len({article.domain for article in evidence}) < 2:
            pending.append({"category": category, "anchor": anchor, "article_count": len(cluster), "domain_count": len(domains), "reason": "waiting_shared_entity_action"})
            continue
        if category == "black_swan":
            representative = min(evidence, key=lambda article: article.seen_at)
            if not _market_sync_details(representative.seen_at, market_sync):
                pending.append({"category": category, "anchor": anchor, "article_count": len(cluster), "domain_count": len(domains), "reason": "waiting_market_sync_for_warning"})
    return pending


def cross_checked_gdelt_alerts(
    articles: Iterable[DiscoveryArticle], market_sync: dict[str, Any] | None = None,
) -> list[Alert]:
    """Require two publishers, shared facts and market impact confirmation.

    GDELT remains a discovery layer, so a matching black-swan cluster can only
    produce a warning-level alert.  The official monitor is the sole path to
    a high-risk black-swan notification.
    """
    clusters = _gdelt_candidate_clusters(articles)
    alerts: list[Alert] = []
    for (category, anchor), cluster in clusters.items():
        domains = {article.domain for article in cluster}
        if len(domains) < 2:
            continue
        evidence = _matching_discovery_evidence(cluster, category, anchor)
        if len({article.domain for article in evidence}) < 2:
            continue
        representative = min(evidence, key=lambda article: article.seen_at)
        sync_details = _market_sync_details(representative.seen_at, market_sync)
        if category == "black_swan" and not sync_details:
            continue
        stable_id = hashlib.sha256("|".join(sorted(article.url for article in cluster)).encode("utf-8")).hexdigest()[:20]
        alerts.append(Alert(
            event_id=f"gdelt-{category}-{stable_id}",
            category=category,
            summary=f"{CATEGORY_LABELS[category]}：{anchor}多源核對",
            occurred_at=representative.seen_at,
            source="gdelt",
            evidence=evidence,
            risk_level="警戒" if category == "black_swan" else "警戒",
            official_confirmed=False,
            market_sync_confirmed=bool(sync_details),
            market_sync=sync_details,
        ))
    return alerts


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path not in {"/", "/health"}:
            self.send_error(404)
            return
        body = (json.dumps(health_snapshot(), ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/delivery-status":
            self.send_error(404)
            return
        secret = os.environ.get("DELIVERY_STATUS_SHARED_SECRET", "")
        if not secret:
            self.send_error(503, "delivery callback is not configured")
            return
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 128 * 1024)
            body = self.rfile.read(length)
            supplied = self.headers.get("X-PRSTK-Signature", "")
            expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(supplied, expected):
                self.send_error(401)
                return
            payload = json.loads(body.decode("utf-8"))
            if DELIVERY_STORE is None or not DELIVERY_STORE.record_delivery_status(payload):
                self.send_error(404, "unknown trace_id")
                return
            response = b'{"ok":true}\n'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)
        except (ValueError, TypeError, json.JSONDecodeError):
            self.send_error(400, "invalid delivery receipt")
        except Exception:
            logging.exception("delivery status callback failed")
            self.send_error(500)

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def start_health_server() -> None:
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logging.info("Health endpoint listening on port %s", port)


async def monitor_forever() -> None:
    jin10_token = configured("JIN10_MCP_TOKEN")
    github_token = configured("GITHUB_DISPATCH_TOKEN")
    repository = configured("GITHUB_REPOSITORY")
    shared_secret = configured("EXTERNAL_ALERT_SHARED_SECRET")
    interval = max(60, int(os.environ.get("JIN10_POLL_SECONDS", "120")))
    limit = min(100, max(1, int(os.environ.get("JIN10_FLASH_LIMIT", "30"))))
    # One event cooldown is shared by Jin10, GDELT and the durable ledger.
    # The legacy category-specific variable is intentionally ignored so an
    # old Railway setting cannot silently restore a two-hour cooldown.
    cooldown = EVENT_COOLDOWN_SECONDS
    bootstrap = os.environ.get("JIN10_INITIAL_BACKFILL", "false").lower() == "true"
    gdelt_interval = max(900, int(os.environ.get("GDELT_POLL_SECONDS", "900")))
    gdelt_enabled = os.environ.get("GDELT_DISCOVERY_ENABLED", "true").lower() == "true"
    update_health("gdelt", enabled=gdelt_enabled, poll_seconds=gdelt_interval,
                  status="disabled" if not gdelt_enabled else "not_checked")
    store = SeenStore(Path(os.environ.get("MONITOR_STATE_PATH", "/data/jin10-monitor.sqlite3")))
    global DELIVERY_STORE
    DELIVERY_STORE = store
    update_health("delivery", **store.delivery_diagnostics())
    first_cycle = True
    gdelt_baseline = True
    last_gdelt_poll = 0.0

    while True:
        try:
            flashes = await fetch_jin10_flashes(jin10_token, limit)
            flashes.sort(key=lambda item: item.occurred_at)
            dispatched = 0
            for flash in flashes:
                classification, classification_reason = classify_flash_with_reason(flash)
                store.record_incoming_flash(flash, classification_reason)
                previous_classification = store.classification_for(flash.event_id)
                alert = alert_from_flash(flash)
                if alert is None and classification == "black_swan":
                    classification_reason = "black_swan_requires_official_confirmation"
                classification_status = "in_scope" if alert is not None else "unclassified"
                logging.info(
                    "Jin10 flash classified event_id=%s classification=%s reason=%s",
                    flash.event_id, classification_status, classification_reason,
                )
                if previous_classification in {None, "unclassified"}:
                    store.set_classification_reason(flash.event_id, classification_reason)
                if not store.claim_classification(flash.event_id, classification_status):
                    continue
                if alert is None:
                    # Keep unrecognised IDs retryable after a rule/source update.
                    continue
                # Brand-new rows are baselined on the first cycle.  A legacy
                # ``unclassified`` row is intentionally not baselined: it is
                # precisely the missed event that a rule update should recover.
                if first_cycle and not bootstrap and previous_classification is None:
                    store.set_classification(flash.event_id, "baseline")
                    store.set_classification_reason(flash.event_id, "baseline_initial_cycle")
                    continue
                ledger_record = store.observe_alert(alert)
                if not store.ledger_may_dispatch(ledger_record, cooldown):
                    logging.info("Jin10 alert suppressed by durable event ledger: %s", ledger_record["canonical_key"])
                    store.set_classification_reason(flash.event_id, "durable_ledger_cooldown")
                    continue
                if not store.may_dispatch(alert, cooldown):
                    logging.info("Jin10 alert suppressed by category cooldown: %s", alert.category)
                    store.set_classification_reason(flash.event_id, "category_cooldown")
                    continue
                trace_id = store.record_outbox(alert, {
                    "source": alert.source, "event_id": alert.event_id,
                    "category": alert.category, "summary": alert.summary,
                    "occurred_at": alert.occurred_at,
                })
                try:
                    await dispatch_alert(alert, token=github_token, repository=repository, shared_secret=shared_secret)
                except Exception as error:
                    store.mark_outbox(trace_id, "failed", type(error).__name__)
                    store.release_classification(flash.event_id, type(error).__name__)
                    logging.exception("Jin10 dispatch failed trace_id=%s; event remains retryable", trace_id)
                    continue
                store.mark_outbox(trace_id, "sent")
                store.record_dispatch(alert)
                store.set_classification(flash.event_id, "in_scope")
                store.set_classification_reason(flash.event_id, "dispatched_to_github")
                store.mark_alert_reminded(alert, escalated="高風險" in alert.summary)
                dispatched += 1
            diagnostics = store.classification_diagnostics()
            logging.info("Jin10 poll completed: %s flash(es), %s alert(s) dispatched", len(flashes), dispatched)
            update_health("jin10", status="healthy", last_success_at=datetime.now(timezone.utc).isoformat(),
                          item_count=len(flashes), error=None)
            update_health("classification", status="healthy", updated_at=datetime.now(timezone.utc).isoformat(), **diagnostics)
            first_cycle = False
        except Exception as error:
            update_health("jin10", status="failed", last_failure_at=datetime.now(timezone.utc).isoformat(),
                          error=type(error).__name__)
            logging.exception("Jin10 poll failed; will retry")
        if gdelt_enabled and time.monotonic() - last_gdelt_poll >= gdelt_interval:
            last_gdelt_poll = time.monotonic()
            try:
                articles = await fetch_gdelt_articles(store)
                # A discovery headline is not enough for a black-swan push.
                # Refresh the public quote snapshot and require a material,
                # time-aligned move before producing a warning-level alert.
                market_sync = await fetch_market_sync_snapshot()
                pending = pending_gdelt_candidates(articles, market_sync)
                alerts = cross_checked_gdelt_alerts(articles, market_sync)
                dispatched = 0
                for alert in alerts:
                    previous_classification = store.classification_for(alert.event_id)
                    if not store.claim_classification(alert.event_id, "in_scope"):
                        continue
                    if gdelt_baseline and not bootstrap and previous_classification is None:
                        store.set_classification(alert.event_id, "baseline")
                        continue
                    ledger_record = store.observe_alert(alert)
                    if not store.ledger_may_dispatch(ledger_record, EVENT_COOLDOWN_SECONDS):
                        logging.info("GDELT alert suppressed by durable event ledger: %s", ledger_record["canonical_key"])
                        continue
                    if not store.may_dispatch(alert, EVENT_COOLDOWN_SECONDS):
                        continue
                    trace_id = store.record_outbox(alert, {
                        "source": alert.source, "event_id": alert.event_id,
                        "category": alert.category, "summary": alert.summary,
                        "occurred_at": alert.occurred_at,
                    })
                    try:
                        await dispatch_alert(alert, token=github_token, repository=repository, shared_secret=shared_secret)
                    except Exception as error:
                        store.mark_outbox(trace_id, "failed", type(error).__name__)
                        store.release_classification(alert.event_id, type(error).__name__)
                        logging.exception("GDELT dispatch failed trace_id=%s; event remains retryable", trace_id)
                        continue
                    store.mark_outbox(trace_id, "sent")
                    store.record_dispatch(alert)
                    store.set_classification(alert.event_id, "in_scope")
                    store.mark_alert_reminded(alert, escalated="高風險" in alert.summary)
                    dispatched += 1
                pending_reasons: dict[str, int] = {}
                for candidate in pending:
                    reason = str(candidate.get("reason") or "unknown")
                    pending_reasons[reason] = pending_reasons.get(reason, 0) + 1
                logging.info(
                    "GDELT cross-check completed: %s article(s), %s alert(s) dispatched, %s candidate(s) pending",
                    len(articles), dispatched, len(pending),
                )
                update_health("gdelt", status="healthy", last_success_at=datetime.now(timezone.utc).isoformat(),
                              article_count=len(articles), alert_count=dispatched,
                              market_sync_status="confirmed" if any(alert.market_sync_confirmed for alert in alerts) else "not_confirmed",
                              pending_count=len(pending), pending_reasons=pending_reasons, error=None)
                try:
                    await dispatch_monitor_health(
                        token=github_token,
                        repository=repository,
                        gdelt=health_snapshot().get("gdelt", {}),
                    )
                except Exception:
                    # Health publication is observability only; it must never
                    # stop the next Jin10/GDELT polling cycle.
                    logging.exception("GDELT health publication failed; continuing monitor loop")
                gdelt_baseline = False
            except Exception as error:
                update_health("gdelt", status="failed", last_failure_at=datetime.now(timezone.utc).isoformat(),
                              error=type(error).__name__)
                logging.exception("GDELT discovery failed; will wait for the next interval")
                try:
                    await dispatch_monitor_health(
                        token=github_token,
                        repository=repository,
                        gdelt=health_snapshot().get("gdelt", {}),
                    )
                except Exception:
                    logging.exception("GDELT failure health publication failed")
        await asyncio.sleep(interval)


def validate_runtime_layout() -> None:
    """Fail loudly in logs, but keep the health endpoint available.

    Railway deployments using ``/railway-monitor`` cannot import the
    repository-level ``src`` package.  The standalone classifier and bundled
    keyword database are intentional fallbacks; this check makes the active
    mode visible in Deploy Logs so a restart is not mistaken for a healthy
    polling loop.
    """
    try:
        probe = classify_event_fields({"title": "WTI oil production update"})
        probe_category = probe.get("category") if isinstance(probe, dict) else None
        if not probe_category:
            raise RuntimeError("classifier_probe_no_category")
        mode = "standalone-bundled" if _USING_STANDALONE_CLASSIFIER else "repository-shared"
        update_health(
            "runtime",
            status="healthy",
            classifier_mode=mode,
            keyword_categories=len(CATEGORY_KEYWORDS),
            updated_at=datetime.now(timezone.utc).isoformat(),
            error=None,
        )
        logging.info(
            "Runtime self-check passed classifier_mode=%s keyword_categories=%s",
            mode,
            len(CATEGORY_KEYWORDS),
        )
    except Exception as error:
        update_health(
            "runtime",
            status="failed",
            classifier_mode="unavailable",
            updated_at=datetime.now(timezone.utc).isoformat(),
            error=type(error).__name__,
        )
        logging.exception("Runtime self-check failed; monitor will continue for health diagnostics")


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    validate_runtime_layout()
    start_health_server()
    try:
        asyncio.run(monitor_forever())
    except RuntimeError as error:
        # Keep Railway's liveness endpoint available when a secret or
        # repository setting is missing.  Previously this exception escaped
        # the process and produced an opaque restart loop.  Only expected
        # configuration failures are held open; programming/runtime errors
        # still fail fast so they remain visible to deployment checks.
        if not str(error).startswith("Missing required Railway variable:"):
            raise
        update_health(
            "runtime",
            status="configuration_error",
            updated_at=datetime.now(timezone.utc).isoformat(),
            error="missing_required_variable",
        )
        logging.exception("Monitor is paused until Railway configuration is fixed")
        while True:
            time.sleep(60)


if __name__ == "__main__":
    main()
