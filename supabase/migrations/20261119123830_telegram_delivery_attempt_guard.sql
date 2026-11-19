-- Durable, per-recipient Telegram send guard.  Store only one-way identities;
-- raw Telegram chat IDs and message content never enter these tables.
create table if not exists public.telegram_delivery_attempt_state (
  notification_hash text not null check (notification_hash ~ '^[0-9a-f]{64}$'),
  recipient_hash text not null check (recipient_hash ~ '^[0-9a-f]{64}$'),
  status text not null default 'ready'
    check (status in ('ready', 'reserved', 'sending', 'retryable_failed', 'delivered', 'terminal_failed', 'delivery_unknown', 'expired')),
  attempt_count integer not null default 0 check (attempt_count between 0 and 3),
  active_attempt_id uuid,
  lease_expires_at timestamptz,
  deadline_at timestamptz not null,
  retry_after_at timestamptz,
  telegram_message_id bigint,
  last_error_class text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (notification_hash, recipient_hash),
  check (telegram_message_id is null or telegram_message_id > 0)
);

create table if not exists public.telegram_delivery_attempt_log (
  id bigint generated always as identity primary key,
  notification_hash text not null check (notification_hash ~ '^[0-9a-f]{64}$'),
  recipient_hash text not null check (recipient_hash ~ '^[0-9a-f]{64}$'),
  attempt_id uuid not null,
  transition text not null check (transition in ('reserved', 'started', 'delivered', 'retryable_failed', 'terminal_failed', 'delivery_unknown', 'expired', 'reservation_reclaimed')),
  error_class text,
  retry_after_at timestamptz,
  occurred_at timestamptz not null default now()
);

create index if not exists telegram_delivery_attempt_log_identity_idx
  on public.telegram_delivery_attempt_log (notification_hash, recipient_hash, occurred_at desc);

alter table public.telegram_delivery_attempt_state enable row level security;
alter table public.telegram_delivery_attempt_log enable row level security;
revoke all on public.telegram_delivery_attempt_state, public.telegram_delivery_attempt_log from public, anon, authenticated;
grant select, insert, update on public.telegram_delivery_attempt_state to service_role;
grant insert on public.telegram_delivery_attempt_log to service_role;
grant usage, select on sequence public.telegram_delivery_attempt_log_id_seq to service_role;

create or replace function public.transition_telegram_delivery_attempt(
  p_notification_hash text,
  p_recipient_hash text,
  p_operation text,
  p_attempt_id uuid,
  p_deadline_at timestamptz default null,
  p_retry_after_at timestamptz default null,
  p_result text default null,
  p_message_id bigint default null,
  p_lease_seconds integer default 60
) returns jsonb
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_state public.telegram_delivery_attempt_state%rowtype;
  v_now timestamptz := clock_timestamp();
  v_next text;
