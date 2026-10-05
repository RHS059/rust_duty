# Complete-build performance and unchanged verification

## Scope

The Task 2 candidate changes Python/tooling and CI scheduling only. Gameplay,
authored animation, format tolerances, expected clip revisions, publisher
conditions and release permissions remain unchanged. A faster complete Windows
ZIP is the target; less than five minutes is not yet established.

The exact build candidate and GitHub Actions result must be recorded separately
from local tests. Queue time, active job time, workflow time and commit-to-final
ZIP time are different measurements.

## Measured baseline

Baseline gameplay commit `dad6071625ce9190c69e4703c53952a2244cf1f8`,
[complete build run 37169478902](https://github.com/RHS059/rust_duty/actions/runs/37169478902):

| Step | Windows seconds | Linux seconds |
| --- | ---: | ---: |
| Complete OS job | 1082 | 939 |
| Python test suite | 479 | 372 |
| Asset materialization | 63 | 50 |
| Companion verification | 39 | 32 |
| Complete game staging | 145 | 114 |
| Rust tests | 111 | 96 |
| Release compilation | 40 | 42 |

Warm asset jobs took 29–35 seconds. Compilation is not the largest bottleneck.
The source traversal repeatedly validates the same walk/ADS/directional byte
triples, including after staging. These counts are an optimization opportunity,
not by themselves a measured speedup.

For the independently reviewed PR28 warm run
[37171922385](https://github.com/RHS059/rust_duty/actions/runs/37171922385),
commit `3e3f7589` at 02:43:15 UTC to the final Windows ZIP at 03:03:31 UTC
was 20m16s; Linux was 13m38s. The workflow itself was 20m12s. The cold/main
[37162724484](https://github.com/RHS059/rust_duty/actions/runs/37162724484)
comparison was 29m01s commit-to-Windows-ZIP, including a much longer asset
preparation path. These are 2026-10-04 measurements, not candidate results.

## Optimization boundaries

### Exact-byte, process-local parse reuse

`vrview.ValidationMemo` keeps at most 24 small successful validation summaries.
Each lookup hashes fresh immutable bytes and includes their lengths, the parser
identity and relevant mode/context. It never keys approval on a path, mtime or
manifest assertion. It never keeps a failure, input blob or large decoded pose.
Returned metadata is defensively copied. No validation approval is saved to disk;
a new process/code version starts empty.

`validated_clip_summary` still calls the existing full VRA decoder on a miss.
The decoder still checks every frame, numeric transform, time ordering and
companion binding. Shared VRS/VRM structural inspection can reuse successful
results for the same bytes while each VRA's binding CRC, skeleton and actor
assignment checks still execute. This changes repeated work, not acceptance.

Every public packaging call still checks current required paths and symlinks,
raw and compressed SHA-256/size/equality, required transport mode, manifest and
current authoring source identity, recorded parity, preserved old clip bytes and
selected revision metadata. Destination files are freshly read and checked after
copying; only pure decoding of identical bytes may reuse a prior result. Changing
an animation, model or rig changes those byte keys. Source/provenance changes are
checked outside the memo even when binary bytes are unchanged.

The existing export-boundary source/tool-keyed CI asset caches remain in place.
Their cached/fresh outputs are revalidated. No new persistent certificate or
trust shortcut is introduced. In particular, successful FBX conversion alone is
not treated as approval of the final runtime payload.

### Independent checks overlap

`ci_quality_checks.py` runs the complete Python suite, sequential game
clippy/test/release-build commands, and sequential updater fmt/clippy/test
commands in three independent lanes. Game commands retain one target directory;
the updater has its own. All lanes must pass before staging/upload. Failures and
spawn errors fail the overall step; each lane gets a log and command timing.

Materialization and generated-pack verification run in one process, sharing
only safe pure-parser results. Formatter output is still checked against source.
The Cargo cache stores updated game and updater targets under exact-commit keys
with lockfile-scoped restore fallbacks. Cargo still performs all checks/builds.
Duplicate push/PR runs share a branch concurrency lane. The existing publishing
push has an event-isolated lane and retains its non-cancellation condition.

All existing native gameplay, walk, ADS, layered-rate and lighting checks remain,
including the Task 1 ADS-placement comparison and reload-return capture/verifier.
No asset-identity, public-input, parser, sampler, final-package or native gate is
removed to improve the time.

## Safety contracts versus selected revision expectations

Finite transforms, valid quaternion/scale, monotonic time, binary bounds and
companion compatibility are format/sampler checks. Hardcoded walk/ADS/directional
clip names, durations and frame ranges are selected project-pack revision
contracts, not universal runtime durations. This optimization preserves both.
A future deliberate animation revision should update its declared source/export
contract and matching regression evidence; it must not silently bypass these
checks or misdescribe a new duration as intrinsically unreadable.

## Candidate verification

- Existing Python suite: 189 tests passed in the first local pass, with one
  pre-existing opt-in Blender neutral smoke skipped. This is not CI timing.
- New tests exercise exact-content versus same-length changes, bounded eviction,
  parser identity, mutable input snapshots, defensive copies and failure retry.
- Warm-cache public packaging tests exercise file replacement, symlink replacement,
  changed manifest/source/parity and raw-only to required-transport mode.
- Orchestration tests prove lane overlap, within-lane ordering, failure propagation
  and spawn-error handling. They do not substitute for the real CI command run.
- Actionlint and Python bytecode compilation passed locally.
- Local optimization snapshot on gameplay base b577aaaa: 202 tests passed in
  196.931 seconds; the one existing
  opt-in Blender smoke remained skipped. The workflow contract now verifies the
  invoked parallel driver's exact updater commands and staging dependency rather
  than requiring those commands to be inline YAML text.
- Sixteen native/staging/build-identity steps compare unchanged with the Task 1
  workflow, including all capture commands and their verification/upload steps.
- Baseline versus optimized staging retained identical path/size/SHA-256/execute
  maps: 83 complete-game files and 70 managed-update files. Settings stayed in the
  complete distribution and outside the managed update. Real notices matched.
- Deterministically zipped complete distributions were byte-identical:
  `a99f4cbc3bc4b4a4960bde81e0f475f8c176b23760f2298dd5c07ebb1eb22e38`.
  Managed bundles were byte-identical:
  `3b0146ae7ba25f9bb98a391185f8a0af7b95853fa0e4c9e778ebf817d8c54646`.
- Local complete staging: 105.25s baseline, 58.77s optimized; managed staging:
  104.29s baseline, 56.16s optimized. These are directional local measurements
  under shared cloud load while tests/native work also ran, not an isolated
  performance claim and not the end-to-end CI target.
- The subsequent gameplay review follow-up 6db18e retains its source changes
  and strengthened return verifier; all five updated return-verifier tests passed
  separately after that handoff. Full exact-head CI is the combined-candidate gate.
- Exact-head full CI and final Windows/Linux artifact timings remain pending.

Local packaging comparison uses the same materialized runtime assets and same
0.1.8 Linux debug/no-audio executable in both versions. Actual updater notices
come from the exact dad6071 Linux artifact 11291071076. This comparison checks
packager equivalence; it is not a release executable, Windows gameplay pass or
new artistic approval.
