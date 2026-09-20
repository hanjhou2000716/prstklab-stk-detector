"""Post-migration verification for the private market observation store.

This module deliberately emits statuses instead of API response bodies.  It is
used by the migration workflow after ``supabase db push`` and can also be run
locally with a service-role credential.  No mail, Telegram identifier, token,
password, or connection string is ever included in the result.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from typing import Any

import requests

EXPECTED_MIGRATIONS = (
    "202609170001",
    "202609180001",
    "202609200001",
    "202609210001",
)


class VerificationError(RuntimeError):
    """A safe, stable verification failure code."""

    def __init__(self, code: str, *, failed_checks: tuple[str, ...] = ()) -> None:
        super().__init__(code)
        self.code = code
        self.failed_checks = failed_checks


class SupabaseManagementClient:
    """Minimal Management API client with redacted failures."""

    def __init__(self, project_ref: str, access_token: str, *, session: requests.Session | None = None) -> None:
        self.project_ref = project_ref.strip()
        self.session = session or requests.Session()
        self.headers = {
            "Authorization": f"Bearer {access_token.strip()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self.base_url = f"https://api.supabase.com/v1/projects/{self.project_ref}"

    def project(self) -> dict[str, Any]:
        try:
            response = self.session.get(f"{self.base_url}", headers=self.headers, timeout=30)
        except requests.RequestException as exc:
            raise VerificationError("token_unauthorized") from exc
        if response.status_code in {401, 403}:
            raise VerificationError("token_unauthorized")
        if not response.ok:
            raise VerificationError("token_unauthorized")
        try:
            value = response.json()
        except ValueError as exc:
            raise VerificationError("token_unauthorized") from exc
        return value if isinstance(value, dict) else {}

    def query(self, sql: str, *, read_only: bool) -> Any:
        try:
            response = self.session.post(
                f"{self.base_url}/database/query",
                headers=self.headers,
                json={"query": sql, "read_only": read_only},
                timeout=45,
            )
        except requests.RequestException as exc:
            raise VerificationError(
                "schema_verification_failed" if read_only else "token_database_write_denied"
            ) from exc
        if response.status_code in {401, 403}:
            raise VerificationError("token_database_write_denied" if not read_only else "token_unauthorized")
        if not response.ok:
            raise VerificationError("schema_verification_failed" if read_only else "backup_smoke_failed")
        try:
            return response.json()
        except ValueError as exc:
            raise VerificationError("schema_verification_failed" if read_only else "backup_smoke_failed") from exc


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("result", "data", "rows"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def _first_row(payload: Any) -> dict[str, Any]:
    rows = _rows(payload)
    return rows[0] if rows else {}


SCHEMA_QUERY = """
select
  to_regclass('public.market_observations') is not null as market_observations_exists,
  to_regclass('public.market_source_state') is not null as market_source_state_exists,
  to_regclass('public.financialjuice_priority_pending') is not null as fj_pending_exists,
  exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'market_observations'
      and column_name = 'expires_at'
  ) as retention_column_exists,
  to_regprocedure('public.purge_expired_market_observations()') is not null as purge_function_exists,
  exists (
    select 1 from pg_constraint c
    where c.conrelid = 'public.market_observations'::regclass
      and c.contype = 'u'
      and pg_get_constraintdef(c.oid) like '%(instrument_id, provider, market_date, quote_basis)%'
  ) as market_observation_unique_key,
  exists (
    select 1 from pg_indexes
    where schemaname = 'public' and indexname = 'market_observations_latest_idx'
  ) as latest_index_exists,
  coalesce((
    select c.relrowsecurity from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relname = 'market_observations'
  ), false) as market_observations_rls,
  coalesce((
    select c.relrowsecurity from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relname = 'market_source_state'
  ), false) as market_source_state_rls,
  not exists (
    select 1 from information_schema.role_table_grants
    where table_schema = 'public'
      and table_name in ('market_observations', 'market_source_state')
      and grantee in ('anon', 'authenticated')
  ) as public_roles_revoked,
  has_table_privilege('service_role', 'public.market_observations', 'SELECT') as service_role_market_select,
  has_table_privilege('service_role', 'public.market_observations', 'INSERT') as service_role_market_insert,
  has_table_privilege('service_role', 'public.market_observations', 'UPDATE') as service_role_market_update,
  has_table_privilege('service_role', 'public.market_source_state', 'SELECT') as service_role_state_select,
  has_table_privilege('service_role', 'public.market_source_state', 'INSERT') as service_role_state_insert,
  has_table_privilege('service_role', 'public.market_source_state', 'UPDATE') as service_role_state_update,
  not has_function_privilege('anon', 'public.purge_expired_market_observations()', 'EXECUTE')
    and not has_function_privilege('authenticated', 'public.purge_expired_market_observations()', 'EXECUTE')
    as purge_public_roles_revoked,
  has_function_privilege('service_role', 'public.purge_expired_market_observations()', 'EXECUTE')
    as purge_service_role_execute,
  to_regprocedure('public.transition_financialjuice_priority_delivery(text, text, text, text, timestamptz, timestamptz)')
    is not null as fj_delivery_function_exists,
  exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'financialjuice_priority_pending'
      and column_name = 'delivery_status'
  ) as fj_delivery_status_exists
