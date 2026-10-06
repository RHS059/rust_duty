# Conditional source visibility diagnostics

`source_visibility_certificate` evaluates the existing 553-frame ADS-offset
replay from original companion meshes and a read-only source-pose snapshot.
It does not read capture pixels or use emitted draw batches as its geometry
oracle. `compare_source_visibility.py` checks an image against those supplied
obligations; neither component grants migration acceptance.

```sh
cargo run --locked --release --no-default-features \
  --example source_visibility_certificate -- \
  MANIFEST SETTINGS opengl NEW_OUTPUT.jsonl
```

Use `dx12` for the separate DX12 matrix profile. The settings must contain the
existing `(0.2, -0.2, 0.2)` offset fixture. Output creation is exclusive. Keep the
source, compiler, executable, manifest, settings and every consumed companion
hash with the output. A regenerated pack passing its own source oracle is not
evidence that its bytes equal a native capture's pack.

The source snapshot preserves the selected animation, pose, root and authored
actor opacity before batching. Independent decoders enumerate the original
skin and rigid triangle indices, including ownership and hidden-actor checks.
The snapshot rejects unsupported cant rather than approximating it. The replay
also emits the existing ADS gameplay fields using the capture writer's numeric
formatting, so a caller can compare complete per-frame state.

## Explicit profiles

GL bounds the `Projection * Model * position` expression. DX12 separately bounds
the CPU `(remap * projection) * model` upload followed by the shader dot product.
Both assume normal finite float operations with the declared error envelope and
equivalent-or-tighter fused operations. Their operation counts and outward
interval arithmetic are in the example; the GL capability receipt alone does
not establish these arithmetic assumptions.

Raster obligations assume a single center sample, no face culling, no alpha
discard, and at least eight subpixel bits with the declared displacement bound.
The model assumes x/y clipping preserves covered interior samples. Unsupported
eye/near/far clipping prevents claiming complete possible support.

Fragment obligations use conservative source vertex/texture color envelopes,
opaque fragments and a stated error bound of three byte levels per channel.
Potentially unsafe occluders remove required samples. That bound is an explicit
engineering assumption, not a result of querying the GL precision capability.
The frame-witness rectangle never supplies scene visibility.

These diagnostics are useful for distinguishing intentionally offscreen geometry
from missing visible content. Before using them in an acceptance caller, bind
the exact native inputs, source/executable, invocation, backend and every frame's
state; review the profile against the pinned implementation. Preserve strict PNG
decoding and all existing finite, world, identity, witness, telemetry and pair
checks. An ambiguous fallback must fail. A normal frame already satisfying its
existing coverage check does not acquire a new clipping obligation.

The negative controls reject blank or witness-only substitutes, missing required
pixels and unrelated injected patches. They do not establish resistance to a
renderer deliberately synthesizing the exact expected mask. Geometry,
calibration and the ordinary coverage threshold remain unchanged.

## Immutable native capture revalidation

`revalidate-ads-source.yml` prepares a separate Windows source oracle for the
explicitly pinned capture revision and attempt. It checks out original production
source, permits only the reviewed read-only pose bridge and diagnostic example,
and recovers the original compiler fingerprint from that attempt's successful
authored-input job. The installed compiler, release settings, all 18 runtime
companions, base and offset settings, animation manifest and original invocation
must match their retained identities before the oracle runs.

`ads_source_visibility_binding.py` binds the resulting packet to the immutable
native captures, including every frame's complete gameplay and timing records.
An independently retained receipt digest anchors that packet. The original
capture revision and the later verifier revision remain distinct in each report.

`revalidate_ads_offset.py` runs the existing ADS, placement and exact same-Windows
parity checks on fresh verified copies. Only a typed generic coverage/structure
failure in the bound ADS-offset scenario may use the conditional source model.
Malformed PNGs, incorrect extents, missing witnesses, changed state, unsupported
fallback geometry and any other original check failure still fail. Frames that
already pass ordinary image validation do not use the fallback.

Original failed summaries and captured bytes are retained unchanged. The new
report explicitly keeps `acceptance_complete: false`: an ADS-pair result alone
does not establish the original nine-scenario aggregate or a current complete
Windows package. Publishing this caller does not assert that authoritative
Windows source generation or native revalidation has passed.
