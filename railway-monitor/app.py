"""Railway bridge: Jin10 MCP Flash -> signed GitHub repository_dispatch.

The service intentionally performs no scraping.  It calls Jin10's official MCP
``list_flash`` tool, records seen IDs locally, and only forwards in-scope events.
GitHub independently verifies the HMAC signature and de-duplicates the event.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunsplit

import httpx


JIN10_MCP_URL = "https://mcp.jin10.com/mcp"
GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_QUERY = '(war OR invasion OR ceasefire OR sanctions OR Hormuz OR tariff OR "export controls" OR semiconductor OR earthquake OR tsunami OR cyberattack OR ransomware OR pandemic OR Bitcoin OR Ethereum OR Trump OR "cancel attack" OR "call off attack" OR Iran OR "White House")'
GITHUB_API_VERSION = "2022-11-28"
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

# These are deliberately conservative.  A flash must contain one of these
# expressions before it can create a public alert; everything else is merely
# marked as seen and never forwarded.
CATEGORY_KEYWORDS = {
    "fed": ("fomc", "federal reserve", "powell", "聯準會", "美联储", "鮑威爾", "鲍威尔"),
    "macro": ("cpi", "pce", "非農", "非农", "失業率", "失业率", "gdp", "通膨", "通胀"),
    "policy": ("關稅", "关税", "制裁", "出口管制", "政策", "tariff", "sanction", "duties", "duty", "trade war"),
    "conflict": ("戰爭", "战争", "軍事", "军事", "導彈", "导弹", "停火", "中東", "中东", "伊朗", "以色列", "特朗普", "川普", "攻擊", "攻击", "襲擊", "袭击", "空襲", "空袭", "進攻", "进攻", "軍事行動", "军事行动", "invasion", "iran", "israel", "ukraine", "russia", "trump", "truce", "ceasefire", "airstrike", "attack"),
    "energy": ("wti", "brent", "原油", "油價", "油价", "opec", "crude oil", "oil supply"),
    "semiconductor": ("nvidia", "輝達", "英伟达", "台積電", "台积电", "tsmc", "半導體", "半导体"),
    "market": ("熔斷", "熔断", "閃崩", "闪崩", "crash", "circuit breaker"),
}
ESCALATION_TERMS = (
    "擴大", "升级", "升級", "加徵", "加征", "大幅", "急升", "急跌", "供應中斷", "供应中断",
    "additional", "increase", "airstrike", "missile", "attack", "supply disruption", "supply cut",
)

# A discovery item is never sufficient on its own. GDELT candidates must have
# two independent domains from this conservative set and share a concrete
# event anchor before they can reach the signed GitHub dispatch bridge.
TRUSTED_NEWS_DOMAINS = {
    "reuters.com", "apnews.com", "bloomberg.com", "ft.com", "wsj.com",
    "nytimes.com", "bbc.com", "cnbc.com", "nikkei.com",
}
DISCOVERY_ANCHORS = {
    "conflict": ("iran", "israel", "ukraine", "russia", "hormuz", "taiwan"),
    "policy": ("tariff", "sanction", "export control", "duties"),
    "energy": ("wti", "brent", "oil", "opec", "crude"),
    "semiconductor": ("nvidia", "tsmc", "asml", "semiconductor"),
    "black_swan": ("earthquake", "tsunami", "ransomware", "cyberattack", "pandemic"),
    "material_positive": ("iran", "israel", "ukraine", "russia", "trump", "ceasefire", "truce", "peace deal", "tariff exemption", "rate cut", "cancel attack", "call off attack"),
}

# GDELT is only a discovery feed.  Two headlines must describe the same
# actor/place and the same action, rather than merely repeat a broad topic.
# The small vocabulary is deliberately conservative: a missed headline is
# preferable to publishing a misleading same-topic alert.
DISCOVERY_ENTITIES = (
    "iran", "israel", "ukraine", "russia", "taiwan", "japan", "china", "hormuz",
    "trump", "powell", "netanyahu", "putin", "zelenskyy", "nvidia", "tsmc", "asml",
)
DISCOVERY_ENTITY_ANCHORS = {"nvidia", "tsmc", "asml"}
DISCOVERY_ACTIONS = {
    "conflict": ("conflict", "war", "attack", "airstrike", "invasion", "missile", "ceasefire", "truce", "military action"),
    "policy": ("tariff", "sanction", "export control", "duties", "ban", "restriction"),
    "energy": ("oil", "supply", "production", "opec", "output", "disruption"),
    "semiconductor": ("earnings", "guidance", "export control", "restriction", "capex", "forecast"),
    "material_positive": ("ceasefire", "truce", "peace deal", "tariff exemption", "rate cut", "attack", "cancel attack", "cancel attacks", "cancels attack", "canceled attack", "cancelled attack", "call off attack", "halt attack"),
    "black_swan": ("earthquake", "tsunami", "ransomware", "cyberattack", "pandemic"),
}

# Public, non-secret runtime diagnostics for Railway's /health endpoint.  This
# deliberately contains timestamps, counts and error classes only; credentials
# and response bodies never enter the health payload.
HEALTH_LOCK = threading.Lock()
HEALTH_STATE: dict[str, Any] = {
    "status": "ok",
    "service": "prstk-jin10-monitor",
    "started_at": datetime.now(timezone.utc).isoformat(),
    "jin10": {"status": "not_checked", "last_success_at": None, "last_failure_at": None, "item_count": 0, "error": None},
    "gdelt": {"enabled": True, "status": "not_checked", "last_success_at": None, "last_failure_at": None, "article_count": 0, "alert_count": 0, "error": None},
}
DELIVERY_STORE: SeenStore | None = None


def update_health(component: str, **values: Any) -> None:
    with HEALTH_LOCK:
        HEALTH_STATE.setdefault(component, {}).update(values)


def health_snapshot() -> dict[str, Any]:
    with HEALTH_LOCK:
        return json.loads(json.dumps(HEALTH_STATE))


# These require a confirmed, broadly material event. They deliberately are not
# a catch-all for ordinary geopolitical headlines or routine market moves.
BLACK_SWAN_TERMS = (
    "major earthquake", "magnitude 7", "magnitude 8", "tsunami", "nuclear accident",
    "重大地震", "強震", "規模7", "規模8", "海嘯", "核事故", "大規模停電",
    "金融危機", "銀行擠兌", "交易所遭駭", "重大駭客", "circuit breaker",
)
MATERIAL_POSITIVE_TERMS = (
    "ceasefire agreement", "ceasefire", "truce agreement", "peace deal",
    "tariff exemption", "tariff removal", "rate cut", "cancel attack", "cancel attacks",
    "cancels attack", "canceled attack", "cancelled attack", "call off attack", "call off attacks",
    "calls off attack", "called off attack", "halt attack", "halt attacks", "agreed to cancel",
    "停火協議", "停火", "休戰協議", "和平協議", "關稅豁免", "取消關稅", "降息",
    "取消攻擊", "取消對伊朗的攻擊", "取消對伊朗攻擊", "撤回攻擊", "停止攻擊", "暫停攻擊",
    "撤回軍事行動", "停止軍事行動", "戰事降溫", "战事降温",
)


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

    @property
    def evidence_payload(self) -> list[dict[str, str]]:
        return [
            {"domain": item.domain, "url": item.url, "seen_at": item.seen_at}
            for item in sorted(self.evidence, key=lambda item: (item.domain, item.url, item.seen_at))
        ]

    @property
    def canonical(self) -> str:
        trace = json.dumps(self.evidence_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return "\n".join((self.source, self.event_id, self.category, self.summary, self.occurred_at, trace))


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
    identity = "|".join((alert.category, facts["person"], facts["location"], facts["action"], alert.occurred_at[:13]))
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


def configured(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required Railway variable: {name}")
    return value


def classify_flash(flash: Flash) -> str | None:
    haystack = flash.text.casefold()
    if any(keyword.casefold() in haystack for keyword in BLACK_SWAN_TERMS):
        return "black_swan"
    if any(keyword.casefold() in haystack for keyword in MATERIAL_POSITIVE_TERMS):
        return "material_positive"
    # Oil headlines are material only when supply, a large move, or a
    # geopolitical catalyst is also present. This avoids routine daily oil
    # commentary becoming a Telegram emergency alert.
    if any(keyword.casefold() in haystack for keyword in CATEGORY_KEYWORDS["energy"]):
        material_energy_terms = ("iran", "israel", "中東", "中东", "supply", "供應", "供给", "opec", "attack", "戰爭", "战争", "停火", "ceasefire", "truce", "%")
        if any(term.casefold() in haystack for term in material_energy_terms):
            return "energy"
    for category, keywords in CATEGORY_KEYWORDS.items():
        if category == "energy":
            continue
        if any(keyword.casefold() in haystack for keyword in keywords):
            return category
    return None


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
    category = classify_flash(flash)
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
        self.connection = sqlite3.connect(path)
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
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                last_error TEXT
            )"""
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

    def record_incoming_flash(self, flash: Flash) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.connection.execute(
            """INSERT INTO incoming_events(event_id,source,title,content,occurred_at,first_seen_at,last_seen_at)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(event_id) DO UPDATE SET title=excluded.title, content=excluded.content,
                 occurred_at=excluded.occurred_at, last_seen_at=excluded.last_seen_at""",
            (flash.event_id, "jin10", flash.title, flash.content, flash.occurred_at, now, now),
        )
        self.connection.commit()

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
        return trace_id

    def mark_outbox(self, trace_id: str, status: str, error: str | None = None) -> None:
        if status not in {"pending", "sent", "partial", "failed"}:
            raise ValueError(f"unsupported outbox status: {status}")
        self.connection.execute(
            "UPDATE delivery_outbox SET status=?, attempts=attempts+1, last_error=?, updated_at=? WHERE trace_id=?",
            (status, error, datetime.now(timezone.utc).isoformat(), trace_id),
        )
        self.connection.commit()

    def record_delivery_status(self, payload: dict[str, Any]) -> bool:
        """Persist an authenticated GitHub per-run delivery receipt."""
        trace_id = str(payload.get("trace_id") or "").strip()
        status = str(payload.get("delivery_status") or "unknown").strip()
        if not trace_id or status not in {"delivered", "partial", "failed"}:
            raise ValueError("invalid delivery receipt")
        failed_hashes = payload.get("failed_recipient_hashes") or []
        if not isinstance(failed_hashes, list) or any(not isinstance(item, str) for item in failed_hashes):
            raise ValueError("invalid failed recipient hashes")
        now = datetime.now(timezone.utc).isoformat()
        exists = self.connection.execute(
            "SELECT 1 FROM delivery_outbox WHERE trace_id = ?", (trace_id,)
        ).fetchone()
        if exists is None:
            logging.warning("delivery receipt for unknown trace_id=%s", trace_id)
            return False
        self.connection.execute(
            "UPDATE delivery_outbox SET status=?, last_error=?, updated_at=? WHERE trace_id=?",
            (status, None if status == "delivered" else "recipient delivery incomplete", now, trace_id),
        )
        for recipient_hash in failed_hashes:
            self.connection.execute(
                "INSERT OR REPLACE INTO delivery_receipts(trace_id,recipient_hash,status,error,updated_at) VALUES(?,?,?,?,?)",
                (trace_id, recipient_hash[:128], "failed", "recipient delivery failed", now),
            )
        self.connection.execute(
            "INSERT OR REPLACE INTO delivery_receipts(trace_id,recipient_hash,status,error,updated_at) VALUES(?,?,?,?,?)",
            (trace_id, "__aggregate__", status, json.dumps({
                "delivered_count": payload.get("delivered_count", 0),
                "failed_count": payload.get("failed_count", 0),
                "reported_at": payload.get("reported_at"),
            }, ensure_ascii=False), now),
        )
        self.connection.commit()
        return True

    def release_classification(self, event_id: str, error: str) -> None:
        """Return a failed dispatch to the retryable state."""
        now = datetime.now(timezone.utc).isoformat()
        self.connection.execute(
            "UPDATE seen SET classification='unclassified', classified_at=NULL WHERE event_id=?",
            (event_id,),
        )
        self.connection.execute(
            "UPDATE incoming_events SET classification='unclassified', last_error=?, last_seen_at=? WHERE event_id=?",
            (error[:500], now, event_id),
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
    return next((domain for domain in TRUSTED_NEWS_DOMAINS if host == domain or host.endswith(f".{domain}")), "")


def _discovery_category_and_anchor(title: str) -> tuple[str, str] | None:
    normalized = title.casefold()
    category = classify_flash(Flash("discovery", title, "", ""))
    if category is None:
        return None
    anchor = next((term for term in DISCOVERY_ANCHORS.get(category, ()) if term in normalized), "")
    return (category, anchor) if anchor else None


def _discovery_facts(title: str, category: str, anchor: str) -> tuple[set[str], set[str]]:
    """Extract the concrete actor/place and action facts used for agreement."""
    normalized = title.casefold()
    entities = {term for term in DISCOVERY_ENTITIES if term in normalized}
    if anchor in DISCOVERY_ENTITY_ANCHORS:
        entities.add(anchor)
    actions = {term for term in DISCOVERY_ACTIONS.get(category, ()) if term in normalized}
    return entities, actions


def _matching_discovery_evidence(
    cluster: list[DiscoveryArticle], category: str, anchor: str
) -> tuple[DiscoveryArticle, ...]:
    """Return only multi-domain articles agreeing on entity/place and action."""
    supported: dict[str, DiscoveryArticle] = {}
    facts = [(article, *_discovery_facts(article.title, category, anchor)) for article in cluster]
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
        url = str(row.get("url") or "").strip()
        seen_at = str(row.get("seendate") or "").strip()
        observed = _gdelt_seen_at(seen_at)
        domain = _trusted_domain(url, str(row.get("domain") or ""))
        if not title or not url or not observed or observed.timestamp() < cutoff or not domain:
            continue
        articles.append(DiscoveryArticle(title=title, url=url, domain=domain, seen_at=observed.isoformat()))
    if store:
        store.write_cache("gdelt-success", [article.__dict__ for article in articles])
    return articles


def cross_checked_gdelt_alerts(articles: Iterable[DiscoveryArticle]) -> list[Alert]:
    """Require two publishers plus the same entity/place and action facts."""
    clusters: dict[tuple[str, str], list[DiscoveryArticle]] = {}
    for article in articles:
        classified = _discovery_category_and_anchor(article.title)
        if classified:
            clusters.setdefault(classified, []).append(article)
    alerts: list[Alert] = []
    for (category, anchor), cluster in clusters.items():
        # News aggregation may flag a disaster first, but black-swan delivery
        # is reserved for a verified first-party official monitor.
        if category == "black_swan":
            continue
        domains = {article.domain for article in cluster}
        if len(domains) < 2:
            continue
        evidence = _matching_discovery_evidence(cluster, category, anchor)
        if len({article.domain for article in evidence}) < 2:
            continue
        representative = min(evidence, key=lambda article: article.seen_at)
        stable_id = hashlib.sha256("|".join(sorted(article.url for article in cluster)).encode("utf-8")).hexdigest()[:20]
        alerts.append(Alert(
            event_id=f"gdelt-{category}-{stable_id}",
            category=category,
            summary=f"{CATEGORY_LABELS[category]}：{anchor}多源核對",
            occurred_at=representative.seen_at,
            source="gdelt",
            evidence=evidence,
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
    cooldown = max(1800, int(os.environ.get("JIN10_CATEGORY_COOLDOWN_SECONDS", "1800")))
    bootstrap = os.environ.get("JIN10_INITIAL_BACKFILL", "false").lower() == "true"
    gdelt_interval = max(900, int(os.environ.get("GDELT_POLL_SECONDS", "900")))
    gdelt_enabled = os.environ.get("GDELT_DISCOVERY_ENABLED", "true").lower() == "true"
    update_health("gdelt", enabled=gdelt_enabled, poll_seconds=gdelt_interval,
                  status="disabled" if not gdelt_enabled else "not_checked")
    store = SeenStore(Path(os.environ.get("MONITOR_STATE_PATH", "/data/jin10-monitor.sqlite3")))
    global DELIVERY_STORE
    DELIVERY_STORE = store
    first_cycle = True
    gdelt_baseline = True
    last_gdelt_poll = 0.0

    while True:
        try:
            flashes = await fetch_jin10_flashes(jin10_token, limit)
            flashes.sort(key=lambda item: item.occurred_at)
            dispatched = 0
            for flash in flashes:
                store.record_incoming_flash(flash)
                previous_classification = store.classification_for(flash.event_id)
                alert = alert_from_flash(flash)
                classification = "in_scope" if alert is not None else "unclassified"
                if not store.claim_classification(flash.event_id, classification):
                    continue
                if alert is None:
                    # Keep unrecognised IDs retryable after a rule/source update.
                    continue
                # Brand-new rows are baselined on the first cycle.  A legacy
                # ``unclassified`` row is intentionally not baselined: it is
                # precisely the missed event that a rule update should recover.
                if first_cycle and not bootstrap and previous_classification is None:
                    store.set_classification(flash.event_id, "baseline")
                    continue
                ledger_record = store.observe_alert(alert)
                if not store.ledger_may_dispatch(ledger_record, cooldown):
                    logging.info("Jin10 alert suppressed by durable event ledger: %s", ledger_record["canonical_key"])
                    continue
                if not store.may_dispatch(alert, cooldown):
                    logging.info("Jin10 alert suppressed by category cooldown: %s", alert.category)
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
                store.mark_alert_reminded(alert, escalated="高風險" in alert.summary)
                dispatched += 1
            logging.info("Jin10 poll completed: %s flash(es), %s alert(s) dispatched", len(flashes), dispatched)
            update_health("jin10", status="healthy", last_success_at=datetime.now(timezone.utc).isoformat(),
                          item_count=len(flashes), error=None)
            first_cycle = False
        except Exception as error:
            update_health("jin10", status="failed", last_failure_at=datetime.now(timezone.utc).isoformat(),
                          error=type(error).__name__)
            logging.exception("Jin10 poll failed; will retry")
        if gdelt_enabled and time.monotonic() - last_gdelt_poll >= gdelt_interval:
            last_gdelt_poll = time.monotonic()
            try:
                articles = await fetch_gdelt_articles(store)
                alerts = cross_checked_gdelt_alerts(articles)
                dispatched = 0
                for alert in alerts:
                    previous_classification = store.classification_for(alert.event_id)
                    if not store.claim_classification(alert.event_id, "in_scope"):
                        continue
                    if gdelt_baseline and not bootstrap and previous_classification is None:
                        store.set_classification(alert.event_id, "baseline")
                        continue
                    ledger_record = store.observe_alert(alert)
                    if not store.ledger_may_dispatch(ledger_record, gdelt_interval if gdelt_interval >= 1800 else 7200):
                        logging.info("GDELT alert suppressed by durable event ledger: %s", ledger_record["canonical_key"])
                        continue
                    if not store.may_dispatch(alert, gdelt_interval if gdelt_interval >= 1800 else 7200):
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
                logging.info("GDELT cross-check completed: %s article(s), %s alert(s) dispatched", len(articles), dispatched)
                update_health("gdelt", status="healthy", last_success_at=datetime.now(timezone.utc).isoformat(),
                              article_count=len(articles), alert_count=dispatched, error=None)
                gdelt_baseline = False
            except Exception as error:
                update_health("gdelt", status="failed", last_failure_at=datetime.now(timezone.utc).isoformat(),
                              error=type(error).__name__)
                logging.exception("GDELT discovery failed; will wait for the next interval")
        await asyncio.sleep(interval)


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    start_health_server()
    asyncio.run(monitor_forever())


if __name__ == "__main__":
    main()
