import hashlib
import hmac
import json

import pytest

from src.external_alert import normalize_alert, stamp_snapshot, verify_signature


def signed_alert():
    alert = normalize_alert(
        category="macro",
        summary="CPI 高於預期",
        source="jin10",
        event_id="jin10-cpi-001",
        occurred_at="2026-07-26T08:30:00+08:00",
    )
    secret = "test-shared-secret"
    signature = hmac.new(secret.encode(), alert.canonical.encode(), hashlib.sha256).hexdigest()
    return alert, secret, signature


def test_external_alert_requires_matching_hmac_signature():
    alert, secret, signature = signed_alert()
    verify_signature(alert, f"sha256={signature}", secret)
    with pytest.raises(ValueError, match="簽章"):
        verify_signature(alert, "sha256=wrong", secret)


def test_external_alert_rejects_unknown_source_and_invalid_event_id():
    with pytest.raises(ValueError, match="來源"):
        normalize_alert(category="macro", summary="CPI 高於預期", source="unknown", event_id="event-1", occurred_at="2026-07-26T08:30:00+08:00")
    with pytest.raises(ValueError, match="識別碼"):
        normalize_alert(category="macro", summary="CPI 高於預期", source="jin10", event_id="invalid event id", occurred_at="2026-07-26T08:30:00+08:00")


def test_external_alert_accepts_cross_checked_gdelt_source():
    alert = normalize_alert(
        category="conflict", summary="衝突：Iran多源核對", source="gdelt",
        event_id="gdelt-conflict-1", occurred_at="2026-07-29T01:00:00+00:00",
        evidence=[
            {"domain": "apnews.com", "url": "https://apnews.com/example", "seen_at": "2026-07-29T01:00:00+00:00"},
            {"domain": "reuters.com", "url": "https://www.reuters.com/example", "seen_at": "2026-07-29T01:01:00+00:00"},
        ],
        market_sync_confirmed=True,
        market_sync=["NASDAQ"],
    )
    assert alert.source == "gdelt"
    assert [item["domain"] for item in alert.evidence_payload] == ["apnews.com", "reuters.com"]


def test_black_swan_external_alert_requires_market_sync_for_warning():
    with pytest.raises(ValueError, match="market-sync"):
        normalize_alert(
            category="black_swan",
            summary="重大地震影響供應鏈",
            source="gdelt",
            event_id="gdelt-black-swan-1",
            occurred_at="2026-07-29T01:00:00+00:00",
            market_sync_confirmed=False,
            evidence=[
                {"domain": "apnews.com", "url": "https://apnews.com/example", "seen_at": "2026-07-29T01:00:00+00:00"},
                {"domain": "reuters.com", "url": "https://www.reuters.com/example", "seen_at": "2026-07-29T01:01:00+00:00"},
            ],
        )


def test_black_swan_external_alert_high_risk_requires_both_confirmations():
    with pytest.raises(ValueError, match="official and market-sync"):
        normalize_alert(
            category="black_swan",
            summary="官方確認的重大災害",
            source="jin10",
            event_id="jin10-black-swan-1",
            occurred_at="2026-07-29T01:00:00+00:00",
            risk_level="高風險",
            official_confirmed=True,
            market_sync_confirmed=False,
            market_sync=["TAIEX"],
        )


def test_black_swan_external_alert_accepts_warning_after_market_sync():
    alert = normalize_alert(
        category="black_swan",
        summary="多源核對且市場同步",
        source="gdelt",
        event_id="gdelt-black-swan-2",
        occurred_at="2026-07-29T01:00:00+00:00",
        market_sync_confirmed=True,
        market_sync=["NIKKEI"],
        evidence=[
            {"domain": "apnews.com", "url": "https://apnews.com/example-2", "seen_at": "2026-07-29T01:00:00+00:00"},
            {"domain": "reuters.com", "url": "https://www.reuters.com/example-2", "seen_at": "2026-07-29T01:01:00+00:00"},
        ],
    )
    assert alert.risk_level == "警戒"
    assert alert.market_sync == ("NIKKEI",)


def test_external_alert_stamps_only_public_verified_fields(tmp_path):
    snapshot_path = tmp_path / "market.json"
    snapshot_path.write_text(json.dumps({"quotes": []}), encoding="utf-8")
    alert, _, _ = signed_alert()

    stamp_snapshot(alert, snapshot_path)

    result = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert result["external_alert"]["source"] == "jin10"
    assert result["external_alert"]["event_id"] == "jin10-cpi-001"
    assert result["external_alert"]["source_url"] == "https://www.jin10.com/"
    assert "signature" not in result["external_alert"]
