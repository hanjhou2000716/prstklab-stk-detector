# Google Cloud Gmail Watch IAM audit — 2026-08-24

This is a read-only audit of project `calendar-automation-497107`. It records
configuration evidence without storing OAuth tokens, refresh tokens, service
account keys, message bodies, or secret values.

## Verified configuration

| Item | Observed state |
|---|---|
| Gmail push topic | `prstk-gmail-watch` |
| Push subscription | `prstk-gmail-push-sub` |
| Delivery mode | Push with authentication enabled |
| Push target | `/gmail/push` on the configured Railway service |
| Push identity | `prstk-gmail-pubsub` service account; no user-managed key present |
| Acknowledgement deadline | 10 seconds |
| Retry policy | Immediate retry |
| Dead-letter topic | Not configured |
| Exactly-once delivery | Not enabled |
| Subscription retention | 7 days |
| Inactivity expiry | 31 days |

The endpoint and push identity match the values expected by the Railway Gmail
ingress contract. The absence of a push-identity key is correct: Pub/Sub should
use an authenticated service identity, not a long-lived key stored in Railway.

## IAM finding

The project IAM page shows the `calendar-reader` service account with a
project-level **Editor** role and a large excess-permission recommendation.
This is broader than the Gmail Watch runtime needs. The dedicated
`prstk-gmail-pubsub` identity is separate and does not need Editor access.

No IAM policy, role, key, OAuth grant, Pub/Sub setting, or Railway variable was
changed during this audit. The finding is therefore safe to review and does
not interrupt the current Watch lease.

## Least-privilege remediation plan

1. Inventory the exact API calls made by the Watch renewal and history-sync
   runtime in a staging or Policy Simulator run.
2. Replace the runtime's project-level Editor grant with resource-scoped
   permissions:
   - publish only to the Gmail Watch topic for the Pub/Sub push identity;
   - consume/get only on the intended subscription for a pull consumer, if one
     is introduced;
   - Gmail mailbox access remains an OAuth grant, not a Cloud IAM role.
3. Confirm one complete renew → Pub/Sub push → Railway cursor persistence cycle.
4. Remove the broad grant only after the cycle and rollback path are evidenced.

Permission edits require an action-time operator confirmation because they can
change production access. Until that controlled change is completed, the
release gate treats Gmail as configured only when the Railway health lease and
sanitized observation are both present.

## Evidence boundary

This audit proves configuration alignment, not a live mail delivery. A complete
acceptance record still requires a sanitized Gmail observation reaching Railway
and the next release artifact with matching release/snapshot lineage.

Rollback is limited to restoring the previous IAM policy version and retaining
the existing Pub/Sub subscription; no service-account key should be created as
a workaround.
