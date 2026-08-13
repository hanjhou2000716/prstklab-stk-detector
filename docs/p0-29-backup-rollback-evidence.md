# P0-29 backup, rollback and disaster-recovery evidence

## Contract

The public data branch is an immutable release history, not a mutable cache.
Publishers use an isolated index and write only `refs/heads/data-release`.
Pages restores a selected release, validates its manifest and artifact hashes,
and keeps the previous successful release as the rollback target. An invalid
or incomplete release is never promoted to Telegram or the public Mini App.

## Verification

`tests/test_p0_29_backup_rollback_contract.py` covers:

- non-mutating publish dry-runs;
- an unavailable data branch returning an explicit, non-destructive result;
- a restore drill that checks the previous release tree before checkout and
  skips optional paths absent from that release;
- rollback manifest identity and artifact hash tamper detection; and
- ready/rolled-back state exclusivity.

Run the focused gate with:

```text
python -m pytest -q --basetemp=.test-tmp-p0-29 tests/test_p0_29_backup_rollback_contract.py tests/test_data_release.py tests/test_artifact_contract.py tests/test_release_manifest.py tests/test_release_gate.py
python -m ruff check src tests
```

## Recovery procedure

1. Stop notification delivery when the release gate fails.
2. Select the latest known-good `data-release` commit and record its release
   and snapshot IDs.
3. Restore that commit in a controlled Pages deployment.
4. Re-run manifest, artifact-hash and release-gate validation.
5. Resume notification only after the public release is readable and matches
   the manifest. Never delete `main` or rewrite release history.

## Rollback

Revert the P0-29 contract/test documentation commit if the verification
contract itself must be withdrawn. Operational rollback remains release-based;
it does not require deleting data or force-pushing a branch.