"""

HISTORY_QUERY = """
select version::text as version
from supabase_migrations.schema_migrations
where version in ('202609170001', '202609180001', '202609200001', '202609210001')
order by version
"""

TRANSACTION_SMOKE_QUERY = """
begin;
savepoint market_backup_canary;
set local role service_role;
insert into public.market_observations (
  instrument_id, ticker, provider, source_tier, market_date, price,
  quote_basis, quality_status, payload_hash, parser_version, expires_at
) values (
  'healthcheck:market-backup', 'HEALTHCHECK', 'healthcheck', 'backup',
  current_date, 1, 'healthcheck', 'verified',
  'healthcheck-payload-hash', 'healthcheck-v1', now() + interval '1 hour'
);
select 1 from public.market_observations
 where instrument_id = 'healthcheck:market-backup'
   and provider = 'healthcheck'
   and quote_basis = 'healthcheck';
update public.market_observations
   set price = 2
 where instrument_id = 'healthcheck:market-backup'
   and provider = 'healthcheck'
   and quote_basis = 'healthcheck';
insert into public.market_source_state (
  instrument_id, status, consecutive_failures, fallback_used, circuit_state
) values ('healthcheck:market-backup', 'healthy', 0, false, 'closed')
on conflict (instrument_id) do update set status = excluded.status;
select 1 from public.market_source_state
 where instrument_id = 'healthcheck:market-backup';
update public.market_source_state
   set status = 'unavailable'
 where instrument_id = 'healthcheck:market-backup';
rollback to savepoint market_backup_canary;
release savepoint market_backup_canary;
commit;
"""

TRANSACTION_ROLE_QUERY = """
begin;
set local role service_role;
select current_user;
rollback;
"""

TRANSACTION_MARKET_QUERY = """
begin;
savepoint market_backup_canary;
set local role service_role;
insert into public.market_observations (
  instrument_id, ticker, provider, source_tier, market_date, price,
  quote_basis, quality_status, payload_hash, parser_version, expires_at
) values (
  'healthcheck:market-backup', 'HEALTHCHECK', 'healthcheck', 'backup',
  current_date, 1, 'healthcheck', 'verified',
  'healthcheck-payload-hash', 'healthcheck-v1', now() + interval '1 hour'
);
select 1 from public.market_observations
 where instrument_id = 'healthcheck:market-backup'
   and provider = 'healthcheck'
   and quote_basis = 'healthcheck';
update public.market_observations
   set price = 2
 where instrument_id = 'healthcheck:market-backup'
   and provider = 'healthcheck'
   and quote_basis = 'healthcheck';
rollback to savepoint market_backup_canary;
release savepoint market_backup_canary;
commit;
"""

TRANSACTION_STATE_QUERY = """
begin;
savepoint market_backup_canary;
set local role service_role;
insert into public.market_source_state (
  instrument_id, status, consecutive_failures, fallback_used, circuit_state
) values ('healthcheck:market-backup', 'healthy', 0, false, 'closed')
on conflict (instrument_id) do update set status = excluded.status;
select 1 from public.market_source_state
 where instrument_id = 'healthcheck:market-backup';
update public.market_source_state
   set status = 'unavailable'
 where instrument_id = 'healthcheck:market-backup';
