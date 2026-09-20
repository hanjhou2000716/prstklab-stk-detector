-- Verify the real service_role path without leaving a canary row behind.
-- PostgREST invokes SECURITY INVOKER functions as the JWT role. The nested
-- PL/pgSQL block is a subtransaction and rolls back after verification.
create or replace function public.verify_market_backup_canary()
returns jsonb
language plpgsql
security invoker
set search_path = public
as $$
declare
  market_seen boolean;
  market_updated boolean;
  state_seen boolean;
  state_updated boolean;
begin
  begin
    insert into public.market_observations (
      instrument_id, ticker, provider, source_tier, market_date, price,
      quote_basis, quality_status, payload_hash, parser_version, expires_at
    ) values (
      'healthcheck:market-backup', 'HEALTHCHECK', 'healthcheck', 'backup',
      current_date, 1, 'healthcheck', 'verified',
      'healthcheck-payload-hash', 'healthcheck-v1', now() + interval '1 hour'
    );
    select exists (
      select 1 from public.market_observations
      where instrument_id = 'healthcheck:market-backup'
        and provider = 'healthcheck'
        and quote_basis = 'healthcheck'
        and price = 1
    ) into market_seen;
    update public.market_observations
       set price = 2
     where instrument_id = 'healthcheck:market-backup'
       and provider = 'healthcheck'
       and quote_basis = 'healthcheck';
    select exists (
      select 1 from public.market_observations
      where instrument_id = 'healthcheck:market-backup'
        and provider = 'healthcheck'
        and quote_basis = 'healthcheck'
        and price = 2
    ) into market_updated;
    insert into public.market_source_state (
      instrument_id, status, consecutive_failures, fallback_used, circuit_state
    ) values ('healthcheck:market-backup', 'healthy', 0, false, 'closed')
    on conflict (instrument_id) do update set status = excluded.status;
    select exists (
      select 1 from public.market_source_state
      where instrument_id = 'healthcheck:market-backup'
    ) into state_seen;
    update public.market_source_state
       set status = 'unavailable'
     where instrument_id = 'healthcheck:market-backup';
    select exists (
      select 1 from public.market_source_state
      where instrument_id = 'healthcheck:market-backup'
        and status = 'unavailable'
    ) into state_updated;
    if not coalesce(market_seen, false)
       or not coalesce(market_updated, false)
       or not coalesce(state_seen, false)
       or not coalesce(state_updated, false) then
      raise exception using errcode = 'P0002', message = 'canary_verification_failed';
    end if;
    raise exception using errcode = 'P0001', message = 'canary_rollback';
  exception
    when others then
      if sqlstate <> 'P0001' then
        raise;
      end if;
  end;
  return jsonb_build_object(
    'status', 'rolled_back',
    'market_observation', 'verified',
    'market_source_state', 'verified'
  );
end;
$$;

revoke all on function public.verify_market_backup_canary() from public;
revoke all on function public.verify_market_backup_canary() from anon, authenticated;
grant execute on function public.verify_market_backup_canary() to service_role;
