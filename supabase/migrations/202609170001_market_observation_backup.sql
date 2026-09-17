-- Durable, private last-known-good market observations.
-- This table contains normalized values only; provider payloads and secrets
-- never enter the public Pages artifact.
create table if not exists public.market_observations (
  id bigint generated always as identity primary key,
  instrument_id text not null,
  ticker text not null,
  provider text not null,
  source_tier text not null check (source_tier in ('official', 'public-market', 'backup')),
  market_date date not null,
  observed_at timestamptz,
  price numeric,
  previous_close numeric,
  change numeric,
  change_percent numeric,
  volume numeric,
  quote_basis text not null,
  currency text,
  quality_status text not null check (quality_status in ('verified', 'recent_close', 'degraded_with_fallback')),
  payload_hash text not null,
  parser_version text not null,
  source_url text,
  fetched_at timestamptz not null default now(),
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  unique (instrument_id, provider, market_date, quote_basis)
);

create index if not exists market_observations_latest_idx
  on public.market_observations (instrument_id, market_date desc, fetched_at desc);

create table if not exists public.market_source_state (
  instrument_id text primary key,
  status text not null check (status in (
    'healthy', 'degraded_with_fallback', 'stale_last_good',
    'insufficient_history', 'unavailable', 'contract_invalid'
  )),
  active_provider text,
  last_success_at timestamptz,
  last_failure_at timestamptz,
  consecutive_failures integer not null default 0 check (consecutive_failures >= 0),
  last_error_code text,
  fallback_used boolean not null default false,
  fallback_market_date date,
  circuit_state text not null default 'closed'
    check (circuit_state in ('closed', 'open', 'half_open')),
  updated_at timestamptz not null default now()
);

alter table public.market_observations enable row level security;
alter table public.market_source_state enable row level security;

revoke all on public.market_observations from anon, authenticated;
revoke all on public.market_source_state from anon, authenticated;
grant select, insert, update on public.market_observations to service_role;
grant select, insert, update on public.market_source_state to service_role;
grant usage, select on sequence public.market_observations_id_seq to service_role;

comment on table public.market_observations is
  'Private normalized last-known-good market observations; not a public data source.';
comment on table public.market_source_state is
  'Private provider health and bounded fallback state for market observations.';

create or replace function public.purge_expired_market_observations()
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  removed integer;
begin
  delete from public.market_observations where expires_at < now();
  get diagnostics removed = row_count;
  return removed;
end;
$$;

revoke all on function public.purge_expired_market_observations() from public;
grant execute on function public.purge_expired_market_observations() to service_role;
