from pathlib import Path

import pytest

from src.alert_card_renderer import fallback_card
from src.production_photo_smoke_test import run
from src.release_gate import ReleaseGateResult
from src.telegram_client import PhotoDeliveryReceipt


def _gate(*, allowed: bool = True) -> ReleaseGateResult:
    return ReleaseGateResult(
        allowed=allowed,
        release_id="release-acceptance",
        snapshot_id="market-acceptance",
        errors=() if allowed else ("public manifest unavailable",),
        manifest={
            "status": "ready",
            "release_id": "release-acceptance",
            "market_snapshot_id": "market-acceptance",
        },
    )


def test_production_photo_smoke_is_release_bound_and_single_recipient(tmp_path: Path) -> None:
    calls: list[dict] = []

    def renderer(alert, output):
        assert alert["release_id"] == "release-acceptance"
        assert alert["snapshot_id"] == "market-acceptance"
        return fallback_card(output)

    def sender(**kwargs):
        calls.append(kwargs)
        assert kwargs["chat_ids"] == ("test-chat",)
        assert kwargs["release_id"] == "release-acceptance"
        assert kwargs["snapshot_id"] == "market-acceptance"
        assert kwargs["observation_id"]
        return (PhotoDeliveryReceipt(
            alert_id=kwargs["alert_id"], release_id=kwargs["release_id"],
            snapshot_id=kwargs["snapshot_id"], chat_id_hash="hash",
            status="delivered", message_id=1, observation_id=kwargs["observation_id"],
        ),)

    report = run(
        manifest=tmp_path / "manifest.json",
        public_url="https://example.test/prstk/",
        token="token",
        chat_id="test-chat",
        verifier=lambda **_: _gate(),
        renderer=renderer,
        sender=sender,
    )
    assert report["ok"] is True
    assert report["card_dimensions"] == {"width": 1080, "height": 1350}
    assert report["recipient_count"] == 1
    assert len(calls) == 1


def test_production_photo_smoke_never_sends_when_public_release_is_blocked() -> None:
    called = False

    def sender(**_):
        nonlocal called
        called = True
        raise AssertionError("sender must not run")

    report = run(
        manifest="site/data/release-manifest.json",
        public_url="https://example.test/prstk/",
        token="token",
        chat_id="test-chat",
        verifier=lambda **_: _gate(allowed=False),
        sender=sender,
    )
    assert report["ok"] is False
    assert report["status"] == "release_blocked"
    assert report["delivery_performed"] is False
    assert called is False


@pytest.mark.parametrize("value", ["test-a,test-b", "test-a\ntest-b", ""])
def test_production_photo_smoke_rejects_broadcast_recipient(value: str) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        run(
            manifest="site/data/release-manifest.json",
            public_url="https://example.test/prstk/",
            token="token",
            chat_id=value,
            verifier=lambda **_: _gate(),
        )

