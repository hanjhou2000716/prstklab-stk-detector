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

RISK_RANK = {
    "觀察": 0, "持續觀察": 0, "市場待核對": 0, "R0": 0, "R1": 0,
    "高波動": 1, "R2": 1,
    "警戒": 2, "R3": 2,
    "高風險": 3, "R4": 3,
}
DEFAULT_COOLDOWN_SECONDS = 30 * 60
THEME_WINDOW_SECONDS = 2 * 60 * 60


def _risk_rank(value: Any) -> int:
    normalized = str(value or "").strip()
    return RISK_RANK.get(normalized.upper(), RISK_RANK.get(normalized, 0))


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
        compound_cluster = str(event.get("compound_event_cluster_key") or "").strip()
        if compound_cluster:
            material = f"compound|{compound_cluster}"
            return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
        topic = str(event.get("topic_key") or event.get("source_key") or event.get("short_label") or event.get("event_type") or "official").casefold()
        # A source URL is a fallback identity only.  Topic + facts + release
        # bucket lets syndicated reports converge across different URLs.
        identity = "|".join((topic, facts["person"], facts["location"], facts["action"], _published_bucket(event.get("released_at") or event.get("published_at"), 120)))
        # Escalation is a state transition of the same event, not a new
        # identity.  Keeping it out of the key lets the ledger record an
        # upgrade without replaying the original event after a cache reset.
        material = identity if any(facts.values()) else f"{identity}|{source_url}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def notification_theme_key(event: dict[str, Any] | None) -> str:
    """Project an event into a stable investor-facing notification theme.

    This is deliberately a projection over the existing EventLedger identity;
    it is not a second persistence layer.  Providers may supply an explicit
    key, while common market/news facts receive deterministic, material
    specific keys so a new URL or headline does not create a new alert.
    """
    if not isinstance(event, dict):
        return "unknown"
    explicit = str(event.get("notification_theme_key") or "").strip().casefold()
    if explicit:
        return explicit
    raw_instrument = event.get("instrument")
    instrument = raw_instrument if isinstance(raw_instrument, dict) else {}
    ticker = str(instrument.get("ticker") or event.get("ticker") or "").strip().upper()
    if str(event.get("kind") or "").casefold() == "market_signal" or ticker:
        return f"{ticker or 'market'}-price-move"
    topic = str(event.get("topic_key") or event.get("source_key") or event.get("event_type") or "event").strip().casefold()
    text = " ".join(str(event.get(key) or "") for key in ("title", "summary", "brief_summary")).casefold()
    if any(term in topic or term in text for term in ("fomc", "fed", "central-bank", "interest", "rate", "利率", "聯準")):
        if any(term in topic or term in text for term in ("official", "decision", "statement", "fomc", "公布", "決議")):
            return "fed-official-decision"
        return "fed-rate-outlook"
    if any(term in topic or term in text for term in ("tariff", "trade", "關稅", "貿易")):
        if any(term in topic or term in text for term in ("semiconductor", "chip", "半導體", "晶片")):
            return "us-semiconductor-policy"
        return "trade-policy"
    if any(term in topic or term in text for term in ("conflict", "war", "iran", "israel", "地緣", "衝突")):
        return "middle-east-conflict" if any(term in text for term in ("iran", "israel", "中東", "伊朗", "以色列")) else "geopolitical-conflict"
    anchors = [
        *(_tokens(event.get("person"))[:2]),
        *(_tokens(event.get("location"))[:2]),
        *(_tokens(event.get("action"))[:2]),
    ]
    suffix = "-".join(anchors) or hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]
    return f"{topic or 'event'}-{suffix}"


