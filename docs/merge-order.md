# PR merge order

The production reliability work is intentionally reviewable as a stacked
sequence. Merge with **Create a merge commit**, keep the source branches until
the full stack is merged, and retarget/refresh the next PR only after the
previous one is green.

## Current order

1. `#418` → `#419` → `#420` → `#421` → `#422` → `#423` → `#424` → `#425`
2. `#426` → `#427` → `#428` → `#429` → `#430` → `#431` → `#432`
3. `#433` → `#434` → `#435` → `#436` → `#437` → `#438` → `#439` → `#440`

The final four PRs are cumulative branches based on the preceding reliability
fixes. Do not squash or rebase them while the stack is being merged; doing so
makes it harder to verify that each release-gate and research-state change was
actually applied. No PR in this sequence is auto-merged by the agent.

## Post-merge gate

After the last merge, dispatch the data refresh and deploy workflows, verify a
`status=ready` release manifest and matching snapshot IDs, then run the
Railway → Pages → Mini App → Telegram dry-run/E2E sequence. Production
recipients must not receive test messages; use the explicitly approved single
test chat only.