rollback to savepoint market_backup_canary;
release savepoint market_backup_canary;
commit;
"""


def _all_true(row: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return all(row.get(key) is True for key in keys)


def _failed_checks(row: dict[str, Any], keys: tuple[str, ...]) -> tuple[str, ...]:
    """Return only safe check names; never include SQL results or credentials."""
    return tuple(key for key in keys if row.get(key) is not True)


def _service_role_rest_read(url: str, service_role_key: str, *, session: requests.Session) -> bool:
    endpoint = f"{url.rstrip('/')}/rest/v1/market_source_state"
    try:
        response = session.get(
            endpoint,
            headers={
                "apikey": service_role_key,
                "Authorization": f"Bearer {service_role_key}",
                "Accept": "application/json",
            },
            params={"select": "instrument_id", "limit": "1"},
            timeout=30,
        )
    except requests.RequestException as exc:
        raise VerificationError("backup_smoke_failed", failed_checks=("service_role_rest_read",)) from exc
    if response.status_code in {401, 403} or not response.ok:
        raise VerificationError("backup_smoke_failed", failed_checks=("service_role_rest_read",))
    return True


def verify_market_backup(
    *, project_ref: str, access_token: str, supabase_url: str, service_role_key: str,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Verify project identity, schema, RLS, migration history and rollback smoke."""
    if not project_ref.strip() or not access_token.strip():
        raise VerificationError("token_unauthorized")
    if not supabase_url.strip() or not service_role_key.strip():
        raise VerificationError("backup_smoke_failed")

    client = SupabaseManagementClient(project_ref, access_token, session=session)
    project = client.project()
    project_identity = str(project.get("id") or project.get("ref") or project.get("project_ref") or "")
    if project_identity and project_identity != project_ref:
        raise VerificationError("project_ref_mismatch")

    schema_row = _first_row(client.query(SCHEMA_QUERY, read_only=True))
    schema_keys = (
        "market_observations_exists", "market_source_state_exists", "fj_pending_exists",
        "retention_column_exists", "purge_function_exists", "market_observation_unique_key",
        "latest_index_exists", "fj_delivery_function_exists", "fj_delivery_status_exists",
    )
    rls_keys = (
        "market_observations_rls", "market_source_state_rls", "public_roles_revoked",
        "service_role_market_select", "service_role_market_insert", "service_role_market_update",
        "service_role_state_select", "service_role_state_insert", "service_role_state_update",
        "purge_public_roles_revoked", "purge_service_role_execute",
    )
    if not _all_true(schema_row, schema_keys):
        raise VerificationError(
            "schema_verification_failed",
            failed_checks=_failed_checks(schema_row, schema_keys),
        )
    if not _all_true(schema_row, rls_keys):
        raise VerificationError(
            "rls_verification_failed",
            failed_checks=_failed_checks(schema_row, rls_keys),
        )

    history_rows = _rows(client.query(HISTORY_QUERY, read_only=True))
    registered = {str(row.get("version")) for row in history_rows}
    if not set(EXPECTED_MIGRATIONS).issubset(registered):
        raise VerificationError(
            "schema_verification_failed",
            failed_checks=tuple(
                f"missing_migration:{version}"
                for version in EXPECTED_MIGRATIONS
                if version not in registered
            ),
        )

    http_session = session or requests.Session()
    _service_role_rest_read(supabase_url, service_role_key, session=http_session)
    transaction_stages = (
        ("transaction_role", TRANSACTION_ROLE_QUERY),
        ("transaction_market_observation", TRANSACTION_MARKET_QUERY),
        ("transaction_market_source_state", TRANSACTION_STATE_QUERY),
        ("transaction_canary", TRANSACTION_SMOKE_QUERY),
    )
    for stage, query in transaction_stages:
        try:
            client.query(query, read_only=False)
        except VerificationError as exc:
            raise VerificationError(
                "backup_smoke_failed",
                failed_checks=(stage,),
            ) from exc
    verified_at = datetime.now(UTC).isoformat()
    return {
        "migration_status": "verified",
        "schema_status": "verified",
        "rls_status": "verified",
        "service_role_write_status": "verified",
        "service_role_read_status": "verified",
        "canary_cleanup_status": "rolled_back",
        "registered_migrations": sorted(registered),
        "verified_at": verified_at,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-ref", default=os.getenv("SUPABASE_PROJECT_ID", ""))
    parser.add_argument("--access-token", default=os.getenv("SUPABASE_ACCESS_TOKEN", ""))
    parser.add_argument("--supabase-url", default=os.getenv("SUPABASE_URL", ""))
    parser.add_argument("--service-role-key", default=os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""))
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = verify_market_backup(
            project_ref=args.project_ref,
            access_token=args.access_token,
            supabase_url=args.supabase_url,
            service_role_key=args.service_role_key,
        )
    except VerificationError as exc:
        print(json.dumps({
            "status": "failed",
            "error_code": exc.code,
            "failed_checks": list(exc.failed_checks),
        }, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "complete", **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
