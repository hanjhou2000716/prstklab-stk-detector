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
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunsplit

import httpx

try:
    from runtime_config import configuration_health, delivery_shared_secret
except ModuleNotFoundError:  # pragma: no cover - direct file loading / standalone image
    _config_spec = spec_from_file_location(
        "railway_runtime_config",
        Path(__file__).with_name("runtime_config.py"),
    )
    if _config_spec is None or _config_spec.loader is None:
        raise ImportError("cannot load railway-monitor/runtime_config.py")
    _config_module = module_from_spec(_config_spec)
    _config_spec.loader.exec_module(_config_module)
    configuration_health = _config_module.configuration_health
    delivery_shared_secret = _config_module.delivery_shared_secret

try:
    from health_contract import age_seconds, gmail_health_fields, health_request_path, monitor_heartbeat, non_negative_int
except ModuleNotFoundError:  # pragma: no cover - direct file loading / standalone image
    _health_spec = spec_from_file_location(
        "railway_health_contract",
        Path(__file__).with_name("health_contract.py"),
    )
    if _health_spec is None or _health_spec.loader is None:
        raise ImportError("cannot load railway-monitor/health_contract.py")
    _health_module = module_from_spec(_health_spec)
    _health_spec.loader.exec_module(_health_module)
    age_seconds = _health_module.age_seconds
    gmail_health_fields = _health_module.gmail_health_fields
    health_request_path = _health_module.health_request_path
    monitor_heartbeat = _health_module.monitor_heartbeat
    non_negative_int = _health_module.non_negative_int

try:
    from gmail_runtime import configure_gmail_ingress as build_gmail_ingress
except ModuleNotFoundError:  # pragma: no cover - direct file loading / standalone image
    _gmail_runtime_spec = spec_from_file_location(
        "railway_gmail_runtime",
        Path(__file__).with_name("gmail_runtime.py"),
    )
    if _gmail_runtime_spec is None or _gmail_runtime_spec.loader is None:
        raise ImportError("cannot load railway-monitor/gmail_runtime.py")
    _gmail_runtime_module = module_from_spec(_gmail_runtime_spec)
    _gmail_runtime_spec.loader.exec_module(_gmail_runtime_module)
    build_gmail_ingress = _gmail_runtime_module.configure_gmail_ingress

try:
    from dispatch_transport import dispatch_repository_payload as send_repository_payload
except ModuleNotFoundError:  # pragma: no cover - direct file loading / standalone image
    _dispatch_spec = spec_from_file_location(
        "railway_dispatch_transport",
        Path(__file__).with_name("dispatch_transport.py"),
    )
    if _dispatch_spec is None or _dispatch_spec.loader is None:
        raise ImportError("cannot load railway-monitor/dispatch_transport.py")
    _dispatch_module = module_from_spec(_dispatch_spec)
    _dispatch_spec.loader.exec_module(_dispatch_module)
    send_repository_payload = _dispatch_module.dispatch_repository_payload

try:
    from poll_config import load_poll_settings
except ModuleNotFoundError:  # pragma: no cover - direct file loading / standalone image
    _poll_config_spec = spec_from_file_location(
        "railway_poll_config",
        Path(__file__).with_name("poll_config.py"),
    )
    if _poll_config_spec is None or _poll_config_spec.loader is None:
        raise ImportError("cannot load railway-monitor/poll_config.py") from None
    _poll_config_module = module_from_spec(_poll_config_spec)
    sys.modules[_poll_config_spec.name] = _poll_config_module
    _poll_config_spec.loader.exec_module(_poll_config_module)
    load_poll_settings = _poll_config_module.load_poll_settings

try:
    from state_store_schema import initialize_state_schema
except ModuleNotFoundError:  # pragma: no cover - direct file loading / standalone image
    _schema_spec = spec_from_file_location(
        "railway_state_store_schema",
        Path(__file__).with_name("state_store_schema.py"),
    )
    if _schema_spec is None or _schema_spec.loader is None:
        raise ImportError("cannot load railway-monitor/state_store_schema.py") from None
    _schema_module = module_from_spec(_schema_spec)
    _schema_spec.loader.exec_module(_schema_module)
    initialize_state_schema = _schema_module.initialize_state_schema

try:
    from classification_store import (
        add_if_new as store_add_if_new,
        classification_diagnostics as store_classification_diagnostics,
        classification_for as store_classification_for,
        classification_reason_counts as store_classification_reason_counts,
        claim_classification as store_claim_classification,
        record_incoming_flash as store_record_incoming_flash,
        release_classification as store_release_classification,
        set_classification as store_set_classification,
        set_classification_reason as store_set_classification_reason,
    )
except ModuleNotFoundError:  # pragma: no cover - direct file loading / standalone image
    _classification_spec = spec_from_file_location(
        "railway_classification_store",
        Path(__file__).with_name("classification_store.py"),
    )
    if _classification_spec is None or _classification_spec.loader is None:
        raise ImportError("cannot load railway-monitor/classification_store.py") from None
    _classification_module = module_from_spec(_classification_spec)
    _classification_spec.loader.exec_module(_classification_module)
    store_add_if_new = _classification_module.add_if_new
    store_classification_diagnostics = _classification_module.classification_diagnostics
    store_classification_for = _classification_module.classification_for
    store_classification_reason_counts = _classification_module.classification_reason_counts
    store_claim_classification = _classification_module.claim_classification
    store_record_incoming_flash = _classification_module.record_incoming_flash
    store_release_classification = _classification_module.release_classification
    store_set_classification = _classification_module.set_classification
    store_set_classification_reason = _classification_module.set_classification_reason


def _delivery_shared_secret() -> str:
    """Return the delivery HMAC secret using the canonical or legacy name.

    GitHub Actions calls this value ``RAILWAY_STATUS_SHARED_SECRET`` while
    Railway historically exposed ``DELIVERY_STATUS_SHARED_SECRET``.  Accept
    both names during migration, preferring the Railway-specific setting, so
    a naming mismatch cannot silently block otherwise valid receipts.
    """
    return delivery_shared_secret()

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


