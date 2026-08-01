"""Durable, provider-independent event de-duplication ledger.

GitHub Actions cache keys are useful as a short-lived delivery lock, but they
are not an event history.  This module keeps the durable facts needed to
recognise the same event after a cache eviction or a new deployment.  The
default JSON format is intentionally portable: GitHub Actions can commit it
with the public snapshot and Railway can point ``EVENT_LEDGER_PATH`` at a
persistent volume.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_QUERY_KEYS = {"fbclid", "gclid", "dclid", "mc_cid", "mc_eid", "ref", "ref_src"}
FACT_FIELDS = {
    "person": ("person", "persons", "people", "entities", "actors"),
    "location": ("location", "locations", "place", "places", "regions"),
    "action": ("action", "actions", "event_action", "verbs"),
}


def normalize_source_url(value: Any) -> str:
    """Normalise a public URL without discarding the article identity."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"https://{raw}"
    parts = urlsplit(raw)
    host = (parts.hostname or "").lower().removeprefix("www.")
    if not host:
        return ""
    port = f":{parts.port}" if parts.port and parts.port not in {80, 443} else ""
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if key.lower() not in TRACKING_QUERY_KEYS and not key.lower().startswith("utm_")]
    return urlunsplit((parts.scheme.lower() or "https", host + port, path, urlencode(sorted(query)), ""))


