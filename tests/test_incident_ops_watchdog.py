from __future__ import annotations

import pytest

from scripts import incident_ops_watchdog as watchdog
from scripts.incident_ops_auth import IncidentOpsAuthError


def _env() -> dict[str, str]:
    return {
        "GITHUB_REPOSITORY": watchdog.REPOSITORY,
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_SHA": "a" * 40,
        "INCIDENT_OPS_URL": "https://prstk.account.workers.dev",
        "INCIDENT_OPS_MODE": "shadow",
        "ACTIONS_ID_TOKEN_REQUEST_URL": "https://pipelines.actions.githubusercontent.com/token",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "request-token",
    }


def _body(**overrides):
    result = {
        "ok": True,
        "mode": "shadow",
        "operational_status": "shadow",
        "recipient_fixed": "hanjhou2000716@gmail.com",
        "ready_to_cutover": False,
        "gmail_configured": False,
        "receipt_gmail_configured": False,
        "telegram_admin_fallback_configured": False,
        "delivery_unknown": 0,
        "stale_inbox_receipts": 0,
    }
    result.update(overrides)
    return result


def test_shadow_mode_is_observed_without_false_failure(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "fetch_oidc_token", lambda *args, **kwargs: "oidc")
    monkeypatch.setattr(watchdog, "worker_get_json", lambda *args, **kwargs: _body())
    result = watchdog.inspect_ops_health(environment=_env())
    assert result["status"] == "shadow_ready_for_observation"
    assert result["health"]["ready_to_cutover"] is False


def test_live_degraded_state_is_preserved_for_workflow_failure(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "fetch_oidc_token", lambda *args, **kwargs: "oidc")
    monkeypatch.setattr(watchdog, "worker_get_json", lambda *args, **kwargs: _body(
        mode="live", operational_status="degraded", ok=False,
    ))
    environment = _env()
    environment["INCIDENT_OPS_MODE"] = "live"
    result = watchdog.inspect_ops_health(environment=environment)
    assert result["status"] == "live_degraded"


def test_worker_and_github_cutover_modes_must_match(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "fetch_oidc_token", lambda *args, **kwargs: "oidc")
    monkeypatch.setattr(watchdog, "worker_get_json", lambda *args, **kwargs: _body(mode="live", operational_status="ready", ok=True, ready_to_cutover=True))
    with pytest.raises(watchdog.OpsWatchdogError, match="mode_mismatch"):
        watchdog.inspect_ops_health(environment=_env())


def test_wrong_repository_is_rejected_before_oidc(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "fetch_oidc_token", lambda *args, **kwargs: pytest.fail("unexpected OIDC"))
    environment = _env()
    environment["GITHUB_REPOSITORY"] = "attacker/repo"
    with pytest.raises(watchdog.OpsWatchdogError, match="repository_identity_invalid"):
        watchdog.inspect_ops_health(environment=environment)


def test_worker_auth_failure_is_not_relabelled_as_healthy(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "fetch_oidc_token", lambda *args, **kwargs: "oidc")
    monkeypatch.setattr(watchdog, "worker_get_json", lambda *args, **kwargs: (_ for _ in ()).throw(IncidentOpsAuthError("offline")))
    with pytest.raises(IncidentOpsAuthError):
        watchdog.inspect_ops_health(environment=_env())
