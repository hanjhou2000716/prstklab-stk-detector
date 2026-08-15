# PR merge order

The production reliability work is intentionally reviewable as a stacked
sequence. Merge with **Create a merge commit**, keep the source branches until
the full stack is merged, and refresh the next PR only after its parent is
green.

## Current canonical order

1. [#620](https://github.com/hanjhou2000716/prstklab-stk-detector/pull/620) — fail closed on unsupported Creator parsers
2. [#621](https://github.com/hanjhou2000716/prstklab-stk-detector/pull/621) — derive news feeds from the canonical provider registry
3. [#622](https://github.com/hanjhou2000716/prstklab-stk-detector/pull/622) — enforce Railway keyword-bundle parity
4. [#623](https://github.com/hanjhou2000716/prstklab-stk-detector/pull/623) — package the canonical classifier for Railway
5. [#624](https://github.com/hanjhou2000716/prstklab-stk-detector/pull/624) — expose classifier provenance in Railway health

All five are currently open, mergeable, and have green CI. Use **Create a
merge commit** in this order. Keep every source branch until the complete
post-merge gate passes; do not squash or rebase this stack. The agent does not
auto-merge these PRs.

Older PR ranges previously listed in this file are historical and are not part
of the current merge queue.

## Post-merge gate

After the last merge, dispatch the data refresh and deploy workflows, verify a
`status=ready` release manifest and matching snapshot IDs, then run the
Railway → Pages → Mini App → Telegram dry-run/E2E sequence. Production
recipients must not receive test messages; use only the explicitly approved
single test chat.
