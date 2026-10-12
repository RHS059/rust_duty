# Resident on/off ADS numerical diagnostic

This is a bounded attribution experiment, not a replacement for the authored
source-visibility gate. The original gate remains failed at frame 0000 on both
backends: foreground coverage 0.002716 versus the unchanged minimum 0.010000.

The independently decoded current `1ef12e3` and earlier `adc2706` ADS sequences
have identical gameplay/time/primary records and foreground-count sets. OpenGL
is exact outside the verified 64×22 invocation marker. DX12 differs at 495 pixels
across 273 of 553 frames, at most six pixels per frame; every changed channel
has absolute delta one and alpha is unchanged. These are observed small numeric
differences, not proof of their cause. GPU lighting/normal arithmetic followed by
vertex-color byte quantization is a hypothesis.

## Source and execution boundary

`tools/run_resident_ads_rounding.py` admits only the reviewed 131-input production
inventory from local `272d9cc` (remote `1ef12e3`), SHA-256
`2a6a534aec6e3a6053ed6584dac497e38f85fabcf47aecf64c209bc925460b17`.
It freshly builds both variants with actual Rust/Cargo 1.99.0 MSVC, locked
release `wgpu-runtime`, no default features, on the same Windows worker. The
only production difference is `src/frame_resident_policy.rs`: `ENABLED=false`
for the CPU reference and `ENABLED=true` for the GPU resident path. Staging,
loader deduplication, serialization, capture code and all other production
bytes are identical. Both original EXEs are retained, with compiler, source,
build-command, same-run identity and executable hashes.

Both controls use the same verified public companion set and the same settings
file with the existing `(0.20,-0.20,0.20)` offset. Each runs the unchanged full
`gameplay-ads` capture sequence at its default 60000/1001 rate, reference viewport
960×540, DX12/WARP/Fifo, timestamp recording off. This is the authored offscreen
viewmodel image route, not a physical1080p performance recording.

The invocation-derived marker is checked in every original PNG before its
region is excluded in an in-memory diagnostic copy. All 553 frame indices,
primary metadata (except the verified per-executable marker identity), gameplay
and time records must join exactly. Every original image is also passed through
the unchanged one-percent structural predicate, and its failures are retained.
The report contains exact per-frame RGBA deltas and foreground counts, without
a new image tolerance or an acceptance verdict. A successful diagnostic job
means the comparison completed; `visibility_gate_passed` remains the original
predicate's result.

This pair isolates resident offload in current source. An exact pair would not
settle every older `adc2706`-to-current difference, which also spans loader and
compiler changes. Any observed difference needs inspection before a cause or a
new acceptance rule is proposed. This run measures neither FPS nor speedup.

## Invocation and retained evidence

A cheap closed-source scheduling check gates every asset producer and capture
job; future unreviewed production source skips this historical diagnostic.
The dedicated `resident-ads-rounding.yml` workflow materializes only the same
five public companion producer outputs used by the current authored gate, then
runs:

```
python tools/run_resident_ads_rounding.py --root . --output evidence/resident-ads
```

The output directory must initially contain only the successful package
materialization receipt. Each build is bounded to 1,200 seconds and each capture
to 3,000 seconds, with owned-process-tree cleanup on timeout or interruption.
Raw source/build/process receipts, both executables, every original PNG/sidecar,
and the diagnostic report are retained. A smaller report artifact is separate
from the full raw packet. Final checks rehash assets, settings, compiler inputs,
source variants, earlier process outputs and complete directory inventories.
No success summary is written if final verification fails.