def classifier_delivery_allowed() -> bool:
    """Allow dispatch only when the canonical repository classifier is active.

    The root-only Railway image keeps a compatibility classifier so its health
    endpoint remains available during packaging mistakes. That fallback is
    deliberately candidate-only: it must never create a repository dispatch
    that could become a Telegram alert under a different policy version.
    """
    return not _USING_STANDALONE_CLASSIFIER


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
    "gdelt": {"enabled": True, "status": "not_checked", "last_success_at": None, "last_failure_at": None, "article_count": 0, "alert_count": 0, "pending_count": 0, "pending_reasons": {}, "error": None, "stale_cache_used": False, "health_dispatch_status": "not_checked", "health_dispatch_error": None, "health_dispatch_next_retry_at": None},
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
    "monitor": {
        "status": "starting",
        "poll_interval_seconds": None,
        "last_cycle_started_at": None,
        "last_cycle_completed_at": None,
    },
    "gmail": {
        "status": "not_configured",
        "watch_status": "not_checked",
        "last_notification_at": None,
        "last_history_id": None,
        "error": None,
    },
}
DELIVERY_STORE: SeenStore | None = None
EMAIL_INGRESS: Any | None = None


def update_health(component: str, **values: Any) -> None:
    with HEALTH_LOCK:
        HEALTH_STATE.setdefault(component, {}).update(values)


def _non_negative_int(value: Any) -> int | None:
    """Compatibility wrapper for callers of the legacy app module."""
    return non_negative_int(value)


def _age_seconds(value: str | None, *, now: datetime | None = None) -> int | None:
    """Compatibility wrapper for callers of the legacy app module."""
    return age_seconds(value, now=now)