def _material_state(event: dict[str, Any] | None) -> dict[str, Any]:
    """Return only fields that can justify a same-theme re-alert."""
    if not isinstance(event, dict):
        return {}
    raw_instrument = event.get("instrument")
    instrument = raw_instrument if isinstance(raw_instrument, dict) else {}
    percent = instrument.get("change_percent", event.get("change_percent"))
    try:
        numeric_percent = float(percent) if percent is not None else None
    except (TypeError, ValueError):
        numeric_percent = None
    direction = "up" if numeric_percent is not None and numeric_percent > 0 else "down" if numeric_percent is not None and numeric_percent < 0 else str(event.get("direction") or event.get("market_direction") or "").casefold()
    raw_impact = event.get("impact_confirmation")
    impact = raw_impact if isinstance(raw_impact, dict) else {}
    official = bool(event.get("official_confirmation") or event.get("official_confirmed") or event.get("crosscheck_status") in {"official_confirmed", "confirmed"})
    market = bool(event.get("market_sync_confirmed") or event.get("market_confirmation") or impact.get("confirmed"))
    risk = str(event.get("prstk_risk_level") or event.get("risk_level") or (event.get("prstk_risk") or {}).get("prstk_risk_level") or "R0").upper()
    return {
        "risk_rank": _risk_rank(risk),
        "risk": risk,
        "official_confirmation": official,
        "market_confirmation": market,
        "material_fact_version": str(event.get("material_fact_version") or event.get("fact_version") or "").strip(),
        "direction": direction,
        "price_bucket": (4 if numeric_percent is not None and abs(numeric_percent) >= 4 else 3 if numeric_percent is not None and abs(numeric_percent) >= 3 else 2 if numeric_percent is not None and abs(numeric_percent) > 1.5 else 0),
        "systemic_emergency": bool(event.get("systemic_emergency") or (risk == "R4" and official and market)),
    }


def material_state_changed(previous: dict[str, Any] | None, event: dict[str, Any] | None) -> bool:
    """Return whether an event contains a contract-approved material change."""
    current = _material_state(event)
    if not previous:
        return True
    if current.get("systemic_emergency") and not previous.get("systemic_emergency"):
        return True
    if current.get("official_confirmation") and not previous.get("official_confirmation"):
        return True
    if current.get("market_confirmation") and not previous.get("market_confirmation"):
        return True
    if int(current.get("risk_rank", 0)) > int(previous.get("risk_rank", 0)):
        return True
    if current.get("material_fact_version") and current.get("material_fact_version") != previous.get("material_fact_version"):
        return True
    if current.get("direction") and previous.get("direction") and current.get("direction") != previous.get("direction"):
        return True
    if int(current.get("price_bucket", 0)) > int(previous.get("price_bucket", 0)):
        return True
    return False


def taiwan_investor_priority(event: dict[str, Any] | None, *, now: datetime | None = None) -> int:
    """Return the Taiwan-session queue priority (1 is highest)."""
    current = now or datetime.now(UTC)
    try:
        from zoneinfo import ZoneInfo
        local = current.astimezone(ZoneInfo("Asia/Taipei"))
    except Exception:
        local = current
    minute = local.hour * 60 + local.minute
    in_session = local.weekday() < 5 and 8 * 60 + 45 <= minute <= 13 * 60 + 30
    if not in_session or not isinstance(event, dict):
        return 4
    raw_instrument = event.get("instrument")
    instrument = raw_instrument if isinstance(raw_instrument, dict) else {}
    ticker = str(instrument.get("ticker") or event.get("ticker") or "").upper()
    market = str(event.get("market") or event.get("region") or "").casefold()
    text = " ".join(str(event.get(key) or "") for key in ("topic_key", "event_type", "short_label", "title", "summary")).casefold()
    risk = str(event.get("prstk_risk_level") or event.get("risk_level") or (event.get("prstk_risk") or {}).get("prstk_risk_level") or "").upper()
    official = bool(event.get("official_confirmation") or event.get("official_confirmed") or event.get("crosscheck_status") in {"official_confirmed", "confirmed"})
    synced = bool(event.get("market_sync_confirmed") or event.get("market_confirmation") or (event.get("impact_confirmation") or {}).get("confirmed"))
    if risk == "R4" and official and synced:
        return 0
    if ticker in {"2330", "006208", "00685L", "TAIEX", "TPEX"} or market in {"taiwan", "tw", "台股", "台灣"} or any(term in text for term in ("台灣政策", "台股政策", "taiwan policy")):
        return 1
    if ticker in {"TSM", "NVDA", "SOX", "NASDAQ"} or any(term in text for term in ("semiconductor", "chip", "半導體", "晶片", "ai supply")):
        return 2
    if official or any(term in text for term in ("fed", "fomc", "cpi", "pce", "nfp", "usd/twd", "貨幣", "利率")):
        return 3
    return 4


