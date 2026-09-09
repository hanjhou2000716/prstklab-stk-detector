-- Persist bounded, privacy-safe Gmail reconciliation diagnostics.
-- This contains counters and stable reason labels only; no mail body,
-- address, Gmail transport ID, OAuth value or history cursor is stored.
alter table public.gmail_watch_state
  add column if not exists last_sync_diagnostics jsonb;

comment on column public.gmail_watch_state.last_sync_diagnostics is
  'Last bounded Gmail sync counters and candidate reasons; no raw mail or transport identifiers.';
