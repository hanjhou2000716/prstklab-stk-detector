# Production runtime audit modes

`src.runtime_audit` has two explicit modes:

- Default mode is a structural audit for checked-in fixtures. It reports a
  missing or stale release as warnings so local tests can inspect sample data.
- `--require-production` is the Pages deployment mode. It treats release-gate
  errors as failures and requires a ready manifest with matching market,
  research, and event snapshots.

Pages restores `data-release` first and runs the strict mode before upload. A
failed strict audit stops deployment and leaves the previous verified release
available for rollback.

```text
python -m src.runtime_audit
python -m src.runtime_audit --require-production
```

Rollback is release-based: restore the previous `status=ready` commit on
`data-release` and rerun the Pages deployment. No generated data is copied to
`main`.
