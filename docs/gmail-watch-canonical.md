# Canonical Gmail Watch boundary

Gmail `users.watch` lease creation and renewal has one runtime owner:
`railway-monitor/gmail_watch.py:GmailWatchManager`.

`railway-monitor/gmail_watch_service.py` remains only because the Railway
application loop is asynchronous. It adapts the async HTTP client to the
canonical manager in a worker thread and translates the historical result
envelope. It must not add a second endpoint, renewal policy, retry policy or
cursor writer.

## Runtime paths

```text
Railway startup
  -> GmailIngressService.ensure_watch()
  -> GmailWatchManager.ensure_watch()

Railway async poll loop
  -> gmail_watch_service.renew_watch_if_due()
  -> asyncio.to_thread()
  -> GmailWatchManager.ensure_watch()
```

Both paths therefore share:

- the same OAuth and `users.watch` endpoints;
- the same renewal margin and retry cooldown;
- the same fail-closed configuration checks;
- the same privacy-safe cursor persistence and error taxonomy.

Recent failures are suppressed until `GMAIL_WATCH_RETRY_COOLDOWN_MINUTES`
expires. A controlled `force=True` check bypasses that cooldown for an
operator-triggered recovery test.

Run the offline guard with:

```text
python scripts/verify_canonical_overlap.py
```

The guard fails if the compatibility adapter grows a second manager class,
endpoint constant, or renewal function.

## Rollback

Revert the canonical Gmail Watch PR. This restores the prior adapter and does
not delete the durable Gmail cursor or alter private message content.
