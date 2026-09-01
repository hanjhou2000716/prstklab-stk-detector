from pathlib import Path

import pytest

from src.production_text_acceptance import run
from src.release_gate import ReleaseGateResult
from src.telegram_client import TextDeliveryReceipt


def _gate(*, allowed: bool = True) -> ReleaseGateResult:
    return ReleaseGateResult(
        allowed=allowed, release_id="release-acceptance", snapshot_id="market-acceptance",
        errors=() if allowed else ("public manifest unavailable",),
        manifest={"status": "ready", "release_id": "release-acceptance", "market_snapshot_id": "market-acceptance"},
    )


def test_retired_photo_entrypoint_sends_one_release_bound_text(tmp_path: Path) -> None:
    calls: list[dict] = []

    def sender(**kwargs):
        calls.append(kwargs)
        assert kwargs["chat_ids"] == ("test-chat",)
        assert all(code not in kwargs["text"] for code in ("R0", "R1", "R2", "R3", "R4"))
        assert kwargs["prstk_risk_level"] == "R2"
        return (TextDeliveryReceipt("a", "release-acceptance", "market-acceptance", "hash", "delivered", message_id=1),)

    report = run(manifest=tmp_path / "manifest.json", public_url="https://example.test/prstk/",
                 token="token", chat_id="test-chat", verifier=lambda **_: _gate(), sender=sender)
    assert report["ok"] is True
    assert report["delivery_mode"] == "text"
    assert report["recipient_count"] == 1
    assert len(calls) == 1
    assert "photo" not in calls[0]


def test_text_acceptance_never_sends_when_public_release_is_blocked() -> None:
    called = False

    def sender(**_):
        nonlocal called
        called = True
        raise AssertionError("sender must not run")

    report = run(manifest="site/data/release-manifest.json", public_url="https://example.test/prstk/",
                 token="token", chat_id="test-chat", verifier=lambda **_: _gate(allowed=False), sender=sender)
    assert report["ok"] is False
    assert report["status"] == "release_blocked"
    assert report["delivery_performed"] is False
    assert called is False


@pytest.mark.parametrize("value", ["test-a,test-b", "test-a\ntest-b", ""])
def test_text_acceptance_rejects_broadcast_recipient(value: str) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        run(manifest="site/data/release-manifest.json", public_url="https://example.test/prstk/",
            token="token", chat_id=value, verifier=lambda **_: _gate())
