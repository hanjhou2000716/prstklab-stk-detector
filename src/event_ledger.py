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
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_QUERY_KEYS = {"fbclid", "gclid", "dclid", "mc_cid", "mc_eid", "ref", "ref_src"}
FACT_FIELDS = {
    "person": ("person", "persons", "people", "entities", "actors"),
    "location": ("location", "locations", "place", "places", "regions"),
    "action": ("action", "actions", "event_action", "verbs"),
}

RISK_RANK = {"觀察": 0, "持續觀察": 0, "市場待核對": 0, "警戒": 1, "高波動": 1, "高風險": 2}
DEFAULT_COOLDOWN_SECONDS = 30 * 60


def _risk_rank(value: Any) -> int:
    return RISK_RANK.get(str(value or "").strip(), 0)


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
        # Escalation is a state transition of the same event, not a new
        # identity.  Keeping it out of the key lets the ledger record an
        # upgrade without replaying the original event after a cache reset.
        material = identity if any(facts.values()) else f"{identity}|{source_url}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


class EventLedger:
    """Atomic JSON ledger with retention and concurrent-writer protection."""

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        retention_days: int = 30,
        lock_timeout_seconds: float = 30.0,
        lock_stale_after_seconds: float = 120.0,
    ) -> None:
        path_value = path or os.getenv("EVENT_LEDGER_PATH") or "site/data/event-ledger.json"
        self.path = Path(path_value)
        self.retention_days = max(30, int(retention_days))
        self.lock_timeout_seconds = max(0.1, float(lock_timeout_seconds))
        self.lock_stale_after_seconds = max(1.0, float(lock_stale_after_seconds))
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
        source_domain = (urlsplit(source_url).hostname or "").lower().removeprefix("www.") if source_url else ""
        record = self.records.get(key)
        changed = False
        if record is None:
            risk_level = str(event.get("risk_level") or "觀察")
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
                "risk_level": risk_level,
                "risk_rank": _risk_rank(risk_level),
                "verified_sources": [source_url] if source_url else [],
                "last_title": str(event.get("title") or event.get("summary") or ""),
                "updated_at": now_iso,
            }
            self.records[key] = record
            is_new = True
            changed = True
        else:
            is_new = False
            previous_escalated = bool(record.get("escalated"))
            previous_rank = int(record.get("risk_rank", _risk_rank(record.get("risk_level"))))
            incoming_level = str(event.get("risk_level") or record.get("risk_level") or "觀察")
            incoming_rank = _risk_rank(incoming_level)
            risk_upgraded = incoming_rank > previous_rank
            if incoming_rank != previous_rank or incoming_level != record.get("risk_level"):
                record["risk_level"] = incoming_level
                record["risk_rank"] = incoming_rank
                changed = True
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
            escalated = bool(record.get("escalated") or event.get("escalation") or incoming_rank >= 2)
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
        # Keep upgrade detection in the return value only; it is a delivery
        # decision, not durable event content.
        if record.get("risk_rank", 0) >= 0 and is_new:
            risk_upgraded = False
        else:
            risk_upgraded = locals().get("risk_upgraded", False)
        escalation_upgraded = bool(
            not is_new and event.get("escalation") and not locals().get("previous_escalated", False)
        )
        return {**record, "is_new": is_new, "risk_upgraded": risk_upgraded,
                "escalation_upgraded": escalation_upgraded, "changed": bool(changed or removed)}

    def should_remind(self, event: dict[str, Any], *, cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS, now: datetime | None = None) -> bool:
        record = self.observe(event, now=now)
        if record["is_new"] or record.get("risk_upgraded") or record.get("escalation_upgraded"):
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

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        try:
            timestamp = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
            return timestamp.replace(tzinfo=timestamp.tzinfo or UTC)
        except (TypeError, ValueError):
            return datetime.min.replace(tzinfo=UTC)

    @classmethod
    def _merge_record(cls, left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
        """Merge two writer views without dropping newer evidence or reminders."""
        left_time = cls._timestamp(left.get("updated_at") or left.get("last_reminded_at"))
        right_time = cls._timestamp(right.get("updated_at") or right.get("last_reminded_at"))
        newest, older = (right, left) if right_time >= left_time else (left, right)
        merged = dict(older)
        merged.update(newest)

        first_values = [cls._timestamp(item.get("first_discovered_at")) for item in (left, right)]
        first = min(first_values)
        if first != datetime.min.replace(tzinfo=UTC):
            merged["first_discovered_at"] = first.isoformat()
        reminder_values = [cls._timestamp(item.get("last_reminded_at")) for item in (left, right)]
        reminder = max(reminder_values)
        if reminder != datetime.min.replace(tzinfo=UTC):
            merged["last_reminded_at"] = reminder.isoformat()
        merged["escalated"] = bool(left.get("escalated") or right.get("escalated"))
        merged["risk_rank"] = max(int(left.get("risk_rank", 0) or 0), int(right.get("risk_rank", 0) or 0))
        verified = list(dict.fromkeys([
            *(left.get("verified_sources") or []),
            *(right.get("verified_sources") or []),
        ]))
        if verified:
            merged["verified_sources"] = verified
        return merged

    @staticmethod
    def _read_records(path: Path) -> dict[str, dict[str, Any]]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = payload.get("events", payload) if isinstance(payload, dict) else {}
            if isinstance(rows, dict):
                return {str(key): dict(value) for key, value in rows.items() if isinstance(value, dict)}
        except (OSError, json.JSONDecodeError, TypeError):
            pass
        return {}

    @contextmanager
    def _write_lock(self) -> Iterator[None]:
        """Acquire a portable sidecar lock for the read/merge/replace cycle."""
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        deadline = time.monotonic() + self.lock_timeout_seconds
        while True:
            try:
                lock_path.parent.mkdir(parents=True, exist_ok=True)
                descriptor = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(f"pid={os.getpid()}\n")
                break
            except FileExistsError:
                try:
                    if time.time() - lock_path.stat().st_mtime > self.lock_stale_after_seconds:
                        lock_path.unlink()
                        continue
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out waiting for event ledger lock: {lock_path}") from None
                time.sleep(0.05)
        try:
            yield
        finally:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass

    def save(self) -> None:
        with self._write_lock():
            # Reload while holding the lock: another process may have saved
            # after this instance was created.  Merge prevents lost events.
            merged = self._read_records(self.path)
            for key, record in self.records.items():
                merged[key] = self._merge_record(merged[key], record) if key in merged else dict(record)
            self.records = merged
            self.prune()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"schema_version": 1, "retention_days": self.retention_days, "events": self.records}
            temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.{time.time_ns()}.tmp")
            try:
                temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                temporary.replace(self.path)
            finally:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