def _tokens(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = re.split(r"[,，;；|｜/／\\\s]+", str(value))
    return sorted({str(item).strip().casefold() for item in values if str(item).strip()})


def fact_fingerprint(event: dict[str, Any]) -> dict[str, str]:
    """Return stable person/location/action fingerprints for an event."""
    title = " ".join(str(event.get(key) or "") for key in ("title", "summary", "brief_summary"))
    # These common anchors make cross-source syndicated headlines converge
    # even when providers do not expose structured entities.
    vocabulary = {
        "person": ("trump", "powell", "fed", "netanyahu", "putin", "zelensky", "台積電", "nvidia"),
        "location": ("iran", "israel", "ukraine", "russia", "hormuz", "taiwan", "japan", "china", "日本", "台灣"),
        "action": ("attack", "airstrike", "war", "ceasefire", "truce", "tariff", "sanction", "earthquake", "tsunami", "供應中斷", "停火", "關稅"),
    }
    fingerprints: dict[str, str] = {}
    for kind, fields in FACT_FIELDS.items():
        values: list[str] = []
        for field in fields:
            values.extend(_tokens(event.get(field)))
        if not values:
            lower = title.casefold()
            values = [term for term in vocabulary[kind] if term.casefold() in lower]
        fingerprints[kind] = hashlib.sha256("|".join(sorted(set(values))).encode("utf-8")).hexdigest()[:16] if values else ""
    return fingerprints


def _published_bucket(value: Any, minutes: int = 30) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "unknown"
    try:
        timestamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        return str(int(timestamp.timestamp()) // (minutes * 60))
    except ValueError:
        return raw[:16]


def canonical_event_key(event: dict[str, Any] | None) -> str:
    """Build a stable event key from topic, source facts and time bucket."""
    if not event:
        return "none"
    if event.get("kind") == "market_signal":
        instrument = event.get("instrument") or {}
        time_bucket = ""
        if event.get("realert_interval_minutes") and instrument.get("quote_time"):
            time_bucket = str(instrument.get("quote_time"))[:13]
        material = "|".join((
            "market", str(instrument.get("ticker") or "market"),
            str(instrument.get("quote_date") or "unknown"),
            str(event.get("signal_state") or event.get("risk_level") or "observe"),
            time_bucket,
        ))
    else:
        facts = fact_fingerprint(event)
        source_url = normalize_source_url(event.get("source_url") or event.get("url"))
        topic = str(event.get("topic_key") or event.get("source_key") or event.get("short_label") or event.get("event_type") or "official").casefold()
        # A source URL is a fallback identity only.  Topic + facts + release
        # bucket lets syndicated reports converge across different URLs.
        identity = "|".join((topic, facts["person"], facts["location"], facts["action"], _published_bucket(event.get("released_at") or event.get("published_at"), 120)))
        material = identity if any(facts.values()) else f"{identity}|{source_url}"
        if event.get("escalation"):
            material += "|escalated"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


class EventLedger:
    """Small atomic JSON ledger with 30-day retention by default."""

    def __init__(self, path: Path | str | None = None, *, retention_days: int = 30) -> None:
        self.path = Path(path or os.getenv("EVENT_LEDGER_PATH", "site/data/event-ledger.json"))
        self.retention_days = max(30, int(retention_days))
        self.records: dict[str, dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            rows = payload.get("events", payload) if isinstance(payload, dict) else {}
            if isinstance(rows, dict):
                self.records = {str(key): dict(value) for key, value in rows.items() if isinstance(value, dict)}
        except (OSError, json.JSONDecodeError, TypeError):
            self.records = {}

    def prune(self, now: datetime | None = None) -> int:
        current = now or datetime.now(UTC)
        cutoff = current - timedelta(days=self.retention_days)
        removed = 0
        for key, record in list(self.records.items()):
            raw = record.get("last_reminded_at") or record.get("first_discovered_at")
            try:
                timestamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=UTC)
            except ValueError:
                timestamp = datetime.min.replace(tzinfo=UTC)
            if timestamp < cutoff:
                del self.records[key]
                removed += 1
        return removed

    def observe(self, event: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        current = now or datetime.now(UTC)
        now_iso = current.isoformat()
        key = canonical_event_key(event)
        facts = fact_fingerprint(event)
        source_url = normalize_source_url(event.get("source_url") or event.get("url"))
        source_domain = urlsplit(source_url).hostname.lower().removeprefix("www.") if source_url else ""
        record = self.records.get(key)
        changed = False
        if record is None:
            record = {
                "canonical_key": key,
                "event_type": event.get("event_type") or event.get("kind") or "market",
                "source_url": source_url,
                "source_domain": source_domain,
                "person_fingerprint": facts["person"],
                "location_fingerprint": facts["location"],
                "action_fingerprint": facts["action"],
                "first_discovered_at": now_iso,
                "last_reminded_at": None,
                "escalated": bool(event.get("escalation") or event.get("risk_level") == "高風險"),
                "verified_sources": [source_url] if source_url else [],
                "last_title": str(event.get("title") or event.get("summary") or ""),
                "updated_at": now_iso,
            }
            self.records[key] = record
            is_new = True
            changed = True
        else:
            is_new = False
            for field in ("person", "location", "action"):
                if facts[field]:
                    field_name = f"{field}_fingerprint"
                    if record.get(field_name) != facts[field]:
                        record[field_name] = facts[field]
                        changed = True
            if source_url and source_url not in record.get("verified_sources", []):
                record.setdefault("verified_sources", []).append(source_url)
                changed = True
            if source_url and not record.get("source_url"):
                record["source_url"] = source_url
                record["source_domain"] = source_domain
                changed = True
            escalated = bool(record.get("escalated") or event.get("escalation") or event.get("risk_level") == "高風險")
            if escalated != bool(record.get("escalated")):
                record["escalated"] = escalated
                changed = True
        sources = event.get("verified_sources") or event.get("sources") or event.get("evidence") or []
        for source in sources if isinstance(sources, list) else []:
            url = normalize_source_url(source.get("url") if isinstance(source, dict) else source)
            if url and url not in record.setdefault("verified_sources", []):
                record["verified_sources"].append(url)
                changed = True
        if changed:
            record["updated_at"] = now_iso
        removed = self.prune(current)
        return {**record, "is_new": is_new, "changed": bool(changed or removed)}

    def should_remind(self, event: dict[str, Any], *, cooldown_seconds: int = 7200, now: datetime | None = None) -> bool:
        record = self.observe(event, now=now)
        if record["is_new"] or event.get("escalation") or event.get("risk_level") == "高風險":
            return True
        raw = record.get("last_reminded_at")
        if not raw:
            return True
        try:
            reminded = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if reminded.tzinfo is None:
                reminded = reminded.replace(tzinfo=UTC)
            return (now or datetime.now(UTC)) - reminded >= timedelta(seconds=cooldown_seconds)
        except ValueError:
            return True

    def mark_reminded(self, event: dict[str, Any], *, now: datetime | None = None) -> str:
        current = now or datetime.now(UTC)
        key = canonical_event_key(event)
        self.observe(event, now=current)
        self.records[key]["last_reminded_at"] = current.isoformat()
        self.records[key]["escalated"] = bool(self.records[key].get("escalated") or event.get("escalation") or event.get("risk_level") == "高風險")
        return key

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": 1, "retention_days": self.retention_days, "events": self.records}
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
