"""P0-18 external alert trust-boundary contracts."""

import hmac

import pytest

from src.external_alert import normalize_alert, verify_signature


def _alert(**overrides):
    values = {
        "category": "conflict",
        "summary": "official talks update",
        "source": "jin10",
        "event_id": "conflict-18",
        "occurred_at": "2026-08-14T01:00:00Z",
        "evidence": [{"domain": "reuters.com", "url": "https://www.reuters.com/world/example", "seen_at": "2026-08-14T01:01:00Z"}],
        "risk_level": "warning",
        "market_sync_confirmed": True,
    }
    values.update(overrides)
    return normalize_alert(**values)


def test_external_alert_requires_https_provenance():
    with pytest.raises(ValueError):
        _alert(evidence=[{"domain": "reuters.com", "url": "http://www.reuters.com/world/example", "seen_at": "2026-08-14T01:01:00Z"}])


def test_black_swan_high_risk_requires_official_and_market_confirmation():
    with pytest.raises(ValueError, match="official and market-sync"):
        _alert(category="black_swan", risk_level="high", official_confirmed=False)
    assert _alert(category="black_swan", risk_level="high", official_confirmed=True).risk_level == "high"


def test_signature_covers_canonical_provenance_and_rejects_tampering():
    alert = _alert()
    secret = "external-shared-secret"
    signature = hmac.new(secret.encode(), alert.canonical.encode(), "sha256").hexdigest()
    verify_signature(alert, f"sha256={signature}", secret)
    with pytest.raises(ValueError):
        verify_signature(_alert(summary="tampered"), f"sha256={signature}", secret)