def health_snapshot() -> dict[str, Any]:
    with HEALTH_LOCK:
        snapshot = json.loads(json.dumps(HEALTH_STATE))
    monitor = snapshot.get("monitor")
    if isinstance(monitor, dict):
        monitor.update(monitor_heartbeat(monitor))
    snapshot["runtime_config"] = configuration_health()
    return snapshot


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
        initialize_state_schema(self.connection)
        self.connection.commit()

    def record_incoming_flash(self, flash: Flash, classification_reason: str | None = None) -> None:
        store_record_incoming_flash(
            self.connection,
            event_id=flash.event_id,
            title=flash.title,
            content=flash.content,
            occurred_at=flash.occurred_at,
            classification_reason=classification_reason,
        )

    def set_classification_reason(self, event_id: str, reason: str, error: str | None = None) -> None:
        """Persist the rule path even when an event is not dispatchable."""
        store_set_classification_reason(self.connection, event_id, reason, error)

    def classification_reason_counts(self) -> dict[str, int]:
        return store_classification_reason_counts(self.connection)

    def classification_diagnostics(self) -> dict[str, Any]:
        return store_classification_diagnostics(self.connection)

    def record_outbox(self, alert: Alert, payload: dict[str, Any]) -> str:
        trace_id = alert_trace_id(alert)
        now = datetime.now(timezone.utc).isoformat()
        self.connection.execute(
            """INSERT INTO delivery_outbox(trace_id,canonical_key,source,event_id,category,payload_json,status,created_at,updated_at)
               VALUES(?,?,?,?,?,?,'pending',?,?)
               ON CONFLICT(trace_id) DO UPDATE SET category=excluded.category, payload_json=excluded.payload_json, updated_at=excluded.updated_at""",
            (trace_id, alert_canonical_key(alert), alert.source, alert.event_id, alert.category, json.dumps(payload, ensure_ascii=False), now, now),
        )
        self.connection.commit()
        update_health("delivery", **self.delivery_diagnostics())
        return trace_id

    def mark_outbox(self, trace_id: str, status: str, error: str | None = None) -> None:
        if status not in {"pending", "sent", "partial", "failed"}:
            raise ValueError(f"unsupported outbox status: {status}")
        now = datetime.now(timezone.utc)
        retry_at: str | None = None
        if status == "failed":
            row = self.connection.execute(
                "SELECT attempts FROM delivery_outbox WHERE trace_id = ?", (trace_id,)
            ).fetchone()
            attempts = int(row[0]) if row else 0
            # Retry quickly after a transient failure, then back off to at
            # most 15 minutes.  The stable trace ID makes an accepted-but-
            # unacknowledged request safe to replay downstream.
            delay_seconds = min(15 * 60, 30 * (2 ** min(attempts, 5)))
            retry_at = (now + timedelta(seconds=delay_seconds)).isoformat()
        self.connection.execute(
            """UPDATE delivery_outbox
               SET status=?, attempts=attempts+1, last_error=?, next_retry_at=?, updated_at=?
               WHERE trace_id=?""",
            (status, error, retry_at, now.isoformat(), trace_id),
        )
        self.connection.commit()
        update_health("delivery", **self.delivery_diagnostics())

    def due_outbox(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return retryable dispatches whose backoff window has elapsed.

        Rows written by older versions may not contain ``dispatch_payload``;
        those remain visible in diagnostics but are intentionally skipped
        because they cannot be reconstructed safely.
        """
        now = datetime.now(timezone.utc).isoformat()
        rows = self.connection.execute(
            """SELECT trace_id, payload_json, status, attempts, updated_at
               FROM delivery_outbox
               WHERE status IN ('pending', 'failed')
                 AND (next_retry_at IS NULL OR next_retry_at <= ?)
               ORDER BY updated_at ASC LIMIT ?""",
            (now, max(1, min(100, int(limit)))),
        ).fetchall()
        due: list[dict[str, Any]] = []
        for trace_id, payload_json, status, attempts, updated_at in rows:
            try:
                payload = json.loads(payload_json)
            except (TypeError, json.JSONDecodeError):
                continue
            dispatch_payload = payload.get("dispatch_payload") if isinstance(payload, dict) else None
            if not isinstance(dispatch_payload, dict):
                continue
            due.append({
                "trace_id": str(trace_id),
                "dispatch_payload": dispatch_payload,
                "status": str(status),
                "attempts": int(attempts),
                "updated_at": str(updated_at),
            })
        return due

    def outbox_state(self, trace_id: str) -> tuple[str, bool] | None:
        """Return status and whether a durable replay body is available."""
        row = self.connection.execute(
            "SELECT status, payload_json FROM delivery_outbox WHERE trace_id = ?", (trace_id,)
        ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row[1])
        except (TypeError, json.JSONDecodeError):
            payload = None
        has_payload = isinstance(payload, dict) and isinstance(payload.get("dispatch_payload"), dict)
        return str(row[0]), has_payload

    def delivery_history(self, db: sqlite3.Connection | None = None, limit: int = 10) -> list[dict[str, Any]]:
        """Return a bounded, non-secret recent delivery history for health checks."""
        database = db or self.connection
        rows = database.execute(
            """SELECT trace_id, source, event_id, category, status, attempts, last_error, updated_at
               FROM delivery_outbox ORDER BY updated_at DESC LIMIT ?""",
            (max(1, min(20, int(limit))),),
        ).fetchall()
        history: list[dict[str, Any]] = []
        for trace_id, source, event_id, category, outbox_status, attempts, last_error, updated_at in rows:
            notification_keys: list[str] = []
            payload_row = database.execute(
                "SELECT payload_json FROM delivery_outbox WHERE trace_id=?", (trace_id,)
            ).fetchone()
            if payload_row:
                try:
                    stored_payload = json.loads(payload_row[0] or "{}")
                except (TypeError, json.JSONDecodeError):
                    stored_payload = {}
                if isinstance(stored_payload, dict):
                    notification_keys = [
                        str(item)[:160] for item in (stored_payload.get("notification_keys") or [])
                        if isinstance(item, str) and item.strip()
                    ][:200]
            receipt = database.execute(
                """SELECT status, delivered_count, failed_count, reported_at, error, updated_at
                   FROM delivery_receipts
                   WHERE trace_id=? AND recipient_hash='__aggregate__'
                   ORDER BY updated_at DESC LIMIT 1""",
                (trace_id,),
            ).fetchone()
            delivered_count = int(receipt[1]) if receipt and receipt[1] is not None else None
            failed_count = int(receipt[2]) if receipt and receipt[2] is not None else None
            reported_at = str(receipt[3]) if receipt and receipt[3] else None
            receipt_updated_at = str(receipt[5]) if receipt else None
            if receipt and (delivered_count is None or failed_count is None):
                try:
                    legacy_counts = json.loads(receipt[4] or "{}")
                except (TypeError, json.JSONDecodeError):
                    legacy_counts = {}
                if isinstance(legacy_counts, dict):
                    delivered_count = delivered_count if delivered_count is not None else _non_negative_int(legacy_counts.get("delivered_count"))
                    failed_count = failed_count if failed_count is not None else _non_negative_int(legacy_counts.get("failed_count"))
                    reported_at = reported_at or (str(legacy_counts.get("reported_at")) if legacy_counts.get("reported_at") else None)
            failed_hash_count = int(database.execute(
                """SELECT COUNT(*) FROM delivery_receipts
                   WHERE trace_id=? AND recipient_hash <> '__aggregate__' AND status='failed'""",
                (trace_id,),
            ).fetchone()[0])
            history.append({
                "trace_id": str(trace_id),
                "source": str(source),
                "event_id": str(event_id),
                "category": str(category) if category else None,
                "outbox_status": str(outbox_status),
                "attempts": int(attempts),
                "last_error": str(last_error) if last_error else None,
                "updated_at": str(updated_at),
                "receipt_status": str(receipt[0]) if receipt else None,
                "delivered_count": delivered_count,
                "failed_count": failed_count,
                "recipient_count": (delivered_count + failed_count) if delivered_count is not None and failed_count is not None else None,
                "reported_at": reported_at,
                "receipt_age_seconds": _age_seconds(receipt_updated_at),
                "failed_recipient_hash_count": failed_hash_count,
                "notification_keys": notification_keys,
            })
        return history

    def delivery_diagnostics(self, db: sqlite3.Connection | None = None) -> dict[str, Any]:
        """Return non-secret delivery state for Railway's health endpoint."""
        database = db or self.connection
        rows = database.execute(
            "SELECT status, COUNT(*) FROM delivery_outbox GROUP BY status"
        ).fetchall()
        counts = {str(status): int(count) for status, count in rows}
        now = datetime.now(timezone.utc).isoformat()
        retryable_count = 0
        due_retry_count = 0
        retry_rows = database.execute(
            """SELECT payload_json, next_retry_at FROM delivery_outbox
               WHERE status IN ('pending', 'failed')"""
        ).fetchall()
        for payload_json, next_retry_at in retry_rows:
            try:
                stored_payload = json.loads(payload_json)
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(stored_payload, dict) or not isinstance(stored_payload.get("dispatch_payload"), dict):
                continue
            retryable_count += 1
            if not next_retry_at or str(next_retry_at) <= now:
                due_retry_count += 1
        latest = database.execute(
            """SELECT trace_id, status, last_error, updated_at
               FROM delivery_outbox ORDER BY updated_at DESC LIMIT 1"""
        ).fetchone()
        latest_receipt = database.execute(
            """SELECT trace_id, status, delivered_count, failed_count, reported_at, error, updated_at
               FROM delivery_receipts
               WHERE recipient_hash='__aggregate__' ORDER BY updated_at DESC LIMIT 1"""
        ).fetchone()
        receipt = database.execute(
            """SELECT trace_id, status, delivered_count, failed_count, reported_at, error, updated_at
               FROM delivery_receipts
               WHERE recipient_hash='__aggregate__' AND trace_id=?
               ORDER BY updated_at DESC LIMIT 1""",
            (latest[0],),
        ).fetchone() if latest else latest_receipt
        recent = self.delivery_history(database, 10)
        outbox_status = str(latest[1]) if latest else None
        receipt_trace_id = str(receipt[0]) if receipt else None
        receipt_status = str(receipt[1]) if receipt else None
        delivered_count = int(receipt[2]) if receipt and receipt[2] is not None else None
        failed_count = int(receipt[3]) if receipt and receipt[3] is not None else None
        reported_at = str(receipt[4]) if receipt and receipt[4] else None
        receipt_updated_at = str(receipt[6]) if receipt else None
        # Older rows encoded these fields in ``error``.  Read them once for
        # compatibility; new rows use dedicated columns for reliable queries.
        if receipt and (delivered_count is None or failed_count is None):
            try:
                legacy_counts = json.loads(receipt[5] or "{}")
            except (TypeError, json.JSONDecodeError):
                legacy_counts = {}
            if isinstance(legacy_counts, dict):
                delivered_count = delivered_count if delivered_count is not None else _non_negative_int(legacy_counts.get("delivered_count"))
                failed_count = failed_count if failed_count is not None else _non_negative_int(legacy_counts.get("failed_count"))
                reported_at = reported_at or (str(legacy_counts.get("reported_at")) if legacy_counts.get("reported_at") else None)
        return {
            "status": receipt_status or outbox_status or "not_checked",
            "last_trace_id": str(latest[0]) if latest else None,
            "last_outbox_status": outbox_status,
            "last_receipt_status": receipt_status,
            "last_receipt_trace_id": receipt_trace_id,
            "receipt_matches_last_outbox": (receipt_trace_id == str(latest[0])) if latest and receipt_trace_id else (False if latest else None),
            "stale_receipt_status": str(latest_receipt[1]) if latest_receipt and receipt_trace_id != str(latest_receipt[0]) else None,
            "counts": counts,
            "retryable_count": retryable_count,
            "due_retry_count": due_retry_count,
            "last_updated_at": receipt_updated_at if receipt else (latest[3] if latest else None),
            "last_error": str(latest[2]) if latest and latest[2] else None,
            "last_delivered_count": delivered_count,
            "last_failed_count": failed_count,
            "last_recipient_count": (delivered_count + failed_count) if delivered_count is not None and failed_count is not None else None,
            "last_reported_at": reported_at,
            "last_receipt_age_seconds": _age_seconds(receipt_updated_at),
            "last_failed_recipient_hash_count": int(database.execute(
                """SELECT COUNT(*) FROM delivery_receipts
                   WHERE trace_id=? AND recipient_hash <> '__aggregate__' AND status='failed'""",
                (receipt_trace_id,),
            ).fetchone()[0]) if receipt_trace_id else 0,
            "recent": recent,
        }

    def prune_delivery_history(self, retention_days: int = 30, limit: int = 500) -> int:
        """Remove bounded, terminal delivery history after the retention window.

        Pending and failed rows are deliberately retained so a transient
        delivery failure remains retryable and auditable.  Only terminal
        ``sent``/``partial`` outbox rows are eligible, and their receipts are
        deleted first because receipts have no foreign-key cascade on older
        Railway volumes.  The limit keeps a single monitor cycle inexpensive.
        """
        days = max(30, int(retention_days))
        batch_size = max(1, min(5000, int(limit)))
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = self.connection.execute(
            """SELECT trace_id FROM delivery_outbox
               WHERE status IN ('sent', 'partial') AND updated_at < ?
               ORDER BY updated_at ASC LIMIT ?""",
            (cutoff, batch_size),
        ).fetchall()
        trace_ids = [str(row[0]) for row in rows]
        if not trace_ids:
            return 0
        placeholders = ",".join("?" for _ in trace_ids)
        self.connection.execute(
            f"DELETE FROM delivery_receipts WHERE trace_id IN ({placeholders})",
            trace_ids,
        )
        self.connection.execute(
            f"DELETE FROM delivery_outbox WHERE trace_id IN ({placeholders})",
            trace_ids,
        )
        self.connection.commit()
        return len(trace_ids)

    def record_delivery_status(self, payload: dict[str, Any]) -> bool:
        """Persist an authenticated GitHub per-run delivery receipt."""
        trace_id = str(payload.get("trace_id") or "").strip()
        receipt_kind = str(payload.get("receipt_kind") or "production").strip()
        status = str(payload.get("delivery_status") or "unknown").strip()
        if receipt_kind not in {"production", "photo_smoke", "creator"}:
            raise ValueError("invalid delivery receipt kind")
        if not trace_id or status not in {"delivered", "partial", "failed"}:
            raise ValueError("invalid delivery receipt")
        failed_hashes = payload.get("failed_recipient_hashes") or []
        if not isinstance(failed_hashes, list) or any(not isinstance(item, str) for item in failed_hashes):
            raise ValueError("invalid failed recipient hashes")
        delivered_count = _non_negative_int(payload.get("delivered_count", 0))
        failed_count = _non_negative_int(payload.get("failed_count", 0))
        if delivered_count is None or failed_count is None:
            raise ValueError("invalid delivery counts")
        reported_at = str(payload.get("reported_at") or "")[:80] or None
        callback_connection = threading.get_ident() != self.owner_thread_id
        db = sqlite3.connect(self.path, timeout=5) if callback_connection else self.connection
        try:
            db.execute("PRAGMA busy_timeout=5000")
            now = datetime.now(timezone.utc).isoformat()
            exists = db.execute(
                "SELECT 1 FROM delivery_outbox WHERE trace_id = ?", (trace_id,)
            ).fetchone()
            if exists is None:
                # A scoped photo smoke test is intentionally emitted before
                # any Railway outbox row exists.  Accept only this explicit,
                # non-production contract.  Production GitHub Actions jobs
                # publish immutable release metadata before the callback, but
                # do not create a Railway outbox row.  The signed callback is
                # therefore allowed to register that row when it carries the
                # complete release/snapshot/alert tuple and explicit origin.
                photo_smoke = (
                    receipt_kind == "photo_smoke"
                    and payload.get("release_id") == "photo-smoke-test"
                    and payload.get("snapshot_id") == "photo-smoke-test"
                    and payload.get("alert_id") == "photo-smoke-test"
                    and payload.get("delivery_mode") == "photo"
                )
                creator_receipt = (
                    receipt_kind == "creator"
                    and payload.get("receipt_origin") == "github_actions"
                    and bool(payload.get("release_id"))
                    and bool(payload.get("snapshot_id"))
                    and bool(payload.get("alert_id"))
                    and payload.get("delivery_mode") in {"photo", "text"}
                )
                production_receipt = (
                    receipt_kind == "production"
                    and payload.get("receipt_origin") == "github_actions"
                    and bool(payload.get("release_id"))
                    and bool(payload.get("snapshot_id"))
                    and bool(payload.get("alert_id"))
                    and payload.get("delivery_mode") in {"text", "photo"}
                )
                if not (photo_smoke or creator_receipt or production_receipt):
                    logging.warning("delivery receipt for unknown trace_id=%s", trace_id)
                    return False
                smoke_payload = {
                    "receipt_kind": receipt_kind,
                    "receipt_origin": payload.get("receipt_origin"),
                    "release_id": payload.get("release_id"),
                    "snapshot_id": payload.get("snapshot_id"),
                    "alert_id": payload.get("alert_id"),
                    "delivery_mode": payload.get("delivery_mode"),
                    "notification_keys": [
                        str(item)[:160] for item in (payload.get("notification_keys") or [])
                        if isinstance(item, str) and item.strip()
                    ][:200],
                }
                db.execute(
                    """INSERT INTO delivery_outbox(
                        trace_id,canonical_key,source,event_id,category,payload_json,
                        status,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?, ?, ?)""",
                    (
                        trace_id,
                        (
                            f"photo-smoke:{trace_id}"
                            if photo_smoke
                            else f"github-actions:{payload.get('alert_id')}"
                        ),
                        "github_actions",
                        payload.get("alert_id") or "photo-smoke-test",
                        "photo_smoke" if photo_smoke else "creator_receipt" if creator_receipt else "production_receipt",
                        json.dumps(smoke_payload, ensure_ascii=False, sort_keys=True),
                        status,
                        now,
                        now,
                    ),
                )
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
                """INSERT OR REPLACE INTO delivery_receipts(
                    trace_id,recipient_hash,status,error,delivered_count,failed_count,reported_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?)""",
                (trace_id, "__aggregate__", status, None, delivered_count, failed_count, reported_at, now),
            )
            db.commit()
            update_health("delivery", **self.delivery_diagnostics(db))
            return True
        finally:
            if callback_connection:
                db.close()

    def release_classification(self, event_id: str, error: str) -> None:
        """Return a failed dispatch to the retryable state."""
        store_release_classification(self.connection, event_id, error)

    def add_if_new(self, event_id: str) -> bool:
        """Backward-compatible insert helper for callers outside the poll loop."""
        return store_add_if_new(self.connection, event_id)

    def claim_classification(self, event_id: str, classification: str) -> bool:
        """Claim an event once, while allowing legacy unknown rows to retry.

        The old monitor inserted every ID before classification.  That made a
        transiently unrecognised headline permanent and explains why adding a
        better keyword later did not recover the missed Trump/Iran event.  A
        row in ``unclassified`` is deliberately re-claimable; once it becomes
        in-scope, out-of-scope, or baseline it is stable and will not loop.
        """
        return store_claim_classification(self.connection, event_id, classification)

    def classification_for(self, event_id: str) -> str | None:
        return store_classification_for(self.connection, event_id)

    def set_classification(self, event_id: str, classification: str) -> None:
        """Finalize a claimed event (used for first-cycle baseline rows)."""
        store_set_classification(self.connection, event_id, classification)

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


