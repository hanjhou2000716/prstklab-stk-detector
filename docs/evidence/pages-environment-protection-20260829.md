# Pages environment protection evidence

The manual `deploy-pages.yml` dispatch from
`feat/workflow-secret-scope-20260829` was intentionally rejected before a
runner started (`run 33256369705`). GitHub reported that the branch is not
allowed to deploy to the protected `github-pages` environment. The job had no
steps and consumed zero runner time.

This is a deployment-boundary result, not a release-data failure. A successful
`main` deployment remains the only accepted production path; feature branches
must not bypass the environment protection rule. The latest public `main`
release was independently verified read-only in
`external-acceptance-2026-08-29-worker-pages.json` with a ready manifest and
7/7 artifact hashes matching.

Rollback: do not loosen the environment rule. If a new release is required,
merge the reviewed PR chain and dispatch `deploy-pages.yml` from `main`; the
release gate preserves the previous public release when validation fails.
