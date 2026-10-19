# Workflow successor v2

Immutable predecessor: workflow v1 PINS `c027871c70b741e5b0d13edcb724e7170c45df952d678b446bb092f209629270`. v1 is retained unchanged. This successor is source-only; no native/build/download/publication execution occurred.

## Confirmed B1: draft trigger and incomplete-input CI

The predecessor was dispatch-only and required a repository variable before its only job. A newly introduced dispatch-only workflow cannot provide the requested draft-branch route before default-branch presence. The predecessor also checked missing execution pins before running CPU tests.

v2 uses `pull_request` on `aella/combined-authored-transitions-20261016` (the stacked PR74 branch), with `main` supported for later review. It checks the exact event head SHA and same-repository head identity, read-only contents access and no stored credentials. It does not use `pull_request_target`, secrets, repository variables or manual dispatch. Source export and source tests each have a ten-minute bound. Opening/synchronizing/reopening the draft PR can run them with deliberately missing native input pins.

The source-only bootstrap reads exact Git blobs from the event commit and checks every declared source hash, including all frozen dependencies. Its calculated package identity is explicitly `observed_orchestration_pins_sha256`, never independently reviewed native acceptance. All source-only data stays separate from the eventual full proof-input materialization.

After source tests, `preinstall_admission.py` checks the committed `tools/onehand_windows/proof-admission.json`. Missing or wholly null admission reports `blocked-incomplete-admission`, sets `native_ready=false`, and leaves source-test CI useful. Partial, malformed or contradictory non-null admission fails the job. The current template is deliberately all null.

A complete record must separately pin the orchestration PINS and three immutable Git records: full proof inputs, controller layout and actual independent review. All records have exactly `ref`, `repository_path`, `sha256`, and `bytes`; refs must resolve to actual commit objects. The independent review has exactly:

- `schema`: `rust-duty-onehand-workflow-independent-acceptance/v2`
- `decision`: `accepted-for-guarded-native-proof`
- `orchestration_pins_sha256`: independently accepted package PINS identity
- `reviewed_dependencies_sha256`: exact accepted completion/dependency declaration
- `blocking_findings`: empty only after actual independent review
- `animation_proof`: false

No such completed review record is invented or shipped here. It is a source acceptance boundary, not a replacement for native proof.

Before any Blender/Rust installer, the gate requires every reviewed dependency hash, delta destination, Rust commit and exact toolchain choice; verifies the acceptance identities; materializes the complete exact proof input manifest; loads the real producer/consumer/original helpers; revalidates original base/delta/canonical inputs, all34 Linux reference witnesses and their aggregate using the existing bridge; revalidates actual process transport acceptance/smoke using the existing adapter validator; and verifies the selected Rust snapshot against its actual commit records and unchanged consumer Rust source pins. Missing source data fails. No unknown native expected hash is learned from observed bytes.

Only after those checks can five conditional native steps run. The existing full runner preflight repeats after official installation. Actual runtime/native evidence remains in the same runner rather than crossing a private artifact upload. Source-test, admission and actual native summaries are separately labeled; passing source tests never claims animation proof.

## Confirmed B3: object type is not a commit

The predecessor accepted any40-digit Git object identifier, and `git cat-file tree:path` is valid. Content hashes remained checked, but a tree object could masquerade as the declared source revision.

The materializer now requires `git cat-file -t <ref>` to equal `commit` before any blob read. Tree, blob and annotated tag objects are rejected. The source-test bootstrap and admission's event SHA enforce the same boundary. Tiny actual local Git object fixtures test commit round-trip success and tree/blob/tag rejection, plus missing/null/partial admission CLI behavior. These source-only fixtures are not Windows animation or compiler execution.

## Other boundaries

Numerical algorithms, the222 native stages,67 Rust chunks/4,240 samples, focus tests,12 blocks, original resource floors and restoration checks are unchanged. The source-only publication inventory excludes original delta, all private assets, held vault/prone payloads, completed Linux references and a live proof-inputs manifest. The placeholder admission file is explicitly safe to publish as null WIP; future complete admission requires a new independently reviewed immutable source revision.