def build_dispatch_payload(alert: Alert, trace_id: str | None = None) -> dict[str, Any]:
    """Build the exact repository-dispatch body persisted in the outbox."""
    stable_trace_id = trace_id or alert_trace_id(alert)
    return {
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
            "trace_id": stable_trace_id,
        },
    }


def sign_dispatch_payload(payload: dict[str, Any], alert: Alert, shared_secret: str) -> dict[str, Any]:
    """Attach the HMAC after restoring a serialized outbox payload."""
    client_payload = payload.setdefault("client_payload", {})
    client_payload["signature"] = sign(alert, shared_secret)
    return payload


async def dispatch_repository_payload(
    payload: dict[str, Any], *, token: str, repository: str, trace_id: str,
) -> None:
    await send_repository_payload(
        payload,
        token=token,
        repository=repository,
        trace_id=trace_id,
        api_version=GITHUB_API_VERSION,
    )


async def dispatch_alert(alert: Alert, *, token: str, repository: str, shared_secret: str) -> None:
    trace_id = alert_trace_id(alert)
    payload = sign_dispatch_payload(build_dispatch_payload(alert, trace_id), alert, shared_secret)
    await dispatch_repository_payload(payload, token=token, repository=repository, trace_id=trace_id)


async def retry_due_outbox(
    store: SeenStore, *, token: str, repository: str, shared_secret: str,
) -> int:
    """Replay durable dispatches that survived a transient source/network failure."""
    batch_size = max(1, min(100, int(os.environ.get("OUTBOX_RETRY_BATCH", "20"))))
    retried = 0
    for item in store.due_outbox(batch_size):
        trace_id = item["trace_id"]
        try:
            await dispatch_repository_payload(
                item["dispatch_payload"],
                token=token,
                repository=repository,
                trace_id=trace_id,
            )
        except Exception as error:
            store.mark_outbox(trace_id, "failed", type(error).__name__)
            logging.exception("outbox retry failed trace_id=%s; backoff scheduled", trace_id)
            continue
        store.mark_outbox(trace_id, "sent")
        retried += 1
        logging.info("outbox retry delivered trace_id=%s", trace_id)
    if retried:
        update_health("delivery", **store.delivery_diagnostics())
    return retried


