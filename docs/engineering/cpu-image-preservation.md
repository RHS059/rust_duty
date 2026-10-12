# CPU image preservation and the ADS-offset validation gap

## Observed failure, unchanged verdict

Windows run [38162233555, ADS-offset job 114552431107](https://github.com/RHS059/rust_duty/actions/runs/38162233555/job/114552431107)
captured all 553 frames on each backend. The actual source receipt identifies
`d7534342e7c8d8898e12740309705097a438974b`; its complete tree matches PR #49
head `311538e38f460645b49d86548a377246680f71a3`.

Artifact `11713360923` is 92,542,817 bytes, with ZIP SHA-256
`7747bc4e00e9ea37ec4b3569f463da786a08b07a1a166b713dfbe9bf96aab088`.
Its original summary remains failed. Both first frames have 1,408 foreground
pixels, all belonging to the 64 by 22 frame-witness marker. That is
`1408 / (960 * 540) = 0.002716049...`, below the unchanged 1% coverage gate.
There is no viewmodel foreground outside the marker in those frames.

Read-only decoding of all 1,106 original PNGs, independently repeated, found
160 scene-empty frames and 210 below-threshold frames per backend. Both index
sets match the historical finite ADS descriptor exactly. The first frame is
the time-zero ready/hip pose, with ADS zero. The scenario applies the saved
viewmodel offset `(0.20, -0.20, 0.20)` and fades it out with visual ADS. This
offscreen capture contains the viewmodel, not world geometry or HUD text.
These facts are consistent with the known offset visibility pattern; they are
not a new triangle-clipping or source-visibility proof.

The current-source supplement is restricted to the ordinary main build. Its
finite class also permits only exact reviewed source variants, which do not
include this integration's new diagnostics modules and CPU changes. Therefore
neither the historical frame-set match nor a new source allowlist can turn this
PR's failed authored aggregate into a pass. No threshold, source-class guard,
original capture, or failed verdict is changed here.

## Separate, bounded CPU experiment

`tools/run_cpu_image_preservation.py` compares a reviewed four-file CPU change
without modifying that authored acceptance path. Its candidate production
inventory is all 118 compile inputs from the integrated tree reviewed at
`698edf3657cfb412eef942b864ebfaff30bae36f`, bound by manifest SHA-256
`d74a901c91ffd6746826e7e9c7f0ff447157774d3ea8d661d4912caf84e4a33c`.
The baseline is the same integrated code with only these files restored from
`70ff2933ebe69b7180e207c7defebeaeb6e240e1`:

- `src/draw/mod.rs`
- `src/render/lines.rs`
- `src/render/text.rs`
- `src/render/plan.rs`

This is an explicitly identified counterfactual CPU overlay, not the complete
historical game. Both variants use identical committed image fixtures and
freshly built executables. No downloaded baseline executable or game asset is
used. The exact source inventories, compiler identity, selected build settings,
commands, executable hashes, process exit codes and timeout cleanup are retained.
Source and executable mutations fail the experiment.

Each variant runs the existing 21-image production renderer contract, retaining
its original fixed expectations and negative cases. It also runs the existing
mixed line/text control: 20 semantic lines, 170 glyphs and 305 prepared draws,
including target, depth, blend and camera boundaries. All 21 image pairs and
the four mixed before/after controls must have exactly equal decoded RGBA
bytes. Actual Windows DX12/WARP/FXC identity and device evidence must agree.

The mixed fixture's line-count unit test now counts semantic lines across
nonempty commands. It admits the baseline's 20 one-line commands and the
candidate's one 20-line command while preserving the prepared-draw and glyph
totals. Candidate-specific coalescing assertions remain in the DrawList tests.
No fixture rendering operation or historical comparison source pin changed.

## Exact preparation and native invocation

Use a clean checkout with committed LF bytes (`core.autocrlf=false` before
checkout), the original `70ff2933...` Git object available, Python with the
repository's image-reader dependencies, and Rust 1.99.0 for Windows MSVC.
The runner rejects inherited compiler/asset overrides, an embedded weapon file,
changed or untracked source inputs, a different production manifest, and reused
evidence directories. In CI, the actual `GITHUB_SHA` must equal the checkout.
Inherited Cargo build/target/profile overrides and Cargo configuration files
in source ancestors or Cargo home are refused too. Cargo supports compiler
aliases and hierarchical configuration; checking only `RUSTC` and standalone
`rustc -Vv` would not bind the compiler Cargo actually invokes. See the
[official configuration reference](https://doc.rust-lang.org/cargo/reference/config.html#buildrustc).
Private configuration contents are neither read nor copied into receipts.
Compiler and Cargo versions are also checked from each materialized source's
working directory before its build and again before acceptance, detecting
directory-selected rustup toolchains. Stored source/verifier receipts are
rehash-checked alongside their materialized files.

Source-only preparation works on Linux and does not build or execute programs:

```text
python tools/run_cpu_image_preservation.py prepare --root . --output evidence/cpu-image-prepare
```

The separate native command builds both variants itself, then executes only
those freshly built, hash-verified binaries:

```text
python tools/run_cpu_image_preservation.py run --root . --output evidence/cpu-image-native --build-timeout 1200 --process-timeout 180
```

The push-only [Windows workflow](../../.github/workflows/cpu-image-preservation.yml)
on the diagnostics draft branch executes that same native command. It retrieves
only the pinned baseline Git source, selects the direct Rust 1.99.0 binaries,
and uses a fresh Cargo home. Source, process, image and failure receipts are
retained on either outcome; compiled binaries and build trees are excluded.
A successful run also retains `control-outputs.zip`, bound by SHA-256 in the
summary. This inner archive explicitly preserves empty negative-fixture
directories, including `capture-is-directory.png`, which file-only artifact
uploads otherwise omit. Extract that archive into a separate replay directory
when rerunning the original strict renderer validator. The separately retained
PNG/JSON files remain useful for direct inspection; no missing directory is
inferred or fabricated during validation.

There are two bounded builds and four bounded native fixture processes. Retain
the source/command/image receipts and logs; no binary distribution is needed.
The incidental timing fields in the reused mixed fixture remain raw diagnostic
data. This comparison does not score them, measure the recording allocation
change, infer gameplay FPS, or validate RTX 3080 Ti / 1080p60.

## Remaining evidence

1. Execute the fresh native comparison above. Linux guard tests and compilation
   cannot establish its Windows pixel verdict.
2. Execute `run_gpu_session_contract.py` separately for enabled/default-off
   windowed capture, stop/restart, and exact primary/sidecar joins. The image
   comparison is headless and cannot replace that lifecycle proof.
3. To claim preservation of the authored ADS scenario, perform a fresh same-host
   baseline/candidate replay using the same exact assets, settings, compiler,
   adapter and deterministic timeline. Bind both executable/source variants and
   every frame/gameplay/time join. Compare decoded pixels with zero tolerance,
   excluding only each independently verified frame-witness rectangle. The
   existing OpenGL-versus-DX12 pair is not a pre/post CPU-change comparison.
4. Even a passing relative image comparison leaves absolute authored visibility
   and the original nine-shard aggregate unresolved. Any current-source
   visibility supplement needs independently reviewed evidence under its own
   contract; merely adding source hashes or accepting empty images is insufficient.

Status at preparation: Linux source/guard validation and the mixed example's
37 baseline / 42 candidate unit tests are available. Native image comparison,
enabled windowed GPU-session execution, authored baseline replay and target
hardware performance remain unrun.

## Destination-buffer reuse comparison

The separately named `--experiment geometry-reuse` mode uses the current
122-file closed compile inventory (`f796c8d9e5de81598a42fe77854b047ec961f0e17da709502889b65c143b2c5b`).
Both variants retain the same new v2 phase/allocation counters. The only source
change is `src/frame_upload_policy.rs`, replacing `REUSE_ENABLED: bool = true`
with `false` in the explicitly labeled baseline. The latter selects the original
immutable per-frame uploader. It is a one-line policy counterfactual, not the
historical four-file CPU baseline or an unmodified retail commit.

The existing Windows workflow runs:

```text
python tools/run_cpu_image_preservation.py run --root . --output evidence/cpu-image-native --build-timeout 1200 --process-timeout 180 --experiment geometry-reuse
```

The two shared image fixtures, all 21 fixed image expectations, four mixed-image
comparisons, exact pixel equality and directory-bearing retained archive remain
unchanged. The old CPU overlay remains available as `--experiment cpu-overlay`.
Queued earlier-frame-copy versus later-write lifetime coverage is supplied by
the separate `render::upload_reuse_tests` suite on DX12/WARP; serial image
readbacks alone do not establish in-flight ordering safety. Neither result
changes the authored ADS coverage failure or establishes an RTX speedup.
