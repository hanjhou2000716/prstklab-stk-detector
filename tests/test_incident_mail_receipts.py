from __future__ import annotations

import pytest

from scripts import incident_mail_receipts as receipts


def _env() -> dict[str, str]:
    return {
        "GITHUB_REPOSITORY": receipts.REPOSITORY,
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_SHA": "a" * 40,
        "INCIDENT_OPS_URL": "https://prstk.account.workers.dev",
        "ACTIONS_ID_TOKEN_REQUEST_URL": "https://pipelines.actions.githubusercontent.com/token",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "request-token",
    }


def test_no_pending_receipts_is_a_valid_noop(monkeypatch) -> None:
    monkeypatch.setattr(receipts, "fetch_oidc_token", lambda *args, **kwargs: "oidc")
    monkeypatch.setattr(receipts, "worker_get_json", lambda *args, **kwargs: {"ok": True, "recipient": receipts.RECIPIENT, "pending": []})
    monkeypatch.setattr(receipts, "worker_post_json", lambda *args, **kwargs: pytest.fail("must not post"))
    result = receipts.audit_pending_receipts(environment=_env())
    assert result["status"] == "no_pending_receipts"
    assert result["checked_count"] == 0


def test_only_delivery_identity_is_sent_for_inbox_verification(monkeypatch) -> None:
    delivery_id = "b" * 64
    calls = []
    monkeypatch.setattr(receipts, "fetch_oidc_token", lambda *args, **kwargs: "oidc")
    monkeypatch.setattr(receipts, "worker_get_json", lambda *args, **kwargs: {
        "ok": True, "recipient": receipts.RECIPIENT,
        "pending": [{"delivery_id": delivery_id, "message_id": "not-forwarded", "payload": "not-forwarded"}],
    })

    def post(base, path, payload, *, token):
        calls.append((base, path, payload, token))
        return {"ok": True, "delivery_id": delivery_id, "receipt_state": "inbox_verified", "gmail_message_id": "verified-id"}

    monkeypatch.setattr(receipts, "worker_post_json", post)
    result = receipts.audit_pending_receipts(environment=_env())
    assert calls == [(_env()["INCIDENT_OPS_URL"], "/ops/mail/receipt", {"delivery_id": delivery_id}, "oidc")]
    assert result["inbox_verified_count"] == 1


def test_unavailable_gmail_receipt_remains_a_failure_not_a_delivery_claim(monkeypatch) -> None:
    delivery_id = "c" * 64
    monkeypatch.setattr(receipts, "fetch_oidc_token", lambda *args, **kwargs: "oidc")
    monkeypatch.setattr(receipts, "worker_get_json", lambda *args, **kwargs: {
        "ok": True, "recipient": receipts.RECIPIENT, "pending": [{"delivery_id": delivery_id}],
    })
    monkeypatch.setattr(receipts, "worker_post_json", lambda *args, **kwargs: {
        "ok": False, "delivery_id": delivery_id, "receipt_state": "verification_unavailable",
    })
    with pytest.raises(receipts.MailReceiptError, match="not_verified:verification_unavailable"):
        receipts.audit_pending_receipts(environment=_env())
