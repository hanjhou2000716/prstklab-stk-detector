-- Prevent a retry or a late Gmail replay from moving a priority delivery
-- backwards after it has reached ready/delivery_pending/delivered.
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
  next_delivery_status text;
begin
  if p_summary_status not in ('pending', 'ready', 'expired', 'contract_failed') then
    raise exception 'priority_summary_status_invalid';
  end if;

  next_delivery_status := case p_summary_status
    when 'ready' then 'ready'
    when 'expired' then 'expired'
    when 'contract_failed' then 'contract_failed'
    else 'summary_pending'
  end;

  insert into public.financialjuice_priority_pending(
    canonical_fact_key, material_fact_version, event_ref,
    summary_contract_version, summary_status, summary_reason,
    source_published_at, first_detected_at, last_checked_at,
    expires_at, attempt_count, last_run_id, last_run_sha, updated_at,
    delivery_status, next_retry_at, last_progress_at, last_blocking_reason
  ) values (
    p_canonical_fact_key, p_material_fact_version, p_event_ref,
    p_summary_contract_version, p_summary_status, left(p_summary_reason, 120),
    p_source_published_at, p_checked_at, p_checked_at,
    p_source_published_at + interval '30 minutes', 1, p_last_run_id, p_last_run_sha, p_checked_at,
    next_delivery_status,
    case when next_delivery_status = 'summary_pending' then p_checked_at + interval '5 minutes' else null end,
    p_checked_at,
    case when next_delivery_status = 'summary_pending' then left(p_summary_reason, 120) else null end
  )
  on conflict (canonical_fact_key, material_fact_version) do update set
    event_ref = coalesce(nullif(public.financialjuice_priority_pending.event_ref, ''), excluded.event_ref),
    summary_contract_version = excluded.summary_contract_version,
    summary_status = case
      when public.financialjuice_priority_pending.delivery_status in ('delivered', 'expired', 'contract_failed', 'delivery_pending')
        then public.financialjuice_priority_pending.summary_status
      when public.financialjuice_priority_pending.delivery_status = 'ready'
           and excluded.summary_status = 'pending'
        then public.financialjuice_priority_pending.summary_status
      else excluded.summary_status
    end,
    summary_reason = excluded.summary_reason,
    last_checked_at = excluded.last_checked_at,
    attempt_count = public.financialjuice_priority_pending.attempt_count + 1,
    last_run_id = coalesce(excluded.last_run_id, public.financialjuice_priority_pending.last_run_id),
    last_run_sha = coalesce(excluded.last_run_sha, public.financialjuice_priority_pending.last_run_sha),
    updated_at = excluded.updated_at,
    delivery_status = case
      when public.financialjuice_priority_pending.delivery_status in ('delivered', 'expired', 'contract_failed', 'delivery_pending')
        then public.financialjuice_priority_pending.delivery_status
      when public.financialjuice_priority_pending.delivery_status = 'ready'
           and excluded.delivery_status = 'summary_pending'
        then public.financialjuice_priority_pending.delivery_status
      else excluded.delivery_status
    end,
    next_retry_at = case
      when public.financialjuice_priority_pending.delivery_status in ('delivered', 'expired', 'contract_failed', 'delivery_pending', 'ready')
        then public.financialjuice_priority_pending.next_retry_at
      else excluded.next_retry_at
    end,
    last_progress_at = case
      when public.financialjuice_priority_pending.delivery_status in ('delivered', 'expired', 'contract_failed', 'delivery_pending', 'ready')
        then public.financialjuice_priority_pending.last_progress_at
      else excluded.last_progress_at
    end,
    last_blocking_reason = case
      when public.financialjuice_priority_pending.delivery_status in ('delivered', 'expired', 'contract_failed', 'delivery_pending', 'ready')
        then public.financialjuice_priority_pending.last_blocking_reason
      else excluded.last_blocking_reason
    end;

  select * into row_value
    from public.financialjuice_priority_pending
   where canonical_fact_key = p_canonical_fact_key
     and material_fact_version = p_material_fact_version;
  return to_jsonb(row_value);
end;
$$;

create or replace function public.transition_financialjuice_priority_delivery(
  p_event_ref text,
  p_expected_status text,
  p_next_status text,
  p_reason text default null,
  p_checked_at timestamptz default now(),
  p_next_retry_at timestamptz default null
) returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  row_value public.financialjuice_priority_pending;
begin
  if not (
    (p_expected_status = 'summary_pending' and p_next_status in ('ready', 'expired', 'contract_failed'))
    or (p_expected_status = 'ready' and p_next_status in ('delivery_pending', 'expired', 'contract_failed'))
    or (p_expected_status = 'delivery_pending' and p_next_status in ('delivered', 'expired', 'contract_failed'))
  ) then
    raise exception 'priority_delivery_transition_invalid';
  end if;

  update public.financialjuice_priority_pending
     set delivery_status = p_next_status,
         last_checked_at = p_checked_at,
         last_progress_at = p_checked_at,
         last_blocking_reason = case
           when p_next_status in ('summary_pending', 'contract_failed') then left(coalesce(p_reason, ''), 120)
           else null
         end,
         next_retry_at = case
           when p_next_status in ('summary_pending', 'delivery_pending') then p_next_retry_at
           else null
         end,
         delivered_at = case
           when p_next_status = 'delivered' then coalesce(delivered_at, p_checked_at)
           else delivered_at
         end,
         updated_at = p_checked_at
   where event_ref = p_event_ref
     and delivery_status = p_expected_status;

  select * into row_value
    from public.financialjuice_priority_pending
   where event_ref = p_event_ref
     and delivery_status = p_next_status;
  if not found then
    return '{}'::jsonb;
  end if;
  return to_jsonb(row_value);
end;
$$;

revoke all on function public.upsert_financialjuice_priority_pending(text, text, text, text, text, text, timestamptz, timestamptz, text, text) from public, anon, authenticated;
grant execute on function public.upsert_financialjuice_priority_pending(text, text, text, text, text, text, timestamptz, timestamptz, text, text) to service_role;
revoke all on function public.transition_financialjuice_priority_delivery(text, text, text, text, timestamptz, timestamptz) from public, anon, authenticated;
grant execute on function public.transition_financialjuice_priority_delivery(text, text, text, text, timestamptz, timestamptz) to service_role;
