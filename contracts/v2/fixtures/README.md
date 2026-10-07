# Contract v2 canonical fixtures

Every fixture in this directory is canonical input for **both** the Python
suite (`agent/tests/test_contract_v2.py`) and the Java suite
(`cinematic-bridge/.../FixtureTests.java`). Neither side may invent its own
copy of a request or a result: drift here must fail at least one suite.

Layout:

- `requests/*.json` — full HTTP envelopes (`{"request": {...}}`). Files with
  the `malformed-` prefix are intentionally invalid and must be REJECTED by
  schema validation in both languages; every other request must validate.
- `results/*.json` — operation-result bodies exactly as the bridge must emit
  them (complete envelope, `idempotency_key` included). `malformed-` files
  must be rejected; `duplicate-idempotent-replay.json` is what a retried
  write returns — the recorded outcome, never a second execution.
- `game-state/*.json` — truthful `GameStateV2` snapshots.
- `mocap-state/*.json` — observed `MocapStateV2` snapshots.
- `capabilities/*.json` — capability advertisements.
- `transcripts/*` — raw client-feedback lines pinned for the Mocap feedback
  classifier. See `transcripts/README.md` for provenance and the fail-closed
  rule.

Rules (plan v2 §Phase A acceptance):

- Deleting any required envelope field from a valid fixture must fail both
  languages (covered by mutation tests, not by extra files).
- A Java-produced result must equal `results/*.json` byte-for-byte at the
  JSON-value level and validate in Python without normalization.
- Tokens and authorization headers never appear in fixtures or logs.