begin
  if p_notification_hash !~ '^[0-9a-f]{64}$'
     or p_recipient_hash !~ '^[0-9a-f]{64}$'
     or p_operation not in ('reserve', 'start', 'result')
     or p_attempt_id is null then
    raise exception 'invalid delivery attempt identity';
  end if;

  if p_operation = 'reserve' then
    if p_deadline_at is null then raise exception 'delivery deadline required'; end if;
    insert into public.telegram_delivery_attempt_state (
      notification_hash, recipient_hash, deadline_at
    ) values (p_notification_hash, p_recipient_hash, p_deadline_at)
    on conflict (notification_hash, recipient_hash) do nothing;
  end if;

  select * into v_state
    from public.telegram_delivery_attempt_state
    where notification_hash = p_notification_hash
      and recipient_hash = p_recipient_hash
    for update;
  if not found then raise exception 'delivery attempt not found'; end if;

  if p_operation = 'reserve' then
    if v_state.status = 'sending' and v_state.lease_expires_at <= v_now then
      update public.telegram_delivery_attempt_state
        set status = 'delivery_unknown', active_attempt_id = null,
            lease_expires_at = null, last_error_class = 'lease_expired_after_send_start',
            updated_at = v_now
        where notification_hash = p_notification_hash and recipient_hash = p_recipient_hash;
      insert into public.telegram_delivery_attempt_log
        (notification_hash, recipient_hash, attempt_id, transition, error_class)
        values (p_notification_hash, p_recipient_hash, v_state.active_attempt_id,
                'delivery_unknown', 'lease_expired_after_send_start');
      return jsonb_build_object('status', 'delivery_unknown');
    end if;
    if v_state.status in ('ready', 'reserved', 'retryable_failed') and v_state.deadline_at <= v_now then
      update public.telegram_delivery_attempt_state
        set status = 'expired', active_attempt_id = null, lease_expires_at = null, updated_at = v_now
        where notification_hash = p_notification_hash and recipient_hash = p_recipient_hash;
      insert into public.telegram_delivery_attempt_log
        (notification_hash, recipient_hash, attempt_id, transition)
        values (p_notification_hash, p_recipient_hash, p_attempt_id, 'expired');
      return jsonb_build_object('status', 'expired');
    end if;
    if v_state.status = 'delivered' then
      return jsonb_build_object('status', 'delivered', 'message_id', v_state.telegram_message_id);
    elsif v_state.status in ('delivery_unknown', 'terminal_failed', 'expired') then
      return jsonb_build_object('status', v_state.status);
    elsif v_state.status = 'sending' then
      return jsonb_build_object('status', 'sending');
    elsif v_state.status = 'retryable_failed' then
      if v_state.attempt_count >= 3 then return jsonb_build_object('status', 'attempt_limit'); end if;
      if v_state.retry_after_at is not null and v_state.retry_after_at > v_now then
        return jsonb_build_object('status', 'retry_wait', 'retry_after_at', v_state.retry_after_at);
      end if;
    elsif v_state.status = 'reserved' and v_state.lease_expires_at > v_now then
      return jsonb_build_object('status', 'reserved');
    elsif v_state.status not in ('ready', 'reserved', 'retryable_failed') then
      return jsonb_build_object('status', 'blocked');
    end if;

    if v_state.status = 'reserved' then
      insert into public.telegram_delivery_attempt_log
        (notification_hash, recipient_hash, attempt_id, transition)
        values (p_notification_hash, p_recipient_hash, v_state.active_attempt_id,
                'reservation_reclaimed');
    end if;
    update public.telegram_delivery_attempt_state
      set status = 'reserved', active_attempt_id = p_attempt_id,
          lease_expires_at = v_now + make_interval(secs => greatest(10, least(120, p_lease_seconds))),
          updated_at = v_now
      where notification_hash = p_notification_hash and recipient_hash = p_recipient_hash;
    insert into public.telegram_delivery_attempt_log
      (notification_hash, recipient_hash, attempt_id, transition)
      values (p_notification_hash, p_recipient_hash, p_attempt_id, 'reserved');
    return jsonb_build_object('status', 'reserved');
  end if;

  if p_operation = 'start' then
    if v_state.status <> 'reserved' or v_state.active_attempt_id <> p_attempt_id
       or v_state.lease_expires_at <= v_now or v_state.deadline_at <= v_now
       or v_state.attempt_count >= 3 then
      return jsonb_build_object('status', 'blocked');
    end if;
    update public.telegram_delivery_attempt_state
      set status = 'sending', attempt_count = attempt_count + 1,
          lease_expires_at = v_now + interval '2 minutes', updated_at = v_now
      where notification_hash = p_notification_hash and recipient_hash = p_recipient_hash;
    insert into public.telegram_delivery_attempt_log
      (notification_hash, recipient_hash, attempt_id, transition)
      values (p_notification_hash, p_recipient_hash, p_attempt_id, 'started');
    return jsonb_build_object('status', 'sending');
  end if;

  if v_state.status <> 'sending' or v_state.active_attempt_id <> p_attempt_id then
    return jsonb_build_object('status', v_state.status);
  end if;
  if p_result is null or p_result not in ('delivered', 'retryable_failed', 'terminal_failed', 'delivery_unknown') then
    raise exception 'invalid delivery attempt result';
  end if;
  if p_result = 'delivered' and (p_message_id is null or p_message_id <= 0) then
    raise exception 'telegram message identity required';
  end if;
  if p_result = 'retryable_failed' and p_retry_after_at is null then
    raise exception 'retry deadline required';
  end if;

  v_next := p_result;
  update public.telegram_delivery_attempt_state
    set status = v_next,
        active_attempt_id = null,
        lease_expires_at = null,
        retry_after_at = case when v_next = 'retryable_failed' then p_retry_after_at else null end,
        telegram_message_id = case when v_next = 'delivered' then p_message_id else telegram_message_id end,
        last_error_class = case when v_next = 'delivered' then null else v_next end,
        updated_at = v_now
    where notification_hash = p_notification_hash and recipient_hash = p_recipient_hash;
  insert into public.telegram_delivery_attempt_log
    (notification_hash, recipient_hash, attempt_id, transition, error_class, retry_after_at)
    values (p_notification_hash, p_recipient_hash, p_attempt_id, v_next,
            case when v_next = 'delivered' then null else v_next end,
            case when v_next = 'retryable_failed' then p_retry_after_at else null end);
  return jsonb_build_object('status', v_next, 'message_id', case when v_next = 'delivered' then p_message_id else null end);
end;
$$;

revoke all on function public.transition_telegram_delivery_attempt(text, text, text, uuid, timestamptz, timestamptz, text, bigint, integer) from public, anon, authenticated;
grant execute on function public.transition_telegram_delivery_attempt(text, text, text, uuid, timestamptz, timestamptz, text, bigint, integer) to service_role;

comment on table public.telegram_delivery_attempt_state is
  'Hashed per-recipient Telegram state. delivery_unknown is never automatically resent.';
comment on table public.telegram_delivery_attempt_log is
  'Append-only transitions for Telegram send guard; raw recipient IDs and message text are excluded.';
