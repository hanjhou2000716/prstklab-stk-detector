create table if not exists public.delivery_receipts (
  id uuid primary key default gen_random_uuid(),
  trace_id text not null,
  alert_id text,
  release_id text,
  snapshot_id text,
  recipient_hash text not null,
  status text not null check (status in ('delivered', 'failed', 'retryable', 'blocked')),
  message_id bigint,
  error_class text,
  sent_at timestamptz not null default now(),
  unique (trace_id, recipient_hash)
);

create index if not exists delivery_receipts_trace_idx
  on public.delivery_receipts (trace_id, sent_at desc);

alter table public.delivery_receipts enable row level security;

comment on table public.delivery_receipts is
  'Privacy-safe per-recipient Telegram delivery outcomes; recipient_hash is never a raw chat id.';
