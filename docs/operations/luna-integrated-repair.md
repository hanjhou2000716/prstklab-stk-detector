# Luna integrated repair: release, schedule, and market-card operations

This runbook accompanies the deployment-identity, scheduled-delivery, and
market-scoped card changes. It does not authorize historical resend, force,
production refresh, migration, or manually initiated Telegram delivery.

## US premarket backup trigger (external cron-job.org)

The GitHub schedule supplies both UTC candidates (`0 13 * * 1-5` and
`0 14 * * 1-5`). The receiver accepts only the candidate that matches the
NYSE session open minus 30 minutes. The external backup must use the same
exchange-local anchor, so its schedule is 09:00 on weekdays in
`America/New_York`; holidays and exceptional closures are rejected by the
NYSE calendar in the receiver.

Configure the existing cron-job.org job as follows:

| Setting | Value |
|---|---|
| Schedule | `0 9 * * 1-5` |
| Time zone | `America/New_York` |
| Method | `POST` |
| URL | `https://api.github.com/repos/hanjhou2000716/prstklab-stk-detector/dispatches` |
| `Accept` | `application/vnd.github+json` |
| `Content-Type` | `application/json` |
| `Authorization` | `Bearer <existing fine-grained token>` |

Use a fine-grained token restricted to this repository with only the
`Contents: write` permission needed by the repository-dispatch endpoint. Do
not put the token in the request body, a shared screenshot, workflow log, or
this repository.

Request body:

```json
{
  "event_type": "scheduled-brief",
  "client_payload": {
    "slot": "us_premarket",
    "scheduled_slot": "us_premarket",
    "dispatch_unix": "%cjo:unixtime%",
    "trace_id": "%cjo:uuid4%",
    "time_zone": "America/New_York",
    "schedule_contract_version": "4",
    "trigger_kind": "cron-job.org",
    "notify": true,
    "force": false
  }
}
```

The external service must expand both placeholders at send time. Do not replace
them with a timestamp generated while editing the job. The scheduler's timezone
setting handles DST; the receiver still validates the payload against the
NYSE calendar and refuses a mismatched/closed session. Keep this backup enabled
alongside the two GitHub UTC candidates, not as an additional send identity.

## External-setting verification handoff

The external scheduler is not controlled by repository workflows. A maintainer
with existing access must inspect the saved job and confirm all of the settings
above before calling the backup trigger configured. Do not run an ad-hoc
dispatch to test it because that could publish or notify. After the next natural
NYSE premarket anchor, verify the workflow summary shows the correct NY date,
09:00 `America/New_York` anchor, `notify_candidate`, a verified deployment and
release, and either one complete delivered receipt per configured recipient or
an explicit `already_delivered` result. Confirm a repeated natural trigger did
not increase the delivered receipt count. Until both the saved configuration
and a natural run are inspected, report external scheduling as pending.

## Release and notification acceptance

- Match source commit, content `release_id`/snapshot ID, Pages artifact ID, and
  the actual Pages deployment ID/status URL. Never infer the deployment ID from
  a hash or override `GITHUB_SHA`.
- Release-gate retries are bounded to 180 seconds and apply only to propagation
  or transient network failures. Identity, snapshot, summary, and hash mismatch
  are fail-closed; no Telegram sender may run.
- A scheduled slot is expected to notify independently of whether it contains
  a high-scoring news event. Missing quotes/statistics are disclosed in the
  target-market card; missing auxiliary Taiwan statistics do not delay the
  report.
- Taiwan post-close cards separate TAIEX cash-index close, named-month TXF
  regular-session quote, and supplementary TWSE statistics. US premarket cards
  separate the prior cash-index closes, ES/NQ/YM futures, and SOX context.
  No market may fill missing values for the other.
- A natural FinancialJuice item is complete only when the immutable public
  summary, release-bound deep link, Telegram delivery, and recipient receipt
  refer to the same event/release/snapshot identity. Historical quarantined
  items remain quarantined until separately reviewed.
