-- Separate Gmail push, synchronization and candidate-decision timestamps.
-- This migration is additive and keeps the existing private cursor, ledger and
-- public-safe observation contracts readable during rollout.
alter table public.gmail_watch_state
  add column if not exists last_push_received_at timestamptz,
  add column if not exists last_sync_started_at timestamptz,
  add column if not exists last_sync_completed_at timestamptz,
  add column if not exists last_sync_status text,
  add column if not exists last_sync_error text;

alter table public.gmail_pubsub_events
  add column if not exists dispatch_requested_at timestamptz,
  add column if not exists sync_started_at timestamptz,
  add column if not exists sync_completed_at timestamptz,
  add column if not exists candidate_decided_at timestamptz;

-- Older rows used `dispatched` for "GitHub dispatch accepted".  Keep that
-- value readable, but allow the new state machine to distinguish a request
-- from completed synchronization.
alter table public.gmail_pubsub_events
  drop constraint if exists gmail_pubsub_events_dispatch_status_check;

alter table public.gmail_pubsub_events
  add constraint gmail_pubsub_events_dispatch_status_check
  check (dispatch_status in (
    'pending', 'dispatching', 'dispatch_requested', 'processing',
    'completed', 'dispatched', 'failed'
  ));

comment on column public.gmail_watch_state.last_notification_at is
  'Legacy compatibility timestamp; new code uses last_push_received_at for Pub/Sub ingress.';
comment on column public.gmail_watch_state.last_push_received_at is
  'Verified Gmail Pub/Sub receipt time; never updated by history parsing or manual replay.';
comment on column public.gmail_watch_state.last_sync_completed_at is
  'Completed bounded Gmail history synchronization time.';
comment on column public.gmail_pubsub_events.dispatch_requested_at is
  'Time GitHub accepted a sync request; it is not proof that the workflow completed.';
comment on column public.gmail_pubsub_events.candidate_decided_at is
  'Time the sync produced a terminal candidate classification.';
