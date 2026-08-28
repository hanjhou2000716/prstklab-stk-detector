-- Zero-cost durable aggregate receipt store.  Raw chat ids never enter this table.
create table if not exists public.delivery_receipt_events (
  id uuid primary key default gen_random_uuid(),
  trace_id text not null unique,
  receipt_kind text not null check (receipt_kind in ('production', 'photo_smoke', 'creator')),
  receipt_origin text not null check (receipt_origin = 'github_actions'),
  alert_id text,
  release_id text not null,
  snapshot_id text not null,
  delivery_mode text not null check (delivery_mode in ('text', 'photo')),
  delivery_status text not null check (delivery_status in ('delivered', 'partial', 'failed')),
  delivered_count integer not null check (delivered_count >= 0),
  failed_count integer not null check (failed_count >= 0),
  failed_recipient_hashes jsonb not null default '[]'::jsonb,
  notification_keys jsonb not null default '[]'::jsonb,
  renderer_error_type text,
  financialjuice_delivery_trace jsonb,
  reported_at timestamptz,
  received_at timestamptz not null default now()
);

create index if not exists delivery_receipt_events_release_idx
  on public.delivery_receipt_events (release_id, received_at desc);

create index if not exists delivery_receipt_events_status_idx
  on public.delivery_receipt_events (delivery_status, received_at desc);

alter table public.delivery_receipt_events enable row level security;

comment on table public.delivery_receipt_events is
  'Idempotent aggregate delivery receipts written by the signed Cloudflare Worker endpoint.';
