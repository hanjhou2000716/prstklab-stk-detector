-- Keep transient Gmail storage failures durable without changing the Gmail
-- cursor.  The table contains only bounded operational state; no mail data,
-- address, OAuth value, message id or history cursor is stored here.
create table if not exists public.gmail_sync_health (
  id text primary key check (id = 'primary'),
  status text not null default 'healthy'
    check (status in ('healthy', 'recovered_after_retry', 'retry_pending', 'persistent_failure')),
  first_failure_at timestamptz,
  consecutive_failure_count integer not null default 0
    check (consecutive_failure_count >= 0),
  last_failure_at timestamptz,
  last_error text,
  last_run_id text,
  last_run_sha text,
  last_success_at timestamptz,
  next_retry_at timestamptz,
  updated_at timestamptz not null default now()
);

alter table public.gmail_sync_health enable row level security;

comment on table public.gmail_sync_health is
  'Private bounded Gmail sync recovery state; contains no mail or transport identifiers.';

create or replace function public.record_gmail_sync_failure(
  p_error text,
  p_failed_at timestamptz,
  p_run_id text default null,
  p_run_sha text default null,
  p_next_retry_at timestamptz default null
)
returns table (
  status text,
  first_failure_at timestamptz,
  consecutive_failure_count integer,
  last_failure_at timestamptz,
  last_error text,
  last_run_id text,
  last_run_sha text,
  next_retry_at timestamptz
)
language plpgsql
security definer
set search_path = public
as $$
declare
  current_row public.gmail_sync_health%rowtype;
  next_count integer;
begin
  select * into current_row
    from public.gmail_sync_health
   where id = 'primary'
   for update;

  if current_row.id is null then
    next_count := 1;
    insert into public.gmail_sync_health(
      id, status, first_failure_at, consecutive_failure_count,
      last_failure_at, last_error, last_run_id, last_run_sha,
      next_retry_at, updated_at
    ) values (
      'primary', 'retry_pending', p_failed_at, next_count,
      p_failed_at, left(coalesce(p_error, 'transient_storage_error'), 80),
      left(p_run_id, 80), left(p_run_sha, 80), p_next_retry_at, now()
    );
  else
    next_count := current_row.consecutive_failure_count + 1;
    update public.gmail_sync_health
       set status = case
         when next_count >= 2 or p_failed_at - current_row.first_failure_at >= interval '10 minutes'
           then 'persistent_failure'
         else 'retry_pending'
       end,
           first_failure_at = coalesce(current_row.first_failure_at, p_failed_at),
           consecutive_failure_count = next_count,
           last_failure_at = p_failed_at,
           last_error = left(coalesce(p_error, 'transient_storage_error'), 80),
           last_run_id = left(p_run_id, 80),
           last_run_sha = left(p_run_sha, 80),
           next_retry_at = p_next_retry_at,
           updated_at = now()
     where id = 'primary';
  end if;

  return query
  select h.status, h.first_failure_at, h.consecutive_failure_count,
         h.last_failure_at, h.last_error, h.last_run_id, h.last_run_sha,
         h.next_retry_at
    from public.gmail_sync_health h
   where h.id = 'primary';
end;
$$;

create or replace function public.clear_gmail_sync_failure(
  p_success_at timestamptz
)
returns table (status text, had_failure boolean)
language plpgsql
security definer
set search_path = public
as $$
declare
  previous_count integer := 0;
begin
  select consecutive_failure_count into previous_count
    from public.gmail_sync_health
   where id = 'primary'
   for update;

  insert into public.gmail_sync_health(
    id, status, consecutive_failure_count, last_success_at, updated_at
  ) values ('primary', 'healthy', 0, p_success_at, now())
  on conflict (id) do update set
    status = 'healthy', first_failure_at = null,
    consecutive_failure_count = 0, last_failure_at = null,
    last_error = null, last_run_id = null, last_run_sha = null,
    last_success_at = excluded.last_success_at, next_retry_at = null,
    updated_at = excluded.updated_at;

  return query select
    case when previous_count > 0 then 'recovered_after_retry' else 'healthy' end,
    previous_count > 0;
end;
$$;

revoke all on function public.record_gmail_sync_failure(text, timestamptz, text, text, timestamptz) from public;
revoke all on function public.clear_gmail_sync_failure(timestamptz) from public;
grant execute on function public.record_gmail_sync_failure(text, timestamptz, text, text, timestamptz) to service_role;
grant execute on function public.clear_gmail_sync_failure(timestamptz) to service_role;
