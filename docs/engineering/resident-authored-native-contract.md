# Actual authored loader resident-GPU contract

This is a correctness gate for the resident vertex-stage skinning and lighting
path. It does not estimate FPS or replace the existing authored gameplay
visibility rules. The historical loader-dedup runner and its source classes are
unchanged.

`resident_authored_contract` loads the same authorized reload, walk, ADS,
directional and jump companions that the normal package materializer verifies.
It records two 22-case cohorts in one freshly built executable:

- The CPU cohort calls the original CPU-only facade entry point. Its oracle is
  the real loaders' output vertices, not a second resident-reference execution.
- The native cohort calls `begin_frame_with_renderer` with the actual native
  renderer. Every original mesh command must become a resident command; both
  skin and rigid paths are required where the case contains them. Submission
  counters must independently confirm the recorded resident draws.

Both cohorts retain fixed ready/walk/ADS/reload times, an earlier-time revisit
on each already-loaded instance, three production manifest/controller samples,
and three rigid-opacity samples with a nonuniform actor transform. The common
overview camera is derived only from the original CPU cohort's world bounds.

For each ordered command the fixture compares world-space index-expanded
position, UV and quantized RGBA, plus texture bytes/sampling and blend state.
The renderer does not consume the old CPU vertex-normal attribute, so it is
zeroed in this particular canonical stream. The resident CPU reference is used
only on the candidate side. Palette/root/light/material snapshot mistakes must
therefore disagree with the original-loader oracle rather than compare with
themselves.

The fixture retains all 44 raw corner streams and all 44 native PNGs. The first
gate requires exact RGBA equality and nonempty, varied images. Its final report
is saved before reporting a pixel mismatch. No tolerance is silently introduced;
any shader floating-point or raster discrepancy needs inspection of those exact
retained inputs and images before proposing a separate acceptance rule.

The source-bound Python runner reuses the existing input, compiler, generated
asset and strict report guards. It freshly builds the example, embeds the exact
input-receipt SHA, checks the executable before/after execution, and repeats
source/assets/compiler/receipt checks even on a failed native process. Build or
process timeout/interruption retires the owned process tree and retains cleanup
errors. This one-process correctness test is not an A/B timing experiment.

## Execution

After the existing public companion producer chain, use Rust 1.99.0 and pinned
Pillow 11.3.0 / PyYAML 6.0.3. The working tree must match its real Git commit,
`GITHUB_SHA` must identify it, and private weapon inputs must be absent. Start
with a fresh output directory containing only `materialize.json` from:

```
python tools/package_game.py materialize --root . --include-walk --include-ads \
  --include-directional --include-jump --require-generated
python tools/run_resident_authored_contract.py --root . \
  --output evidence/resident-authored --build-timeout 1200 --process-timeout 900
```

Redirect the first command's JSON to that directory's `materialize.json` and
check its exit status before running the second command. The bounded Windows
workflow performs this sequence. Its compact artifact retains original reports,
images, source receipts and process logs; both raw-corner cohorts also have
separate artifacts. Their actual compressed sizes are established only after
execution.

Windows requires actual DX12/WARP and verifies its seven-field adapter receipt.
The Linux route requires the actual NVIDIA A100-SXM4-40GB Vulkan identity,
including vendor 4318, device 8368 and `DiscreteGpu`; software fallback fails.
An installed Vulkan loader alone is insufficient. Linux graphics configuration
and process-local ICD setup remain the authorized hardware runner's concern.

The separate 27-pair resident native test covers queued submissions, different
poses of the same handle, cold/warm retention, transient fallback, clearing,
device recreation, eight influences and textured depth/blend cases. This
authored gate uses synchronous image readback and does not independently prove
in-flight overlap. The unchanged 21-image renderer controls remain in that
separate workflow.

Status at introduction: local source/reader/fixture checks pass; this new
companion-backed native gate has not yet executed. No target-hardware speedup
is inferred from its design.
