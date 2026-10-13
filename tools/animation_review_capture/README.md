# Fixed-source Eevee review capture (WIP)

This additive tooling checkpoint supports PRs [34](https://github.com/RHS059/rust_duty/pull/34),
[35](https://github.com/RHS059/rust_duty/pull/35), and
[41](https://github.com/RHS059/rust_duty/pull/41). It changes no game runtime,
authored animation, source assets, camera, published preview, or review score.
It is not a completed capture or artistic approval.

## What is pinned

`contracts.json` records eleven exact source/Action selections, source SHA-256,
saved camera, 1280x720 resolution, 60 fps, and native reference-frame mappings:

- Prone entry r4: 69 frames, R3 [2241, 2310)
- Low vault r3: 64 frames, R3 [7284, 7348), eight Eevee viewport samples
- One-hand mantle r3: 96 frames, R3 [7787, 7883), sixteen samples
- Forward/backward/left/right HIP walk baseline and visual-v1 candidate: paired
  takes from the same frozen source, 39/46/50/50 inclusive frames respectively.
  The final frame of each walk take is a closure witness, excluded from unique playback

The eleven maps contain 599 samples: 591 unique playback samples and eight walk
closure witnesses. `provenance.json` supplies immutable repository references and
hashes. No BLEND, geometry, texture, screenshot, video, or private asset is included.
Only use source files you are authorized to access; this tool does not download them.

PR20 jump r7 already has a separate native evidence corpus and is outside this
adapter's eleven-take selection. R1/R2 walking reference originals were recovered
and hash/decode verified separately on 2026-10-13, including 185 mapped reference
PNGs. Their availability does not establish model capture or visual agreement.

## Portable setup and tests

Use Python 3.10+ for the asset-free unit tests:

```sh
python3 -m unittest discover -s tools/animation_review_capture -p 'test_*.py' -v
```

The package is also discovered by the existing repository-wide Python test lane:

```sh
python3 -m unittest discover -s tools -p 'test_*.py' -v
```

Blender execution requires exactly Blender 4.3.2. Put the four pinned source files
under a private input root using the paths in `contracts.json`, for example
`<input-root>/sources/prone-entry-r4.blend`. Pass `--input-root` explicitly or set
`RUST_DUTY_CAPTURE_INPUT_ROOT`. The fallback is an untracked `inputs/` directory
beside this README. No machine-specific path is compiled into the tool.

The unchanged source-integrity helpers are included with their source pins and
hashes. Missing inputs or a wrong source hash fail validation; no private source
is silently replaced by a unit-test fixture.

```sh
blender --background --factory-startup --disable-autoexec --python-exit-code 1 \
  --python tools/animation_review_capture/capture_viewport.py \
  -- --input-root /path/to/private-inputs --validate-all \
  --output /path/to/new-validation.json
```

This command only opens data, selects Actions, checks endpoints and restores
bindings. It does not invoke a renderer or save a BLEND.

## Foreground probe and capture

The operator route remains WIP: bounded attempts reached priming and then exited
137 without a native PNG. Exit 137 is consistent with SIGKILL; its cause and any
memory limit were not established. A smaller live Eevee viewport hold succeeded
as capability evidence only. A later exact-size camera-border witness produced
three uniformly black Blender screenshot PNGs and was rejected. It did not
produce an accepted native animation corpus.
Do not infer capture success from the source-selection checks.

Run a bounded frame-one probe only in an already verified graphical environment:

```sh
blender --factory-startup --disable-autoexec --python-exit-code 1 \
  --python tools/animation_review_capture/capture_viewport.py \
  -- --input-root /path/to/private-inputs --take vault-low-r3 --probe-only \
  --output /path/to/new-vault-probe
```

Never use background mode for rendering. Probe evidence includes the cold primer
and repeated same-pose images. It requires two identical consecutive decoded-pixel
hashes, with at least three images and at most eight attempts. No later animation
frame replaces a cold or unstable frame one. `completed` stays false for a probe.

After a route is demonstrated, omit `--probe-only` for a full take. The process
waits at frame one for `primer_review.json`, based on the generated template.
A reviewer must inspect the actual current-process images, provide a meaningful
review note, and retain exact take/source/primer hashes before setting `accepted`
to true. This is a material-priming check, not an animation-quality score.

Only then does the adapter call `bpy.ops.render.opengl` in the genuine foreground
rendered VIEW_3D, with `BLENDER_EEVEE_NEXT`, exact saved camera and native resolution.
It hashes every output, verifies frame one matches the warm primer, restores
playback bindings, and checks source bytes, Action curves, drivers, packed images,
mesh/UV/material/rest-rig/binding data, and camera preservation. It never calls a
canonical-source BLEND save operator. Blender may still write its own temporary
quit/recovery BLEND when closing; that is separate from preserving source bytes. `completed: true` would mean capture complete only.

Every output path must be new. Failed and partial evidence is preserved; use a
different path for an intentional rerun. No file in `evidence/` should be read as
a substitute for that run's images or independent visual review.

## Diagnostic utilities and limits

`viewport_pixel_plan.py` computes display-only camera zoom/offset for an integer
1280x720 rectangle; it does not alter the camera transform or resize an image.
`extract_camera_crop.py` verifies a separately recorded live-viewport screenshot
proof, rejects black or uniform settled pixels, requires a matching independent
visual-review receipt, and losslessly extracts its integer camera rectangle. It neither renders
nor creates missing screenshot evidence. The crop is not `render.opengl` output
and is not a full native frame corpus. A later, separate OS lossless screenshot transport established a stable
nonblack native-size live-viewport witness. Full animation sequences remain
pending; mutable launchers and screenshots are outside this checkpoint.

`evidence/` records compact validation/failure receipts. Passed source/unit checks,
failed renderer attempts, pending native capture, and pending artistic/runtime
review are distinct outcomes. Rust/gameplay checks are not claimed by these tests.

The crop review file must be named `visual-review.json` beside the proof and
contain `accepted: true`, a nonblank `review_note`, exact `proof_sha256`,
`source_sha256`, `action`, `action_frame: 1`, and the ordered `screenshot_sha256`
list. An existing `visual-rejection.json` blocks extraction. This command is
restricted to the pinned low-vault take; it independently checks the settled
crops are byte-identical before writing any output.

```sh
python3 tools/animation_review_capture/extract_camera_crop.py \
  --proof /path/to/viewport-pixel-proof.json --output /path/to/new-crops
```

`evidence/frozen-input-SHA256SUMS` identifies the original reviewed inputs, not
the portable publication files. `SHA256SUMS` records this publication revision.

## Publication verification (2026-10-13)

- All 29 source-free regressions passed in isolated publication staging after the
  Windows path-alias assertion correction; initial revision had 28
- Fresh portable Blender 4.3.2 no-render validation passed all eleven takes,
  including all eight preservation checks per take; exit code 0
- Python syntax and unchanged helper hashes passed
- Full repository/Rust/native-gameplay checks did not run locally for this
  additive Python/tooling-only change; remote CI is recorded on the draft PR
- Foreground native image-corpus completion and artistic approval remain pending

See `evidence/publication-validation.json` and
`evidence/portable-no-render-receipt.json` for exact scope and tested code hashes.

### Later observation outside the sealed renderer snapshot

A separate lossless OS screenshot route subsequently produced three stable,
nonblack 1280x720 camera crops during a clean 180-second live Eevee hold. The
material fingerprint matched the original PR37 r2 proof. This updates route
feasibility only: that experimental transport and its image packet are not
included here, and a complete native animation sequence is still pending. The
older killed-operator and black-window-PNG receipts remain valid historical failures.

Revision r2 fixes the Windows test expectation for equivalent short and canonical
temporary-directory names. Production code is byte-identical to the eleven-take
validation. The initial Windows run had one failing assertion among 2019 tests
(11 skipped); `evidence/ci-revision-r2.json` preserves the failure and correction.
