-- Durable, private state for fresh FinancialJuice priority candidates whose
-- public summary is still being repaired.  This table is never part of the
-- Pages/public observation projection and contains no raw mail or recipient ID.
create table if not exists public.financialjuice_priority_pending (
  canonical_fact_key text not null,
  material_fact_version text not null,
  event_ref text not null,
  summary_contract_version text not null,
  summary_status text not null check (summary_status in ('pending', 'ready', 'expired', 'contract_failed')),
  summary_reason text not null,
  source_published_at timestamptz not null,
  first_detected_at timestamptz not null,
  last_checked_at timestamptz not null,
  expires_at timestamptz not null,
  attempt_count integer not null default 0 check (attempt_count >= 0),
  last_run_id text,
  last_run_sha text,
  updated_at timestamptz not null default now(),
  primary key (canonical_fact_key, material_fact_version),
  unique (event_ref)
);

create index if not exists financialjuice_priority_pending_active_idx
  on public.financialjuice_priority_pending (summary_status, expires_at, source_published_at);

alter table public.financialjuice_priority_pending enable row level security;

create or replace function public.upsert_financialjuice_priority_pending(
  p_canonical_fact_key text,
  p_material_fact_version text,
  p_event_ref text,
  p_summary_contract_version text,
  p_summary_status text,
  p_summary_reason text,
  p_source_published_at timestamptz,
  p_checked_at timestamptz,
  p_last_run_id text default null,
  p_last_run_sha text default null
) returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  row_value public.financialjuice_priority_pending;
begin
  insert into public.financialjuice_priority_pending(
    canonical_fact_key, material_fact_version, event_ref,
    summary_contract_version, summary_status, summary_reason,
    source_published_at, first_detected_at, last_checked_at,
    expires_at, attempt_count, last_run_id, last_run_sha, updated_at
  ) values (
    p_canonical_fact_key, p_material_fact_version, p_event_ref,
    p_summary_contract_version, p_summary_status, left(p_summary_reason, 120),
    p_source_published_at, p_checked_at, p_checked_at,
    p_source_published_at + interval '30 minutes', 1, p_last_run_id, p_last_run_sha, p_checked_at
  )
  on conflict (canonical_fact_key, material_fact_version) do update set
    event_ref = excluded.event_ref,
    summary_contract_version = excluded.summary_contract_version,
    summary_status = excluded.summary_status,
    summary_reason = excluded.summary_reason,
    last_checked_at = excluded.last_checked_at,
    attempt_count = public.financialjuice_priority_pending.attempt_count + 1,
    last_run_id = coalesce(excluded.last_run_id, public.financialjuice_priority_pending.last_run_id),
    last_run_sha = coalesce(excluded.last_run_sha, public.financialjuice_priority_pending.last_run_sha),
    updated_at = excluded.updated_at;

  select * into row_value
    from public.financialjuice_priority_pending
   where canonical_fact_key = p_canonical_fact_key
     and material_fact_version = p_material_fact_version;
  return to_jsonb(row_value);
end;
$$;

revoke all on function public.upsert_financialjuice_priority_pending(text, text, text, text, text, text, timestamptz, timestamptz, text, text) from public, anon, authenticated;
grant execute on function public.upsert_financialjuice_priority_pending(text, text, text, text, text, text, timestamptz, timestamptz, text, text) to service_role;
revoke all on table public.financialjuice_priority_pending from public, anon, authenticated;
grant select, insert, update on table public.financialjuice_priority_pending to service_role;

comment on table public.financialjuice_priority_pending is
  'Private service-role-only FJ priority summary recovery state; no raw mail or Telegram identifiers.';