async def dispatch_monitor_health(*, token: str, repository: str, gdelt: dict[str, Any]) -> None:
    """Publish non-secret GDELT pending diagnostics for the Mini App.

    This is deliberately a separate repository-dispatch event: pending
    candidates are not alerts and must never enter the Telegram path. Only
    bounded counts/reason codes are sent; article bodies, URLs and secrets
    stay inside Railway's local audit store.
    """
    global _HEALTH_DISPATCH_BACKOFF_UNTIL, _HEALTH_DISPATCH_BACKOFF_STATUS, _HEALTH_DISPATCH_BACKOFF_ERROR, _HEALTH_DISPATCH_BACKOFF_NEXT_AT
    if not token or not repository:
        update_health(
            "gdelt",
            health_dispatch_status="configuration_missing",
            health_dispatch_error="missing_github_dispatch_configuration",
            health_dispatch_next_retry_at=None,
        )
        logging.warning("monitor health dispatch skipped: GitHub credentials are not configured")
        return
    if time.monotonic() < _HEALTH_DISPATCH_BACKOFF_UNTIL:
        update_health(
            "gdelt",
            health_dispatch_status=_HEALTH_DISPATCH_BACKOFF_STATUS,
            health_dispatch_error=_HEALTH_DISPATCH_BACKOFF_ERROR,
            health_dispatch_next_retry_at=_HEALTH_DISPATCH_BACKOFF_NEXT_AT,
        )
        logging.info("monitor health dispatch backoff active status=%s", _HEALTH_DISPATCH_BACKOFF_STATUS)
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
                    _HEALTH_DISPATCH_BACKOFF_UNTIL = time.monotonic() + 60
                    _HEALTH_DISPATCH_BACKOFF_STATUS = "degraded"
                    _HEALTH_DISPATCH_BACKOFF_ERROR = type(exc).__name__
                    _HEALTH_DISPATCH_BACKOFF_NEXT_AT = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
                    update_health("gdelt", health_dispatch_status="degraded", health_dispatch_error=type(exc).__name__, health_dispatch_next_retry_at=_HEALTH_DISPATCH_BACKOFF_NEXT_AT)
                    logging.warning("monitor health dispatch unavailable error=%s", type(exc).__name__)
                    return
                await asyncio.sleep(2**attempt)
                continue
            if response.status_code in {401, 403}:
                # This callback is observability only.  A repository token
                # without dispatch permission must not crash or spin the
                # source monitor; local Railway health remains authoritative.
                _HEALTH_DISPATCH_BACKOFF_UNTIL = time.monotonic() + 900
                _HEALTH_DISPATCH_BACKOFF_STATUS = "configuration_missing" if response.status_code == 401 else "permission_denied"
                _HEALTH_DISPATCH_BACKOFF_ERROR = f"HTTP_{response.status_code}"
                _HEALTH_DISPATCH_BACKOFF_NEXT_AT = (datetime.now(timezone.utc) + timedelta(seconds=900)).isoformat()
                update_health(
                    "gdelt", health_dispatch_status=_HEALTH_DISPATCH_BACKOFF_STATUS,
                    health_dispatch_error=_HEALTH_DISPATCH_BACKOFF_ERROR,
                    health_dispatch_next_retry_at=_HEALTH_DISPATCH_BACKOFF_NEXT_AT,
                )
                logging.warning("monitor health dispatch rejected status=%s; local health retained", response.status_code)
                return
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == 2:
                    _HEALTH_DISPATCH_BACKOFF_UNTIL = time.monotonic() + 300
                    _HEALTH_DISPATCH_BACKOFF_STATUS = "degraded"
                    _HEALTH_DISPATCH_BACKOFF_ERROR = f"HTTP_{response.status_code}"
                    _HEALTH_DISPATCH_BACKOFF_NEXT_AT = (datetime.now(timezone.utc) + timedelta(seconds=300)).isoformat()
                    update_health("gdelt", health_dispatch_status="degraded", health_dispatch_error=_HEALTH_DISPATCH_BACKOFF_ERROR, health_dispatch_next_retry_at=_HEALTH_DISPATCH_BACKOFF_NEXT_AT)
                    logging.warning("monitor health dispatch rate-limited/unavailable status=%s", response.status_code)
                    return
                retry_after = 0
                try:
                    retry_after = int(response.headers.get("Retry-After", "0"))
                except (TypeError, ValueError):
                    retry_after = 0
                await asyncio.sleep(min(60, max(1, retry_after)) if retry_after else 2**attempt)
                continue
            response.raise_for_status()
            _HEALTH_DISPATCH_BACKOFF_UNTIL = 0.0
            _HEALTH_DISPATCH_BACKOFF_STATUS = "not_checked"
            _HEALTH_DISPATCH_BACKOFF_ERROR = None
            _HEALTH_DISPATCH_BACKOFF_NEXT_AT = None
            update_health("gdelt", health_dispatch_status="healthy", health_dispatch_error=None, health_dispatch_next_retry_at=None)
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


