# Bounded source geometry supplement

This is a diagnostic supplement, not an acceptance switch. It preserves original
source certificates, failed native verdicts, capture bytes, geometry, camera
calibration and all image thresholds. The existing certificate's false profile
flags remain false. The new probe has a different schema so it cannot be mistaken
for a complete native source certificate.

## Run the source-only probe

`source_visibility_geometry_probe` accepts the same source manifest, offset
settings and backend as the original certificate, followed by a fresh output path
and a JSON array of selected fallback frame numbers. It advances the original
553-frame simulation and traces only those requested rows. No renderer, graphics
context or candidate PNG is used.

```sh
cargo run --locked --release --no-default-features \
  --example source_visibility_geometry_probe -- \
  MANIFEST OFFSET_SETTINGS opengl NEW_TRACE.jsonl FALLBACK_FRAMES.json
python tools/audit_source_visibility_geometry.py \
  --trace NEW_TRACE.jsonl --native ORIGINAL_SOURCE_FRAMES.jsonl \
  --output NEW_CLIPPED_TRACE.jsonl --summary NEW_GEOMETRY_SUMMARY.json
```

The second command models the pinned **OpenGL llvmpipe** clipping path only. It
rejects a DX12 trace. It requires NumPy. The source-only arithmetic probe also
supports DX12; that does not establish DX12 clipping behavior.

Bind the probe executable, compiler, consumed source and exact companion/settings
bytes using an independent receipt. Source-native mask/state equality is useful
cross-checking; it does not prove equality of every intermediate vertex bit.
The caller must independently bind native comparator observations. This helper
never treats an unverified JSONL as proof of actual native coverage.

## Arithmetic domain

Every finite, nonzero binary32 input is an integer multiple of a power of two.
The helper extracts its exact least-significant nonzero-bit exponent. For
multiplication the lattice exponents add; for sums their minimum suffices.
Cancellation cannot produce a nonzero value below that lattice quantum.
Rounding to binary32 preserves that lattice or makes it coarser as long as the
result stays normal. Products and every partial-sum ordering are bounded by
outward sums of absolute magnitudes with the declared per-operation error.

Each mesh's positions are conservatively combined coordinate by coordinate. The
helper checks both GL matrix associations and the fully distributed expression,
and the DX12 remap/projection/model upload followed by the four-term vertex dot.
Every abstract intermediate must have lattice exponent at least -126 and a
magnitude safely below binary32 overflow. Failure remains explicit. This supplies
the normal-or-exact-zero/no-overflow premise of the existing gamma17/gamma24
counts for the audited input bits; it does not derive shader operation semantics
or establish native input identity.

## Generated clipping vertices and snapping

The implementation model is Mesa 26.2.4:

- `draw_context.c` defines the four X/Y planes in order.
- `draw_pipe_clip.c` selects planes from the original clip mask, processes the
  lowest selected plane first, evaluates float distances and `OUT+t*(IN-OUT)`,
  recomputes reciprocal W and viewport coordinates, and emits a fan anchored at
  the first polygon vertex. Provoking-vertex mode cyclically changes each fan
  triangle's vertex order.
- `lp_state_derived.c` enables the guardband path only without a depth attachment.
  The original capture's verified depth target selects ordinary X/Y clipping.
- `lp_rast.h` and `lp_setup_tri.c` define eight-bit coordinate snapping. The existing
  full 1/256-pixel envelope covers snapping plus the offset subtraction at the
  bounded 960-by-540 viewport range.

Generated vertices receive their own interval projection and snapping allowance;
original projected vertices alone do not supply that bound. Arithmetic uses
outward binary64 intervals with binary32 error and an absolute underflow allowance.
Ambiguous clip masks and inside/outside predicates branch both ways. Possible
support is their union and required support their intersection. Empty or fewer
than three-vertex outcomes survive later planes; they cannot be dropped from the
intersection. The finite branch cap and unsupported eye/near/far/small-W domains
fail closed. A row with any unresolved triangle exposes no usable required mask.

For a crossing, the opposite-sign distance denominator is a sum of magnitudes.
The audited W lower bound is 2^-20, retained after each clipping plane. A nonzero
binary32 side distance near cancellation therefore has quantum at least 2^-44,
well above underflow. This justifies the division-ratio envelope even when the
continuous interval contains zero; the actual native sign-changing branch has a
nonzero denominator. Both endpoint interpolation formulas are enclosed.

Colors are carried through generated-vertex interpolation with a conservative
normalization/optional low-precision-store allowance. These fields support a
separate fragment proof; geometry success alone cannot establish contrast.

Each output row narrows required support to the original required mask and unions
generated possible support with original possible support. This preserves a
one-way connection to a separately verified original comparator without replacing
original evidence. It does not relax the existing three-byte fragment envelope,
eight-byte contrast tolerance, ordinary foreground threshold or witness rules.

## Original bounded experiment

The diagnostic experiment used capture 8f571464/run37415102452/attempt1 and the
unchanged source receipt produced by 371bca3d/run37427554951. All 18 companions,
manifest, base/offset settings and three source files matched that receipt's
SHA256 identities. The source-only replay ran on a separate Linux host; it is
explicitly not a new native rendering or a native intermediate-bit observation.

- All 210 fallback rows per backend matched the original required/possible masks,
  complete gameplay/timing records and unsupported-clipping counts exactly.
- Arithmetic passed every audited mesh: minimum dyadic exponent -95 for GL and
  -96 for DX12; maximum rounded magnitude below 2.276; no unsupported domain nodes.
- All 160 empty fallback rows per backend were strictly separated below the
  homogeneous bottom plane or belonged to explicitly hidden source actors.
- The 50 visible GL fallback rows completed the bounded clipping model. Required
  support narrowed from 49,798 to 49,716 samples, with at least four samples in
  every frame. Six possible pixels were added in total, one each in frames
  315, 320, 322, 414, 415 and 518.
- The 19 ordinary-gate eye/near/far rows are outside fallback scope. This work
  does not make them eligible for fallback.

The resulting clipped trace SHA256 was
`458655709d010fd004eccc04234094ec09d66428e286e47c892ab5578d9a3204`.
Independent review found and fixed an empty-branch-retention bug; a negative
control covers it. Reprocessing the bounded 50-row input produced the same bytes.
Original required masks, failed rows and conditional flags were never overwritten.

## Remaining premises

Native intermediate-input identity, actual Mesa binary/build binding, fragment
interpolation/contrast and native comparator binding are separate obligations.
DX12 generated clipping and post-clip interpolation are still unproved here.
The Direct3D functional specification describes clipping and precision but does
not identify WARP's concrete clipping algorithm; Mesa's implementation must not
be applied to WARP as implementation evidence.

Primary specifications: [OpenGL 4.6, sections 13.7–13.8](https://registry.khronos.org/OpenGL/specs/gl/glspec46.core.pdf),
[GLSL 4.60, range and precision](https://registry.khronos.org/OpenGL/specs/gl/GLSLangSpec.4.60.html),
and [Direct3D functional specification, sections 3.1, 3.4 and 15.4](https://microsoft.github.io/DirectX-Specs/d3d/archive/D3D11_3_FunctionalSpec.htm).
