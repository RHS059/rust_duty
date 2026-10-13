# Bounded resident skin/root diagnostic

This revision changes the optional diagnostic helper and its fixture/reader. It
keeps `resident.wgsl`, `mesh.wgsl`, the production transform expressions, and the
original 22-case exact-image gate unchanged. It is not a transform correction.

## Evidence motivating the observation

The A100 run at `047699250fdcd98700caff66cbc86c4adf585b87` passed all 264
standalone byte-conversion rows. Its 29 sampled color disagreements disappeared,
but all 108 final clip tuples were byte-identical to the preceding `5f253fb`
observations; 84 still differed from the CPU route. All 44 PNG files also stayed
byte-identical, preserving the original 18 differing pixels in 11 image pairs
(maximum channel difference 3). Exact image parity therefore still failed.

An existing-input arithmetic enumeration narrows the open issue but does not
identify its cause: for 74 of the 105 skin samples, at least one observed clip
component falls outside the enumerated final-projection rounding outcomes with
the CPU world position held fixed. Earlier skin/root arithmetic or cross-stage
algebraic redistribution remain possible. Neither the prior corner files nor
the prior probe observed the GPU's intermediate world position.

## Added observations

The existing bounded triangle selection remains unchanged. Each selected skin
vertex is uploaded twice, adjacently, and executed by a single instrumented
shader. The two existing integer render targets retain:

- even invocation: accumulated skin-space position and its final clip position;
- odd invocation: post-root world-space position and its final clip position.

The generated shader reuses the production body and retains its final clip
expression verbatim. It exposes two additional intermediate fields and selects
which one to store using the invocation index. A maximum of 192 selected source
vertices produces at most 384 invocations. No new render target or storage-write
feature is required. Rigid draws retain the original probe only.

Every selected skin draw records the exact bytes passed to the diagnostic upload:
80-byte vertex records (including all eight ordered joints/weights), their
adjacent duplicates, the 240-byte draw-uniform block, and the fixed 16,384-byte
position/normal palette block. It also retains the live bone count and generated
shader digest. Matrix arrays are column-major little-endian float32; position
matrices occupy the first 8,192 palette bytes and normal matrices the remainder.
The draw uniform starts with the already depth-remapped view-projection, followed
by root and normal matrices, then lighting/material values.

The CPU world-position words come from the original CPU loader mesh, independently
of `ResidentDraw::reference_mesh`. The reader binds them to the selected ordered
corners in the original raw CPU stream, rehashes every command slice (including
unselected commands), and checks the aggregate hash. This diagnostic currently
requires identity per-command model matrices for skin draws; the separately
retained internal root transform is not restricted to identity.

## Retention and interpretation

Version 2 case/result JSON adds the skin observations. The reader preserves
version 1 replay unchanged. Strict version 2 replay additionally requires the
original CPU corner files under the sibling `captures` directory, or an explicit
`capture_directory` argument. A compact report/PNG packet alone cannot establish
those raw-corner joins. The full native artifact continues to retain them.

The fixture writes the original completed 22-case image/corner report before any
optional probe. Stage errors are retained in their case and aggregate result;
incomplete stage output cannot become a completed diagnostic. Existing timeout,
GPU validation, integer readback, and unwritten-pixel guards remain in use.

Exposing intermediate outputs can change compiler optimization. Both invocations
therefore retain their own final clip words and are compared with the ordinary
probe from the same case. Changed final words explicitly limit inference about
the original raster pipeline. Exact uploaded bytes are source-bound host
snapshots, not independent introspection of GPU memory. These observations do
not establish a particular contraction rule or waive image differences.

No new numerical tolerance, performance result, or A100 result is introduced by
this source revision. The unchanged exact-image gate remains authoritative.