_GDELT_BACKOFF_UNTIL = 0.0
_GDELT_FAILURE_COUNT = 0
_GDELT_LAST_FETCH_STATE = "unknown"
_GDELT_LAST_FETCH_ERROR: str | None = None
_HEALTH_DISPATCH_BACKOFF_UNTIL = 0.0
_HEALTH_DISPATCH_BACKOFF_STATUS = "not_checked"
_HEALTH_DISPATCH_BACKOFF_ERROR: str | None = None
_HEALTH_DISPATCH_BACKOFF_NEXT_AT: str | None = None
GDELT_USER_AGENT = (
    "PRStK-Stock-Detector/1.0 "
    "(+https://github.com/hanjhou2000716/prstklab-stk-detector)"
)


def gdelt_error_label(error: BaseException) -> str:
    """Return a safe, stable provider error label for health diagnostics."""
    if isinstance(error, httpx.HTTPStatusError) and error.response is not None:
        return f"HTTP_{error.response.status_code}"
    if isinstance(error, httpx.TimeoutException):
        return "timeout"
    if isinstance(error, json.JSONDecodeError):
        return "invalid_json"
    if isinstance(error, ValueError):
        return "invalid_payload"
    return type(error).__name__


async def fetch_gdelt_articles(store: SeenStore | None = None) -> list[DiscoveryArticle]:
    """Fetch discovery headlines with a 15-minute cache and 120-minute fallback."""
    global _GDELT_BACKOFF_UNTIL, _GDELT_FAILURE_COUNT, _GDELT_LAST_FETCH_STATE, _GDELT_LAST_FETCH_ERROR
    fresh_cache_seconds = max(60, int(os.environ.get("GDELT_CACHE_MINUTES", "15")) * 60)
    stale_cache_seconds = max(fresh_cache_seconds, int(os.environ.get("GDELT_STALE_CACHE_MINUTES", "120")) * 60)
    fresh_age_seconds = max(60, int(os.environ.get("GDELT_MAX_FRESH_AGE_MINUTES", "45")) * 60)
    if store:
        cached = store.read_cache("gdelt-success", fresh_cache_seconds)
        if cached is not None:
            _GDELT_LAST_FETCH_STATE = "fresh_cache"
            _GDELT_LAST_FETCH_ERROR = None
            return _decode_discovery_articles(cached)
    now = time.monotonic()
    if now < _GDELT_BACKOFF_UNTIL:
        if store:
            stale = store.read_cache("gdelt-success", stale_cache_seconds)
            if stale is not None:
                logging.warning("GDELT backoff active; using cached success until next retry window")
                _GDELT_LAST_FETCH_STATE = "stale_cache"
                return _decode_discovery_articles(stale)
        _GDELT_LAST_FETCH_STATE = "failed"
        _GDELT_LAST_FETCH_ERROR = "rate_limited"
        raise RuntimeError("GDELT backoff active after rate limit")
    params = {"query": os.environ.get("GDELT_QUERY", GDELT_QUERY), "mode": "artlist", "format": "json", "sort": "datedesc", "maxrecords": 75}
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={
            "Accept": "application/json",
            "User-Agent": GDELT_USER_AGENT,
        }) as client:
            response = await client.get(GDELT_DOC_URL, params=params)
        if response.status_code == 429:
            retry_after = 0
            try:
                retry_after = int(response.headers.get("Retry-After", "0"))
            except (TypeError, ValueError):
                retry_after = 0
            _GDELT_FAILURE_COUNT = min(_GDELT_FAILURE_COUNT + 1, 6)
            delay = min(900, max(60, retry_after or 60 * (2 ** (_GDELT_FAILURE_COUNT - 1))))
            _GDELT_BACKOFF_UNTIL = time.monotonic() + delay
            response.raise_for_status()
        response.raise_for_status()
        _GDELT_FAILURE_COUNT = 0
        _GDELT_BACKOFF_UNTIL = 0.0
        _GDELT_LAST_FETCH_STATE = "live"
        _GDELT_LAST_FETCH_ERROR = None
    except Exception as error:
        _GDELT_LAST_FETCH_ERROR = gdelt_error_label(error)
        if store:
            stale = store.read_cache("gdelt-success", stale_cache_seconds)
            if stale is not None:
                logging.warning("GDELT temporarily unavailable; using the most recent cached success")
                _GDELT_LAST_FETCH_STATE = "stale_cache"
                return _decode_discovery_articles(stale)
        _GDELT_LAST_FETCH_STATE = "failed"
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


