-- Private Telegram subscriptions.  Service-role workflows and the Telegram
-- webhook are the only writers/readers; no public projection exposes chat IDs.
create table if not exists public.telegram_subscriptions (
  chat_id text primary key,
  chat_type text not null default 'private' check (chat_type = 'private'),
  status text not null default 'active' check (status in ('active', 'stopped', 'blocked')),
  username text,
  is_editor boolean not null default false,
  source text not null default 'telegram_start',
  first_started_at timestamptz,
  last_started_at timestamptz,
  stopped_at timestamptz,
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint telegram_subscriptions_chat_id_numeric check (chat_id ~ '^-?[0-9]+$')
);

create index if not exists telegram_subscriptions_active_idx
  on public.telegram_subscriptions (status, chat_type, created_at, chat_id);

alter table public.telegram_subscriptions enable row level security;

comment on table public.telegram_subscriptions is
  'Private service-side Telegram subscriptions; never publish chat IDs to Pages.';
