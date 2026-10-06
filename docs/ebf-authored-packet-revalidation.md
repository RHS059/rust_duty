# Completed ebf authored packet revalidation

This separate Python-only workflow reuses source packet and nine captures from
[RHS059/rust_duty run 37490373763, attempt 1](https://github.com/RHS059/rust_duty/actions/runs/37490373763/attempts/1),
source `ebf4bcb7f489766e3c7ec188c35db9bb4146c62b`. It does not build, launch,
render, replay, cancel or rerun any native job. The original attempt remains
failed. The existing fixed-8f recovery and normal full-build workflow are unchanged.

The original source-proof step completed both source outputs and emitted its
independent receipt anchor before rejecting the old class with
`unreviewed production file added`. The original aggregate then failed because
ADS-offset finite-image checks remained deferred. The source artifact is
`11435824885`; its original producer summary, native shard summaries and full
aggregate job log are preserved alongside the supplemental result.

The new adapter pins repository ID `1398577887`, main/build workflow identity,
terminal attempt and conclusion, both original job IDs and step metadata,
23 unique artifact IDs, archive hashes, sizes and timestamps. It requires
complete bounded metadata and unexpired artifacts, verifies every ZIP digest,
and rejects links, path aliases and surplus authored shards before staging.
It never requests the four previously denied artifact IDs.

Independent trust anchors come only from original job logs:

- Authored-inputs job `112401828417`: the exact seven-line Windows rustc 1.99.0
  stdout/cache fingerprint, SHA256
  `5477f9bad65b15c4c5b31fc050fc72feba651ea1b330bc75cf356a4d6b0fbc80`, and precompiled
  receipt `3a6470790ae87aa4c3918e940b7b367038536594c7093f7b861d02d1facda16e`
- Authored-aggregate job `112433359074`: source receipt
  `5b205cf22d6d10e75a5dd0c7da7b28672c170178d53609a63bc4a455315ac0e1`

Exact raw log hashes are pinned separately from packet contents. The adapter
checks original source-execution and capture contexts, the embedded precompiled
receipt, manifest, compiler, build and executable mappings, and the complete
source inventory. Original Windows receipts retain their recorded paths and ebf
identity; the verifier uses its actual caller SHA/run/attempt. No environment
identity is rewritten. Current production must equal ebf after LF normalization
and the existing exact-hash `asset_path.rs` cfg(test) repair only.

Native inputs are materialized in a fresh root against the original manifest;
current Python verifier tools are inventoried separately. Acceptance requires
the existing ADS leaf using `finite_ads_gpu_cpu_class.json`, independently pinned
to `91bd0030157ff8e1b4e70127b028e57543d8fc91fb3b6cc1202c4707491fb798`, followed by the
unchanged complete nine-shard aggregate. Missing evidence, source drift, any
conditional profile or any failed check fails closed. No new arithmetic proof,
source masking or thresholds are introduced. Landmark, human visual and real-GPU
playtest gates remain open even if supplemental automated verification passes.

The workflow runs only for changes to its four implementation/pin/test files on
main, or explicit dispatch. CI downloads and materializes the original data on
its own runner. The result is uploaded as
`ebf-authored-packet-revalidation-attempt-N`; all original artifacts remain in
the protected run. Authored artifacts expire on 2026-10-13, so running after
expiry deliberately fails instead of selecting replacement evidence.
