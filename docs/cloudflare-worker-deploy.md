# Cloudflare Worker deployment

The canonical Worker source is `worker/src/index.ts` and is deployed by the
manual `Deploy canonical Cloudflare Worker` workflow. The workflow performs a
local Wrangler dry-run before uploading and never runs on ordinary pushes.

## Required repository configuration

- Secret: `CLOUDFLARE_API_TOKEN`
- Variable: `CLOUDFLARE_ACCOUNT_ID`

The API token should be scoped to the target account with Workers Script edit
permission only. Do not commit or print the token. Runtime secrets remain in
Cloudflare Worker settings and are not copied into GitHub logs.

Wrangler 4 reads the account from `CLOUDFLARE_ACCOUNT_ID`; the deploy workflow
does not pass the removed `--account-id` CLI option. `--keep-vars` preserves
variables configured in the Worker dashboard while publishing the canonical
bundle.

## Verification

After a successful deployment, verify the public health endpoint and the
signed `/api/delivery-receipt` canary. A `404 NOT_FOUND` on the receipt route
means the active Worker is still an older deployment; do not send a Telegram
production notification until the route and receipt persistence are verified.

On 2026-08-29 the canonical Worker was successfully deployed from the
unmerged feature branch in workflow run `33253334569`. A follow-up
single-recipient photo acceptance is still required to prove receipt
persistence; the prior attempt reached Telegram but both receipt backends
returned 404. A non-mutating post-deploy probe subsequently returned HTTP 200
from `/api/health` and HTTP 401 `INVALID_SIGNATURE` from
`/api/delivery-receipt`, proving that the canonical route is active without
writing a synthetic receipt. The signed production canary is still required
to verify Supabase persistence end to end.

Rollback uses the Cloudflare Worker Versions page to promote the previous
known-good version. The workflow is intentionally manual so a missing token or
an invalid bundle fails closed without changing the active version.