def is_secondary_commentary(event: dict[str, Any] | None) -> bool:
    """Identify opinion-only discovery content without blocking evidence."""
    if not isinstance(event, dict):
        return False
    source_role = str(event.get("source_role") or "").casefold()
    source_tier = str(event.get("source_tier") or "").casefold()
    provider = str(event.get("provider") or event.get("source_key") or event.get("source") or "").casefold()
    commentary = bool(event.get("commentary_only") or event.get("is_commentary"))
    opinion = any(term in source_role or term in provider for term in ("commentary", "analyst", "broker", "yahoo", "google"))
    discovery = source_tier in {"discovery", "secondary", "public"} or opinion
    official = bool(event.get("official_confirmation") or event.get("official_confirmed") or event.get("crosscheck_status") in {"official_confirmed", "confirmed"})
    market_sync = bool(event.get("market_sync_confirmed") or event.get("market_confirmation") or (event.get("impact_confirmation") or {}).get("confirmed"))
    watchlist = bool(event.get("watchlist_trigger") or event.get("kind") == "market_signal")
    fj = event.get("vendor_importance")
    try:
        fj_priority = float(str(fj)) >= 8
    except (TypeError, ValueError):
        fj_priority = False
    return bool(commentary or (discovery and not official and not market_sync and not watchlist and not fj_priority))


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
            history = record.get("delivery_history")
            if isinstance(history, list):
                record["delivery_history"] = [
                    item for item in history
                    if isinstance(item, dict) and self._timestamp(item.get("sent_at")) >= cutoff
                ]
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
        theme_key = notification_theme_key(event)
        state = _material_state(event)
        facts = fact_fingerprint(event)
        source_url = normalize_source_url(event.get("source_url") or event.get("url"))
        source_domain = (urlsplit(source_url).hostname or "").lower().removeprefix("www.") if source_url else ""
        record = self.records.get(key)
        changed = False
        if record is None:
            risk_level = str(event.get("risk_level") or "觀察")
            record = {
                "canonical_key": key,
                "notification_theme_key": theme_key,
                "material_state": state,
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
                "compound_item_id": str(event.get("compound_item_id") or "") or None,
                "compound_event_cluster_key": str(event.get("compound_event_cluster_key") or "") or None,
                "last_decision": None,
                "decision_history": [],
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
            if record.get("notification_theme_key") != theme_key:
                record["notification_theme_key"] = theme_key
                changed = True
            previous_state = record.get("material_state") if isinstance(record.get("material_state"), dict) else {}
            if material_state_changed(previous_state, event):
                record["material_state"] = state
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

    def theme_decision(
        self,
        event: dict[str, Any],
        *,
        now: datetime | None = None,
        window_seconds: int = THEME_WINDOW_SECONDS,
    ) -> dict[str, Any]:
        """Decide whether a candidate is a new investor-theme notification.

        Every outcome is returned with an explicit reason.  Suppressed rows
        remain in the same EventLedger and can therefore update the Mini App
        evidence without sending another Telegram message.
        """
        current = now or datetime.now(UTC)
        theme = notification_theme_key(event)
        state = _material_state(event)
        candidates = [
            record for record in self.records.values()
            if isinstance(record, dict) and record.get("notification_theme_key") == theme
        ]
        latest: dict[str, Any] | None = None
        latest_time = datetime.min.replace(tzinfo=UTC)
        for record in candidates:
            raw = record.get("last_theme_notification_at") or record.get("last_reminded_at")
            stamp = self._timestamp(raw)
            if stamp > latest_time:
                latest, latest_time = record, stamp
        within_window = latest is not None and (current - latest_time).total_seconds() < max(0, int(window_seconds))
        changed = material_state_changed((latest or {}).get("material_state") if latest else None, event)
        if latest is not None and not changed:
            # The two-hour window is a coalescing window, not a re-arm timer.
            # An unchanged theme stays suppressed overnight and across later
            # releases until a contract-approved material state changes.
            reason = "same_theme_within_2h" if within_window else "same_theme_unchanged"
            status = "suppressed"
            allowed = False
        else:
            reason = "material_state_change" if latest else "new_theme"
            status = "eligible"
            allowed = True
        decision = {
            "allowed": allowed,
            "status": status,
            "reason": reason,
            "notification_theme_key": theme,
            "event_key": canonical_event_key(event),
            "risk": state.get("risk", "R0"),
            "theme_window": window_seconds,
            "material_state_changed": changed,
            "last_notified_at": latest_time.isoformat() if latest else None,
        }
        self.record_decision(event, decision, now=current)
        return decision

    def mark_theme_notified(self, event: dict[str, Any], *, now: datetime | None = None) -> None:
        """Record the last successful notification for a theme."""
        current = now or datetime.now(UTC)
        key = canonical_event_key(event)
        self.observe(event, now=current)
        record = self.records[key]
        record["notification_theme_key"] = notification_theme_key(event)
        record["material_state"] = _material_state(event)
        record["last_theme_notification_at"] = current.isoformat()
        record["last_notified_at"] = current.isoformat()
        record["updated_at"] = current.isoformat()

    def should_remind(self, event: dict[str, Any], *, cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS, now: datetime | None = None) -> bool:
        current = now or datetime.now(UTC)
        key = canonical_event_key(event)
        record = self.records.get(key)
        if record is None:
            return True
        # New-format delivery records are governed by material state, never by
        # elapsed time.  Keep the legacy cooldown only for old records that
        # have a reminder timestamp but no material delivery marker.
        if record.get("last_theme_notification_at") or record.get("last_notified_at"):
            return material_state_changed(record.get("material_state"), event)
        if material_state_changed(record.get("material_state"), event):
            return True
        raw = record.get("last_reminded_at")
        if not raw:
            return True
        try:
            reminded = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if reminded.tzinfo is None:
                reminded = reminded.replace(tzinfo=UTC)
            return current - reminded >= timedelta(seconds=cooldown_seconds)
        except ValueError:
            return True

    def mark_reminded(self, event: dict[str, Any], *, now: datetime | None = None) -> str:
        current = now or datetime.now(UTC)
        key = canonical_event_key(event)
        self.observe(event, now=current)
        self.records[key]["last_reminded_at"] = current.isoformat()
        self.records[key]["escalated"] = bool(self.records[key].get("escalated") or event.get("escalation") or event.get("risk_level") == "高風險")
        return key

    def delivery_history(self) -> list[dict[str, Any]]:
        """Return alert-budget rows from the durable ledger.

        Older ledgers only have ``last_reminded_at``.  They are represented as
        one legacy row so the cooldown remains fail-closed while new sends
        record every material delivery for hourly and per-event budgets.
        """
        rows: list[dict[str, Any]] = []
        for key, record in self.records.items():
            history = record.get("delivery_history")
            if isinstance(history, list) and history:
                for item in history:
                    if isinstance(item, dict) and item.get("sent_at"):
                        rows.append({**item, "event_key": str(item.get("event_key") or key)})
                continue
            reminded = record.get("last_reminded_at")
            if reminded:
                rows.append({
                    "event_key": key,
                    "sent_at": reminded,
                    "importance": record.get("risk_level", "normal"),
                    "legacy": True,
                })
        return rows

    def record_decision(
        self,
        event: dict[str, Any],
        decision: dict[str, Any] | None = None,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Persist a notification decision and its explicit blocking reason."""
        current = now or datetime.now(UTC)
        key = canonical_event_key(event)
        self.observe(event, now=current)
        record = self.records[key]
        raw = decision if isinstance(decision, dict) else {}
        nested: dict[str, Any] = {}
        if isinstance(event.get("notification"), dict):
            nested = event["notification"]
        reasons = raw.get("reasons") or raw.get("pending_reasons") or event.get("pending_reasons") or []
        if not isinstance(reasons, (list, tuple)):
            reasons = [str(reasons)] if reasons else []
        row: dict[str, Any] = {
            "recorded_at": current.isoformat(),
            "allowed": bool(raw.get("allowed", nested.get("allowed", False))),
            "status": str(raw.get("status") or nested.get("status") or "pending"),
            "reason": str(raw.get("reason") or (reasons[0] if reasons else "")),
            "reasons": [str(item) for item in reasons if str(item).strip()],
            "notification_theme_key": notification_theme_key(event),
            "event_key": key,
            "risk": _material_state(event).get("risk", "R0"),
            "theme_window": raw.get("theme_window", THEME_WINDOW_SECONDS),
            "material_state_changed": bool(raw.get("material_state_changed", False)),
            "last_notified_at": raw.get("last_notified_at"),
            "taiwan_priority": taiwan_investor_priority(event, now=current),
        }
        record["last_decision"] = row
        history = record.setdefault("decision_history", [])
        if not isinstance(history, list):
            history = []
            record["decision_history"] = history
        history.append(row)
        record["decision_history"] = history[-20:]
        record["updated_at"] = current.isoformat()
        return row

    def record_delivery(
        self,
        event: dict[str, Any],
        *,
        sent_at: datetime | None = None,
        trace_id: str | None = None,
        reason: str = "delivered",
    ) -> dict[str, Any]:
        """Append a bounded, provenance-safe delivery row to the event record."""
        current = sent_at or datetime.now(UTC)
        key = canonical_event_key(event)
        self.observe(event, now=current)
        record = self.records[key]
        history = record.setdefault("delivery_history", [])
        if not isinstance(history, list):
            history = []
            record["delivery_history"] = history
        trace = str(trace_id or event.get("trace_id") or "").strip()
        if trace and any(str(item.get("trace_id") or "") == trace for item in history if isinstance(item, dict)):
            return history[-1] if history else {}
        row: dict[str, Any] = {
            "event_key": key,
            "notification_id": str(event.get("notification_id") or event.get("compound_item_id") or key),
            "sent_at": current.isoformat(),
            "importance": str(event.get("importance") or event.get("risk_level") or "normal"),
            "alert_type": str(event.get("alert_type") or event.get("event_type") or event.get("kind") or "market"),
            "lifecycle_state": str(event.get("lifecycle_state") or "confirmed"),
            "reason": reason,
            "notification_theme_key": notification_theme_key(event),
            "risk": _material_state(event).get("risk", "R0"),
            "taiwan_priority": taiwan_investor_priority(event, now=current),
            "material_state_changed": True,
        }
        # Preserve release-bound provenance needed to reconcile a FinancialJuice
        # observation from ingress through delivery. Legacy events simply omit
        # these optional fields.
        for field in (
            "release_id", "snapshot_id", "delivery_status", "observation_id_hash",
            "item_id", "event_cluster_key", "vendor_importance", "prstk_risk",
            "notification_reason", "parser_version", "received_at", "notification_key",
            "delivery_receipts", "ingested_at", "candidate_at", "writer_wait_ms",
            "release_ready_at", "telegram_attempted_at", "delivery_result", "delay_reason",
        ):
            value = event.get(field)
            if value not in (None, "", [], {}):
                row[field] = value
        if trace:
            row["trace_id"] = trace
        history.append(row)
        # Retain enough rows for the hourly/per-event limits without allowing a
        # malformed producer to grow the public ledger indefinitely.
        record["delivery_history"] = history[-100:]
        record["last_reminded_at"] = current.isoformat()
        record["last_theme_notification_at"] = current.isoformat()
        record["last_notified_at"] = current.isoformat()
        record["notification_theme_key"] = notification_theme_key(event)
        record["material_state"] = _material_state(event)
        record["updated_at"] = current.isoformat()
        return row

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
        if left.get("notification_theme_key") or right.get("notification_theme_key"):
            merged["notification_theme_key"] = str(right.get("notification_theme_key") or left.get("notification_theme_key"))
        theme_times = [cls._timestamp(item.get("last_theme_notification_at")) for item in (left, right)]
        theme_time = max(theme_times)
        if theme_time != datetime.min.replace(tzinfo=UTC):
            merged["last_theme_notification_at"] = theme_time.isoformat()
            merged["last_notified_at"] = theme_time.isoformat()
        merged["material_state"] = right.get("material_state") or left.get("material_state") or {}
        verified = list(dict.fromkeys([
            *(left.get("verified_sources") or []),
            *(right.get("verified_sources") or []),
        ]))
        if verified:
            merged["verified_sources"] = verified
        deliveries = [
            *(left.get("delivery_history") or []),
            *(right.get("delivery_history") or []),
        ]
        unique: dict[str, dict[str, Any]] = {}
        for item in deliveries:
            if not isinstance(item, dict):
                continue
            identity = str(item.get("trace_id") or f"{item.get('sent_at', '')}:{item.get('reason', '')}")
            unique[identity] = item
        if unique:
            merged["delivery_history"] = sorted(
                unique.values(), key=lambda item: cls._timestamp(item.get("sent_at"))
            )[-100:]
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
