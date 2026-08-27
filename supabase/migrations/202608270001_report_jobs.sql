-- PRStK zero-cost production path.
-- The service role is used only by the Worker/Actions backend.  Public and
-- anon clients must not read reports or submit jobs without the Worker gate.

create table if not exists public.report_jobs (
  id uuid primary key default gen_random_uuid(),
  market text not null check (market in ('tw', 'us')),
  intro text not null default '' check (char_length(intro) <= 2000),
  outro text not null default '' check (char_length(outro) <= 2000),
  status text not null default 'queued' check (status in ('queued', 'running', 'completed', 'failed')),
  requested_by text not null default '' check (char_length(requested_by) <= 128),
  error text null check (char_length(error) <= 500),
  created_at timestamptz not null default timezone('utc', now()),
  started_at timestamptz null,
  completed_at timestamptz null,
  constraint report_jobs_terminal_time check (
    (status in ('queued', 'running') and completed_at is null)
    or status in ('completed', 'failed')
  )
);

create table if not exists public.reports (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references public.report_jobs(id) on delete cascade,
  market text not null check (market in ('tw', 'us')),
  content text not null check (char_length(content) <= 200000),
  created_at timestamptz not null default timezone('utc', now()),
  unique (job_id)
);

create table if not exists public.system_status (
  component text primary key check (component <> ''),
  status text not null check (status in ('ok', 'degraded', 'error', 'unknown')),
  last_success_at timestamptz null,
  last_error text null check (char_length(last_error) <= 500),
  updated_at timestamptz not null default timezone('utc', now())
);

create index if not exists report_jobs_status_created_idx on public.report_jobs(status, created_at desc);
create index if not exists reports_job_created_idx on public.reports(job_id, created_at desc);

alter table public.report_jobs enable row level security;
alter table public.reports enable row level security;
alter table public.system_status enable row level security;

comment on table public.report_jobs is 'Asynchronous report jobs; access only through the authenticated Worker.';
comment on table public.reports is 'Immutable report result for one job; backend-only access.';
comment on table public.system_status is 'Non-secret component health consumed by the Worker health endpoint.';
