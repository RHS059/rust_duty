# Same-candidate Windows game continuation, preparation v1

Source-only follow-up to the independently prepared source → FBX → actual Rust
full4240 pipeline. This preparation has not run Blender, a game, or Windows.
Native admission is deliberately disabled. Public high runtime pins remain None.
The parent owns publication and any subsequent exact acceptance.

## Deliverable and publication mapping

- `package/*` → `tools/onehand_windows/game-continuation-v1/*`
- `admission.template.json` → `tools/onehand_windows/game-admission-v1/admission.json`
- `overlay/src/authored_viewmodel.rs` → same repository path
- `overlay/src/high_mantle_capture.rs` → same repository path
- `onehand-windows-proof.yml` → `.github/workflows/onehand-windows-proof.yml`

The independent original orchestration-v5, consumer-v5, native-producer-v4,
context-v2 and process-adapter-v2 packages are not rewritten. Every original
full-proof workflow step is preserved verbatim. Existing game CI workflows are
not replaced. The PR filter additionally admits the actual PR76 base branch
`aella/combined-diagnostic-source-wip-20261016`.

Inspected current game source is PR76 commit
`6afe6e2bc9959242272cb44d0e3919c0aee5179a`; source-only prerequisite PR77 commit
`2a50a5f5ff16678bddac5996409dd902ff68af26` preserves that game composition.
The six reference workflows match their exact current Git blobs. The future
accepted source commit must include these two diagnostic overlays. The stale
older game revision in the predecessor handoff is not selected.

## Runnable path

1. Existing checkout already holds the exact event head and full repository.
   A SHA-pinned standalone bootstrap exports the flat continuation package with
   `git cat-file`, checks all bytes, and runs its isolated source tests.
2. A disabled admission emits an honest source-only report. An enabled admission
   must name exact package/source-spec/review hashes and an immutable game-source
   commit. Every selected game/source-input blob at the actual event head must
   still equal that admitted source commit. A later review/admission commit can
   therefore avoid a circular self-commit hash without accepting stale game code.
3. The only additional checkout is the established Jump authoring revision
   `e9317f90ea171976306e2f17c111325d948ea357`, using the existing official
   actions/checkout route with credentials not persisted. No other-run assets or
   generated-artifact downloads are used.
4. The original full4240/67-chunk Windows source → FBX → Rust proof completes.
   Before teardown, the continuation independently reconsumes that full proof,
   host, build closure, receipts, assets and same run/attempt/runner identity.
5. Exact current game code and established public authored inputs are exported
   to a new runner-local source directory. Current selection is 951 blobs,
   255,462,612 bytes before the separately pinned Jump input. The declared cap is
   1 GiB total and 128 MiB per blob, with all byte counts and Git/SHA256 identities
   independently reviewed in the source spec.
6. The official compiler is reused with a fresh Cargo home/vendor/targets. Both
   the actual current base sampler and final game build undergo the unchanged
   strict Cargo metadata, every-artifact dep-info, generated OUT_DIR producer,
   and complete source/dependency membership checks. Exact compiler/linker/SDK
   files and Cargo config are recorded and rechecked.
7. Existing reload, walk, ADS, directional and approved-r8 Jump generators and
   their unchanged source-bound numerical checks run sequentially in this job.
   Each output is checked before staging. The canonical locomotion companions,
   normal_ready, approved walks, ADS and other current features remain present.
   These producers can fail honestly on Windows; no Linux-specific relaxation
   or prior-green asset substitution is included.
8. Only after the actual full proof passes, a runner-local high binding receipt,
   manifest append and exact six-pin Rust patch are generated. Public source
   stays inactive. The unpatched source inventory, exact patch bytes, resulting
   complete source closure, runtime manifest, candidate assets and executable
   hashes are retained. The enabled executable is explicitly not byte-identical
   to the public inactive source.
9. This exact executable/manifest runs native-window DX12 WARP at 30 and 60 Hz.
   The unchanged strict deterministic verifier retains all 324 native ticks,
   95/60-second endpoint, real PNG witnesses, zero-weight frame96 endpoint and
   intermediate live walk/ADS outgoing samples. New observations bind the actual
   selected renderer/clip, admitted VRA/receipt and rendered source pose time.
   Actual frame metadata plus log identities must show Dx12, Microsoft Basic
   Render Driver and Fxc. Unknown warnings/failures are rejected. Only the exact
   existing known base WIP slot warning is admitted; appended optional-binding
   failures are not.
10. Full proof is reconsumed again. Only after both captures pass is the normal
    playable game distribution staged, including only the three actual candidate
    runtime companions and its hash-only runtime receipt. Original BLEND/FBX/NPZ
    intermediates are never staged. The final manifest/executable and all package
    files are hashed; the game artifact upload is conditional on that acceptance.

## Acceptance files to prepare later

`prepare_game_spec.py` reads an existing exact Git repository and the immutable
Jump checkout. It produces a source-input inventory; it does not approve it.
Its required flags are `--git`, `--repository`, `--revision`, `--output`, with
`--jump-repository` when Jump is a separate checkout.

An enabled admission needs relative ordinary `game_source_spec` and
`independent_review` references `{path, sha256}`. Both files must be committed
under the admission directory and exported from the exact event head. The
review schema is `rust-duty-onehand-game-continuation-review/v1`, with a named
reviewer, `accepted:true`, exact package/orchestration/source/spec hashes,
matching reserve_bytes, and every review flag checked by `admit()`. No
acceptance, source ref or candidate output has been fabricated here.

## Resource and forensic boundaries

The admission template reserves 8 GiB in addition to the 1 GiB disk floor.
Each owned command retains the established Windows Job Object descendant
cleanup, 30-minute maximum, log caps and sampled direct-child 3 GiB guard;
captures tighten the deadline to 10 minutes. These are not claims of aggregate
Blender-descendant memory/commit control. Base generation/build cost is additional
to the existing proof, within the unchanged 360-minute job timeout.

Failure publication is bounded/hash-only. Native logs and raw candidate files
remain runner-local. Teardown destroys raw forensic evidence; summary hashes
cannot resurrect a candidate. Any next run must regenerate and reprove before
building/capturing. Deterministic capture does not claim OS hotkeys, real-time
performance, combined all-route gameplay, or artistic approval. The separate
Linux combined 30/60 result and prior green asset CI are not this candidate.

## Local checks and remaining validation

- 46 bounded runtime-package tests, including identity swaps and strict negatives
- 8 composition/export tests, including actual local-Git dormant export, hash-only
  errors, untouched original proof steps and same-job capture-before-delivery
- Exact two overlays pass rustfmt; `cargo fmt --all -- --check` passes in an
  isolated current-source view; no struct field or constructor changed
- The parent’s bounded no-audio dual-feature Cargo check stopped at its fixed
  256 MiB changed-output cap after 54.2 s while rebuilding dependencies, before
  project compilation. No Rust error was reported, but compile PASS is not
  established. Source inventory was unchanged; no budget increase or retry is
  included. The separate coordinator receipt records this limitation
- Actual Windows source proof, current base generation, game build and DX12
  capture remain required before any candidate acceptance or delivery claim

Run source tests through the immutable entry point:
`python -I -B package/execute_continuation.py --package-pins-sha256 <PINS SHA> --source-tests`.
The outer preparation checks use `python -m unittest discover -s . -p test_preparation.py`.
