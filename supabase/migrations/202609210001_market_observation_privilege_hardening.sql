-- Explicitly keep the private purge helper unavailable to API roles.
-- The original migration revoked PUBLIC execution, but Supabase role grants
-- must also be revoked explicitly so anon/authenticated cannot execute it via
-- a direct or inherited privilege.
revoke execute on function public.purge_expired_market_observations() from anon;
revoke execute on function public.purge_expired_market_observations() from authenticated;
revoke execute on function public.purge_expired_market_observations() from public;
grant execute on function public.purge_expired_market_observations() to service_role;
