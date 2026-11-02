from __future__ import annotations

import pytest

from scripts import incident_ops_verify_mail as verification


def _environment(**updates: str) -> dict[str, str]:
    return {
        "GITHUB_REPOSITORY": verification.REPOSITORY,
        "INPUT_CONFIRM_SEND": "yes",
        "INPUT_VERIFICATION_ID": "link-check-20261102-01",
        "INCIDENT_OPS_URL": "https://prstk-test.account.workers.dev",
        "INCIDENT_OPS_AUDIENCE": "https://prstk-incident-ops",
        "ACTIONS_ID_TOKEN_REQUEST_URL": "https://pipelines.actions.githubusercontent.com/oidc",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "request-token",
        **updates,
    }


def test_requires_explicit_owner_confirmation_before_oidc_or_send(monkeypatch):
    called = []
    monkeypatch.setattr(verification, "fetch_oidc_token", lambda *_a, **_k: called.append("oidc"))

    with pytest.raises(verification.MailVerificationError, match="explicit_confirmation_required"):
        verification.send_owner_verification(environment=_environment(INPUT_CONFIRM_SEND="no"))

    assert called == []


def test_verification_targets_only_the_fixed_mailbox_and_reuses_supplied_identity(monkeypatch):
    posts = []
    monkeypatch.setattr(verification, "fetch_oidc_token", lambda *_a, **_k: "short-lived-oidc")
    monkeypatch.setattr(verification, "worker_post_json", lambda *args, **kwargs: (
        posts.append((args, kwargs)) or {
            "ok": True,
            "verification_id": "link-check-20261102-01",
            "delivery_id": "a" * 64,
            "recipient": verification.RECIPIENT,
            "state": "sent_verified",
            "delivery_verified": True,
            "inbox_verified": False,
            "message_id": "<fixed@example.invalid>",
            "content_sha256": "b" * 64,
        }
    ))

    result = verification.send_owner_verification(environment=_environment())

    assert result["delivery_verified"] is True
    assert result["inbox_verified"] is False
    assert result["recipient"] == "hanjhou2000716@gmail.com"
    assert posts[0][0][1] == "/ops/mail/verify"
    assert posts[0][0][2] == {
        "confirmation": "SEND_ONE_VERIFICATION_EMAIL",
        "verification_id": "link-check-20261102-01",
    }
    assert posts[0][1]["token"] == "short-lived-oidc"


@pytest.mark.parametrize("verification_id", ["short", "contains space 123", "x" * 65])
def test_rejects_invalid_verification_identity_before_network(monkeypatch, verification_id):
    monkeypatch.setattr(verification, "fetch_oidc_token", lambda *_a, **_k: pytest.fail("must not request OIDC"))
    with pytest.raises(verification.MailVerificationError, match="verification_id_invalid"):
        verification.send_owner_verification(environment=_environment(INPUT_VERIFICATION_ID=verification_id))