def _health_request_path(request_target: str) -> str:
    """Compatibility wrapper for the standalone health contract."""
    return health_request_path(request_target)


def _gmail_health_fields(diagnostics: Any) -> dict[str, Any]:
    """Compatibility wrapper for the standalone Gmail health projection."""
    return gmail_health_fields(diagnostics)


def configure_gmail_ingress() -> None:
    """Attach the bounded Gmail Pub/Sub ingress when the Railway worker starts."""
    global EMAIL_INGRESS
    EMAIL_INGRESS, fields = build_gmail_ingress()
    update_health("gmail", **fields)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        # Monitoring probes and browser cache-busting commonly append a
        # query string.  Route by the URL path, not the raw request target, so
        # `/health?ts=...` remains the same public health endpoint.
        request_path = _health_request_path(self.path)
        if request_path not in {"/", "/health"}:
            self.send_error(404)
            return
        body = (json.dumps(health_snapshot(), ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if _health_request_path(self.path) == "/gmail/push":
            if EMAIL_INGRESS is None:
                self.send_error(503, "gmail ingress is unavailable")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > 256 * 1024:
                    self.send_error(413, "push body too large")
                    return
                body = self.rfile.read(length)
                headers = {str(key).lower(): str(value) for key, value in self.headers.items()}
                EMAIL_INGRESS.accept_push(body, headers)
                diagnostics = EMAIL_INGRESS.health()
                update_health(
                    "gmail",
                    status="healthy",
                    **_gmail_health_fields(diagnostics),
                    error=None,
                )
                response = b'{"accepted":true}\n'
                self.send_response(204)
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                return
            except Exception as error:
                # Never echo bearer tokens, message IDs or request bodies.
                update_health("gmail", status="failed", error=type(error).__name__)
                code = 401 if type(error).__name__ in {"GmailIngressError"} else 400
                self.send_error(code, "gmail push rejected")
                return
        if _health_request_path(self.path) == "/creator-delivery-history":
            secret = _delivery_shared_secret()
            if not secret:
                self.send_error(503, "delivery callback is not configured")
                return
            try:
                length = min(int(self.headers.get("Content-Length", "0")), 16 * 1024)
                body = self.rfile.read(length)
                supplied = self.headers.get("X-PRSTK-Signature", "")
                expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
                if not hmac.compare_digest(supplied, expected):
                    self.send_error(401)
                    return
                payload = json.loads(body.decode("utf-8"))
                if str(payload.get("receipt_kind") or "") != "creator":
                    self.send_error(400, "invalid receipt kind")
                    return
                limit = max(1, min(200, int(payload.get("limit", 200))))
                history = DELIVERY_STORE.delivery_history(limit=limit) if DELIVERY_STORE is not None else []
                keys = list(dict.fromkeys(
                    str(item)[:160]
                    for row in history
                    if row.get("category") == "creator_receipt"
                    for item in (row.get("notification_keys") or [])
                    if isinstance(item, str) and item.strip()
                ))[:200]
                response = (json.dumps({"receipt_kind": "creator", "notification_keys": keys}, ensure_ascii=False) + "\n").encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
                return
            except (ValueError, TypeError, json.JSONDecodeError):
                self.send_error(400, "invalid delivery history request")
                return
            except Exception:
                logging.exception("creator delivery history request failed")
                self.send_error(500)
                return
        if _health_request_path(self.path) != "/delivery-status":
            self.send_error(404)
            return
        secret = _delivery_shared_secret()
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
    configure_gmail_ingress()
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logging.info("Health endpoint listening on port %s", port)


async def monitor_forever() -> None:
    settings = load_poll_settings(configured=configured, cooldown_seconds=EVENT_COOLDOWN_SECONDS)
    jin10_token = settings.jin10_token
    github_token = settings.github_token
    repository = settings.repository
    shared_secret = settings.shared_secret
    interval = settings.interval
    limit = settings.limit
    cooldown = settings.cooldown
    bootstrap = settings.bootstrap
    gdelt_interval = settings.gdelt_interval
    gdelt_enabled = settings.gdelt_enabled
    update_health("gdelt", enabled=gdelt_enabled, poll_seconds=gdelt_interval,
                  status="disabled" if not gdelt_enabled else "not_checked")
    store = SeenStore(Path(os.environ.get("MONITOR_STATE_PATH", "/data/jin10-monitor.sqlite3")))
    global DELIVERY_STORE
    DELIVERY_STORE = store
    update_health(
        "delivery",
        **store.delivery_diagnostics(),
        retention_days=30,
        last_pruned_at=None,
        last_pruned_count=0,
    )
    first_cycle = True
    gdelt_baseline = True
    last_gdelt_poll = 0.0
    update_health(
        "monitor",
        status="running",
        poll_interval_seconds=interval,
        last_cycle_started_at=None,
        last_cycle_completed_at=None,
    )

    while True:
        cycle_started_at = datetime.now(timezone.utc).isoformat()
        update_health(
            "monitor",
            status="running",
            poll_interval_seconds=interval,
            last_cycle_started_at=cycle_started_at,
        )
        try:
            pruned_delivery_count = store.prune_delivery_history()
            # Keep the event ledger's existing 30-day retention policy active
            # as well; both cleanups are bounded and independent of source
            # polling so a stale feed cannot block maintenance.
            store.prune_event_ledger()
            maintenance_health = {
                "retention_days": 30,
                "last_pruned_count": pruned_delivery_count,
            }
            if pruned_delivery_count:
                maintenance_health["last_pruned_at"] = datetime.now(timezone.utc).isoformat()
            update_health("delivery", **store.delivery_diagnostics(), **maintenance_health)
            if pruned_delivery_count:
                logging.info(
                    "Delivery history retention cleanup removed %s terminal row(s)",
                    pruned_delivery_count,
                )
        except Exception:
            # Maintenance must never stop a fresh source poll or a retry pass.
            logging.exception("Delivery history retention cleanup failed; continuing monitor cycle")
        try:
            retried = await retry_due_outbox(
                store,
                token=github_token,
                repository=repository,
                shared_secret=shared_secret,
            )
            if retried:
                logging.info("Durable outbox retry completed: %s dispatch(es) delivered", retried)
        except Exception:
            # A retry pass must never prevent fresh Jin10/GDELT polling.
            logging.exception("Durable outbox retry pass failed; continuing source polling")
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
                if not classifier_delivery_allowed():
                    store.set_classification_reason(flash.event_id, "noncanonical_classifier")
                    logging.warning(
                        "Jin10 alert held: repository-shared event classifier is unavailable"
                    )
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
                existing_outbox = store.outbox_state(alert_trace_id(alert))
                if existing_outbox and existing_outbox[0] in {"sent", "partial"}:
                    # A durable retry (or an earlier successful attempt) has
                    # already reached GitHub.  Do not send the same event via
                    # the fresh-source path again.
                    store.set_classification(flash.event_id, "in_scope")
                    store.set_classification_reason(flash.event_id, "already_delivered_outbox")
                    store.record_dispatch(alert)
                    store.mark_alert_reminded(alert, escalated=("\u9ad8\u98a8\u96aa" in alert.summary))
                    continue
                if existing_outbox and existing_outbox[1] and existing_outbox[0] in {"pending", "failed"}:
                    store.set_classification_reason(flash.event_id, "durable_outbox_pending_retry")
                    logging.info(
                        "Jin10 alert held by durable outbox trace_id=%s status=%s",
                        alert_trace_id(alert), existing_outbox[0],
                    )
                    continue
                trace_id = alert_trace_id(alert)
                dispatch_payload = sign_dispatch_payload(
                    build_dispatch_payload(alert, trace_id), alert, shared_secret
                )
                trace_id = store.record_outbox(alert, {
                    "source": alert.source, "event_id": alert.event_id,
                    "category": alert.category, "summary": alert.summary,
                    "occurred_at": alert.occurred_at,
                    "dispatch_payload": dispatch_payload,
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
                # A stale cache can keep the discovery pane useful, but it is
                # never eligible to create a new Telegram alert.  The source
                # health payload records the fallback explicitly so the UI
                # cannot mistake cached headlines for a live confirmation.
                stale_cache_used = _GDELT_LAST_FETCH_STATE == "stale_cache"
                alerts = [] if stale_cache_used else cross_checked_gdelt_alerts(articles, market_sync)
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
                    existing_outbox = store.outbox_state(alert_trace_id(alert))
                    if existing_outbox and existing_outbox[0] in {"sent", "partial"}:
                        store.set_classification(alert.event_id, "in_scope")
                        store.set_classification_reason(alert.event_id, "already_delivered_outbox")
                        store.record_dispatch(alert)
                        store.mark_alert_reminded(alert, escalated=("\u9ad8\u98a8\u96aa" in alert.summary))
                        continue
                    if existing_outbox and existing_outbox[1] and existing_outbox[0] in {"pending", "failed"}:
                        store.set_classification_reason(alert.event_id, "durable_outbox_pending_retry")
                        logging.info(
                            "GDELT alert held by durable outbox trace_id=%s status=%s",
                            alert_trace_id(alert), existing_outbox[0],
                        )
                        continue
                    trace_id = alert_trace_id(alert)
                    dispatch_payload = sign_dispatch_payload(
                        build_dispatch_payload(alert, trace_id), alert, shared_secret
                    )
                    trace_id = store.record_outbox(alert, {
                        "source": alert.source, "event_id": alert.event_id,
                        "category": alert.category, "summary": alert.summary,
                        "occurred_at": alert.occurred_at,
                        "dispatch_payload": dispatch_payload,
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
                if stale_cache_used:
                    pending_reasons["stale_source_cache"] = pending_reasons.get("stale_source_cache", 0) + len(articles)
                logging.info(
                    "GDELT cross-check completed: %s article(s), %s alert(s) dispatched, %s candidate(s) pending",
                    len(articles), dispatched, len(pending),
                )
                now_iso = datetime.now(timezone.utc).isoformat()
                health_values: dict[str, Any] = {
                    "status": "fallback_active" if stale_cache_used else "healthy",
                    "article_count": len(articles),
                    "alert_count": dispatched,
                    "market_sync_status": "confirmed" if any(alert.market_sync_confirmed for alert in alerts) else "not_confirmed",
                    "pending_count": len(pending),
                    "pending_reasons": pending_reasons,
                    "stale_cache_used": stale_cache_used,
                    "error": _GDELT_LAST_FETCH_ERROR if stale_cache_used else None,
                }
                if stale_cache_used:
                    health_values["last_failure_at"] = now_iso
                else:
                    health_values["last_success_at"] = now_iso
                update_health("gdelt", **health_values)
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
                              error=gdelt_error_label(error))
                logging.exception("GDELT discovery failed; will wait for the next interval")
                try:
                    await dispatch_monitor_health(
                        token=github_token,
                        repository=repository,
                        gdelt=health_snapshot().get("gdelt", {}),
                    )
                except Exception:
                    logging.exception("GDELT failure health publication failed")
        cycle_completed_at = datetime.now(timezone.utc).isoformat()
        update_health("monitor", status="running", last_cycle_completed_at=cycle_completed_at)
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
