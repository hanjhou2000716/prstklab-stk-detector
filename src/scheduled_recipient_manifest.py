"""Atomic, privacy-preserving recipient manifest history for scheduled audits."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from src.alert_orchestrator import recipient_hash

SCHEMA_VERSION = "scheduled-recipient-manifest-v1"
_HASH_PATTERN = re.compile(r"^[0-9a-f]{12}$")
_CHAT_ID_PATTERN = re.compile(r"^-?\d+$")


@dataclass(frozen=True)
class RecipientSetVersion:
    """One immutable recipient set effective from an exact UTC instant."""

    version: str
    effective_at: str
    recipient_hashes: frozenset[str]


@dataclass(frozen=True)
class RecipientManifest:
    """Validated append-only recipient set history carried as one repository variable."""

    versions: tuple[RecipientSetVersion, ...]

    @property
    def latest(self) -> RecipientSetVersion:
        return self.versions[-1]

    @property
    def version(self) -> str:
        return self.latest.version

    @property
    def effective_at(self) -> str:
        return self.latest.effective_at

    @property
    def recipient_hashes(self) -> frozenset[str]:
        return self.latest.recipient_hashes

    def for_anchor(self, anchor: datetime) -> RecipientSetVersion | None:
        """Select the newest set effective at the immutable scheduled anchor."""
        instant = anchor.astimezone(UTC)
        applicable = [
            item for item in self.versions
            if datetime.fromisoformat(item.effective_at.replace("Z", "+00:00")) <= instant
        ]
        return applicable[-1] if applicable else None


def _normalized_effective_at(value: datetime | str) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError("expected_recipient_set_effective_at_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("expected_recipient_set_effective_at_invalid")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def recipient_set_version(recipient_hashes: set[str] | frozenset[str], effective_at: str) -> str:
    """Bind a sorted recipient hash set and its effective timestamp."""
    normalized_hashes = sorted({str(value).strip().casefold() for value in recipient_hashes if str(value).strip()})
    if not normalized_hashes or any(not _HASH_PATTERN.fullmatch(value) for value in normalized_hashes):
        raise ValueError("expected_recipient_set_hashes_unavailable")
    normalized_effective = _normalized_effective_at(effective_at)
    material = json.dumps(
        {"recipient_hashes": normalized_hashes, "effective_at": normalized_effective},
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return f"recipients-{hashlib.sha256(material).hexdigest()[:16]}"


def _entry_from_payload(payload: object) -> RecipientSetVersion:
    if not isinstance(payload, dict) or set(payload) != {"version", "effective_at", "recipient_hashes"}:
        raise ValueError("expected_recipient_set_manifest_invalid")
    version, effective_raw, hashes_raw = (
        payload.get("version"), payload.get("effective_at"), payload.get("recipient_hashes"),
    )
    if not isinstance(version, str) or not isinstance(effective_raw, str):
        raise ValueError("expected_recipient_set_manifest_invalid")
    if not isinstance(hashes_raw, list) or not hashes_raw:
        raise ValueError("expected_recipient_set_hashes_unavailable")
    if any(not isinstance(value, str) for value in hashes_raw):
        raise ValueError("expected_recipient_set_manifest_invalid")
    hashes_list = [value.strip().casefold() for value in hashes_raw]
    if (
        any(not _HASH_PATTERN.fullmatch(value) for value in hashes_list)
        or len(set(hashes_list)) != len(hashes_list)
    ):
        raise ValueError("expected_recipient_set_manifest_invalid")
    effective = _normalized_effective_at(effective_raw)
    normalized_version = version.strip()
    if not re.fullmatch(r"recipients-[0-9a-f]{16}", normalized_version):
        raise ValueError("expected_recipient_set_version_invalid")
    hashes = frozenset(hashes_list)
    if normalized_version != recipient_set_version(hashes, effective):
        raise ValueError("expected_recipient_set_fingerprint_mismatch")
    return RecipientSetVersion(normalized_version, effective, hashes)


def parse_recipient_manifest(raw: str) -> RecipientManifest:
    """Validate all append-only versions and reject partial/mixed updates."""
    if not str(raw or "").strip():
        raise ValueError("expected_recipient_set_manifest_unavailable")
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("expected_recipient_set_manifest_invalid") from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema_version", "versions"}
        or payload.get("schema_version") != SCHEMA_VERSION
    ):
        raise ValueError("expected_recipient_set_manifest_invalid")
    raw_versions = payload.get("versions")
    if not isinstance(raw_versions, list) or not raw_versions:
        raise ValueError("expected_recipient_set_manifest_versions_unavailable")
    versions = tuple(_entry_from_payload(item) for item in raw_versions)
    instants = [datetime.fromisoformat(item.effective_at.replace("Z", "+00:00")) for item in versions]
    if instants != sorted(instants) or len(set(instants)) != len(instants):
        raise ValueError("expected_recipient_set_manifest_history_invalid")
    if len({item.version for item in versions}) != len(versions):
        raise ValueError("expected_recipient_set_manifest_history_invalid")
    return RecipientManifest(versions)


def build_recipient_manifest(
    chat_ids: tuple[str, ...] | list[str],
    effective_at: datetime | str | None = None,
    prior_manifest_raw: str = "",
) -> dict[str, object]:
    """Append a fresh set to existing history without disclosing subscriber IDs."""
    normalized_ids = {str(value).strip() for value in chat_ids}
    if not normalized_ids:
        raise ValueError("expected_recipient_set_hashes_unavailable")
    if any(not _CHAT_ID_PATTERN.fullmatch(value) for value in normalized_ids):
        raise ValueError("telegram_subscription_invalid_chat_id")
    hashes = sorted({recipient_hash(value) for value in normalized_ids})
    effective = _normalized_effective_at(datetime.now(UTC) if effective_at is None else effective_at)
    previous: list[dict[str, object]] = []
    if str(prior_manifest_raw or "").strip():
        try:
            parsed = parse_recipient_manifest(prior_manifest_raw)
        except ValueError as exc:
            raise ValueError("existing_scheduled_recipient_manifest_invalid") from exc
        previous = [
            {
                "version": item.version,
                "effective_at": item.effective_at,
                "recipient_hashes": sorted(item.recipient_hashes),
            }
            for item in parsed.versions
        ]
        latest = parsed.latest
        effective_instant = datetime.fromisoformat(effective.replace("Z", "+00:00"))
        latest_instant = datetime.fromisoformat(latest.effective_at.replace("Z", "+00:00"))
        if effective_instant < latest_instant:
            raise ValueError("expected_recipient_set_effective_at_precedes_latest_version")
        if set(hashes) == set(latest.recipient_hashes):
            return {"schema_version": SCHEMA_VERSION, "versions": previous}
        if effective_instant == latest_instant:
            raise ValueError("expected_recipient_set_effective_at_not_monotonic")
    entry = {
        "version": recipient_set_version(set(hashes), effective),
        "effective_at": effective,
        "recipient_hashes": hashes,
    }
    return {"schema_version": SCHEMA_VERSION, "versions": [*previous, entry]}
