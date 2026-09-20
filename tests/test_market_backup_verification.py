from __future__ import annotations

import json

import pytest

from src.market_backup_verification import (
    EXPECTED_MIGRATIONS,
    SCHEMA_QUERY,
    TRANSACTION_SMOKE_QUERY,
    VerificationError,
    verify_market_backup,
)


class Response:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.ok = status_code < 400

    def json(self):
        return self._payload


class Session:
    def __init__(self, *, project=None, schema=None, history=None, rest=None, smoke=None):
        self.project = project or {"id": "jpsohtutyaondeyvcjls"}
        self.schema = schema or {
            key: True for key in (
                "market_observations_exists", "market_source_state_exists", "fj_pending_exists",
                "retention_column_exists", "purge_function_exists", "market_observation_unique_key",
                "latest_index_exists", "market_observations_rls", "market_source_state_rls",
                "public_roles_revoked", "service_role_market_select", "service_role_market_insert",
                "service_role_market_update", "service_role_state_select", "service_role_state_insert",
                "service_role_state_update", "purge_public_roles_revoked", "purge_service_role_execute",
                "fj_delivery_function_exists", "fj_delivery_status_exists",
                "service_role_canary_function_exists", "service_role_canary_public_roles_revoked",
                "service_role_canary_execute",
            )
        }
        self.history = [{"version": version} for version in EXPECTED_MIGRATIONS] if history is None else history
        self.rest = [] if rest is None else rest
        self.smoke = [{"ok": True}] if smoke is None else smoke
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if "/rest/v1/" in url:
            return Response(self.rest)
        return Response(self.project)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        if "/rest/v1/rpc/verify_market_backup_canary" in url:
            return Response({"status": "rolled_back"})
        query = str(kwargs.get("json", {}).get("query") or "")
        if "schema_migrations" in query:
            return Response(self.history)
        if "begin;" in query or "savepoint market_backup_canary" in query:
            return Response(self.smoke)
        assert query == SCHEMA_QUERY
        return Response([self.schema])


def test_verification_returns_safe_statuses_and_uses_read_only_schema_query():
    session = Session()

    result = verify_market_backup(
        project_ref="jpsohtutyaondeyvcjls",
        access_token="pat-value",
        supabase_url="https://example.supabase.co",
        service_role_key="service-role-value",
        session=session,
    )

    assert result["migration_status"] == "verified"
    assert result["schema_status"] == "verified"
    assert result["rls_status"] == "verified"
    assert result["service_role_write_status"] == "verified"
    assert result["canary_cleanup_status"] == "rolled_back"
    assert "pat-value" not in json.dumps(result)
    assert "service-role-value" not in json.dumps(result)
    query_calls = [call for call in session.calls if call[0] == "POST" and "/database/query" in call[1]]
    assert query_calls[0][2]["json"]["read_only"] is True
    assert all(call[2]["json"]["read_only"] is True for call in query_calls)
    assert any("/rest/v1/rpc/verify_market_backup_canary" in call[1] for call in session.calls)
    assert "rollback to savepoint" in TRANSACTION_SMOKE_QUERY


def test_verification_classifies_project_identity_mismatch_without_leaking_response():
    with pytest.raises(VerificationError, match="project_ref_mismatch"):
        verify_market_backup(
            project_ref="jpsohtutyaondeyvcjls",
            access_token="pat-value",
            supabase_url="https://example.supabase.co",
            service_role_key="service-role-value",
            session=Session(project={"id": "different-project"}),
        )


def test_verification_rejects_missing_migration_history():
    with pytest.raises(VerificationError, match="schema_verification_failed"):
        verify_market_backup(
            project_ref="jpsohtutyaondeyvcjls",
            access_token="pat-value",
            supabase_url="https://example.supabase.co",
            service_role_key="service-role-value",
            session=Session(history=[]),
        )
