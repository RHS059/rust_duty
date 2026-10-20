# Authored city instance visibility

Status: implementation and CPU contract coverage. No hardware FPS claim.

## Runtime ownership

`CityLevel` converts geometry once to immutable `StaticMesh` resources. A median
BVH is built once over actual vertex-derived AABBs. Rendering traverses only
intersecting BVH nodes, then tests each candidate record against the exact
world-camera view-projection matrix. Node traversal is near-first. Large and
straddling geometry lives in one leaf, so it cannot fall between grid cells or
be submitted twice. Frustum tests preserve near-plane crossings and view edges.

Distance is measured to the nearest point of the AABB, not its center. Only
explicit catalog entries for small handheld/food props receive the 120 m
cutoff. Missing/zero `max_distance` means the normal 400 m city far range.
Architecture, windows, doors, road markings, and unknown assets never acquire a
short cutoff based on size. Gameplay collision is unchanged.

`CityLevel::visit_visible` reports candidate traversal counts for CPU checks and
benchmarks. They are not GPU duration or performance estimates. The game calls
the same visibility owner through `CityLevel::draw`; it does not maintain a
second full-scene filtering loop.

## RDCITY04 wire format

All numeric values are little-endian. Optional gzip wraps the complete stream;
both compressed and inflated content are bounded to 768 MiB.

1. Eight bytes `RDCITY04`.
2. `u32 flags`: 0 = source normals/colors, 1 = prelit normals/colors,
   3 = compact prelit. Other values (including 2) are rejected.
3. `u32 metadata_byte_count` followed by UTF-8 JSON (at most 32 MiB).
4. `u32 record_count` (1 through 262144).
5. Each record: minimum XYZ and maximum XYZ (`6 × f32`), vertex count (`u32`),
   index count (`u32`), vertices, then triangle indices (`u32` each).

Uncompressed vertices contain XYZ, normal XYZ and RGBA (`10 × f32`). Compact
prelit vertices contain XYZ (`3 × f32`) and RGBA (`4 × u8`). At most 4 million
vertices and 12 million indices occur in a record. Indices must be in range;
index counts must be positive multiples of three. Bounds, positions, normals
and colors must be finite. Colors are in [0, 1]. Bounds are verified against
geometry, then recomputed for runtime culling (accepted export rounding never
shrinks the culling box). Trailing bytes, truncation and gzip corruption fail.

The metadata JSON is an array with exactly one entry per geometry record. Each
entry is null (unclassified geometry, e.g. generated lighting panels) or:

```json
{"id": 17, "asset": "b16_takeaway_coffee_cup", "building": "B01", "max_distance": 120.0}
```

`id` is a u32 source identity; `asset` is a nonempty string up to 512 bytes;
`building` is optional/null or a nonempty string up to 128 bytes.
`max_distance` is optional, finite, and in [0, 400]. Zero is unlimited within
the world far plane. Multiple bake-subdivision records may carry the same
source identity. Every exporter part carries its actual geometry; spatial
batches are never relabeled as buildings or assets.

RDCITY01/02/03 remain readable and retain their original legacy batch identity
(`instance = None`). They get BVH/frustum culling, with no invented per-instance
small-prop policy. Mutable u16 CPU APIs remain compatible: a wide v4 record is
split along whole triangles with a local vertex remap, never a narrowing cast
of an out-of-range index. Each split preserves its source identity. The lighting
baker and compactor carry identities through subdivision and emit compact
prelit v4 for modern sources; the range and legacy bakes retain their existing
writer.

## Rebuilding and compatibility

```sh
python tools/build_city.py --source ../low_poly_items --out /tmp/cedar-v4 --no-write-source-lock
python tools/validate_city.py --help
```

Use the pinned source revision in `tools/city_source_lock.json`, plus the build
workflow's pinned NumPy/Pillow versions for reproducible source/lettering.
An isolated `--out` does not change the committed level or source lock.

Modern manifests declare `geometry_format: "RDCITY04"`. If an old coarse bake
is beside a modern manifest, runtime loads the instance source instead of
silently losing instance ownership. That fallback uses source lighting, not the
old bake; rebuild the bake to restore the authored baked-lighting appearance.
Legacy manifests and committed legacy assets still load as before. This source
change does not itself replace those committed binary assets. A scene exported
with the new format is required for per-instance distance-policy benefits.

Synthetic tests exercise original geometry, wide indices, malformed metadata,
compressed integrity, and BVH parity with a brute-force visibility oracle over
multiple aspect ratios and camera orientations. Full scene regeneration and
native captures are separate evidence; no CPU-only check establishes visual
acceptance or hardware gameplay FPS.

## Reproducible geometry identity check

```sh
python tools/verify_city_geometry.py assets/levels/cedar_junction /tmp/cedar-v4 --report /tmp/city-parity.json
```

This hashes each ordered triangle's original position, normal and RGBA float
bytes, then compares the sorted digest multisets. Triangle winding and duplicate
triangle counts matter; chunk order and shared-vertex packing do not. Directory
mode also compares original collision, building, placement and spawn fields.
It explicitly rejects formats without complete source normals for this proof.

The pinned isolated rebuild used for this change produced 12,464 authored
records, 5,740,304 vertices and 2,740,498 triangles. Its complete ordered-triangle
multiset matched the committed source (269 legacy batches), with digest
`f434d7bcaf38b6e70b47cb4193c5a590191be6e5ba8c2a0609b123fc75f35cf8`.
The independent city validator checked 125 source digests and 189 walking
routes. The explicit regenerated-scene Rust test exercised production loading,
static-resource construction and BVH selection; native rendering appearance
and hardware performance remain separate, unclaimed checks.
