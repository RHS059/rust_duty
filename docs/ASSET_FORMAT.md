> Intermediate source-only update: the supplied HK416 was verified locally, but its model binary and new screenshots are not in this commit. The game uses its procedural fallback until the separately authorized single asset upload finishes.

# Local model conversion and VRMESH01 v1

`tools/vrpack.py` converts a supported **static GLB 2.0 mesh** into the game's
bounded mesh format. It parses the scene, bakes node transforms, normalizes normals,
corrects winding for reflected transforms, decodes optional base-color images,
and writes mesh records. The result is **not a GLB wrapped with a new extension**.
Source JSON, object names, author metadata, cameras, source image files, and the
original GLB are not included. Geometry, UVs, base-color pixels, and material
factors remain recoverable.

## Rights and distribution

Conversion is not encryption, DRM, copy protection, or a substitute for the
artist's permission. CRC32 detects accidental corruption; it does not authenticate
an asset. Compiled embedding also does not prevent extraction. A person who has the
binary or package can reconstruct meshes and textures.

The user-supplied HK416A5 has been converted and tested locally. Only its single
converted package `assets/weapons/hk416a5.vrm` is included, with the user's stated
artist permission. Original FBX and intermediate GLB are excluded. This permission
does not authorize publication of other purchased models
or an artist's whole library. The 180-byte `tests/fixtures/triangle.vrm` is an
original generated triangle, not a fragment of that weapon model.

Other model inputs and outputs must remain local unless their specific license
and permissions allow the intended distribution. `.gitignore` excludes
`private-assets/`, `licensed-assets/`, FBX/GLB/GLTF/Blend files, and VRM packages,
with narrow exceptions for the original triangle and the separately authorized
converted weapon. Do not bypass those exclusions for another licensed asset.

## Quick start

Python 3.10+ is sufficient for untextured meshes. Optional embedded PNG/JPEG
base-color textures need Pillow from the ordinary Python package registry:

```sh
python3 -m pip install -r tools/requirements-assets.txt
```

Convert a model you have permission to use, on your own machine:

```sh
python3 tools/vrpack.py pack /absolute/path/to/model.glb private-assets/weapon.vrm
python3 tools/vrpack.py inspect private-assets/weapon.vrm
cargo run --release -- --weapon-asset=private-assets/weapon.vrm
```

Create the output directory first if it does not exist. Input and output cannot
be the same path. Existing output is not overwritten unless `--force` is supplied.
The packer validates the whole output before publishing it atomically; a failed
conversion does not replace an existing file. No URLs are fetched and no assets
are uploaded. Without an explicit runtime asset override, the game uses the
embedded model when available, otherwise its original procedural rifle.

### Alignment and units

The viewmodel expects **meters, +Y up, barrel toward -Z, and grip near the origin**.
Check model scale and orientation in your modeling tool. Bake any intended pose
and static geometry before exporting GLB. The converter does not infer gun parts,
resize an asset automatically, generate rigging, or supply missing textures.

- `--scale S` applies a positive, finite uniform scale after the scene transform
- `--axes gltf` is the default; it preserves glTF x/y/z (right-handed, +Y up)
- `--axes z-up` intentionally converts a custom Z-up export by mapping
  `(x, y, z)` to `(x, z, -y)`; do not use it if your exporter already converted to glTF axes
- `--translate X Y Z` adds an offset **after** the scale and axis conversion,
  in output units

The prepared local HK416A5 intermediate uses the example below. The neutral gray
material was explicitly prepared in Blender; the converter did not silently drop
unsupported material maps. No texture set was supplied.

```sh
python3 tools/vrpack.py pack private-assets/hk416a5-local.glb private-assets/weapon.vrm \
  --scale 1 --axes gltf --translate 0 -0.03 -0.15
```

If you need arbitrary rotations, pivot adjustment, material simplification, or a
different pose, perform them explicitly in your modeling tool. Inspect the output
bounds before testing in the game.

### Compiled embedding

The build embeds `assets/weapons/hk416a5.vrm` by default when that specifically
authorized file is present. To embed a different locally licensed converted
model **in your own local build**, use an absolute path:

```sh
VR_WEAPON_ASSET="$(pwd)/private-assets/weapon.vrm" cargo build --release
```

PowerShell:

```powershell
$env:VR_WEAPON_ASSET = (Resolve-Path private-assets/weapon.vrm).Path
cargo build --release
Remove-Item Env:VR_WEAPON_ASSET
```

`build.rs` validates the selected bytes with the Rust decoder, stages the package
in Cargo's `OUT_DIR`, and generates an `include_bytes!` binding. The executable
contains the mesh bytes; it does not need that file next to it at runtime. Keep
Cargo build outputs private when they contain assets not cleared for distribution.

The private `VR_WEAPON_ASSET` override is rejected whenever `CI` is set, including
`CI=false`, to avoid accidentally copying a local licensed asset into a CI artifact.
The specific authorized repository model can still be embedded in ordinary CI
builds. A runtime `--weapon-asset=...` override takes priority over the embedded
model. A rejected package produces an error notice and falls back to the
procedural rifle instead of loading unvalidated geometry.

## Supported GLB subset

This is intentionally a strict, small pipeline. Unsupported features fail with a
message; the packer does not silently reinterpret them.

- GLB container version 2, glTF asset version 2.0, JSON followed by embedded BIN
- One embedded buffer; no external files, HTTP requests, or data-URI resources
- The declared default scene; if `scene` is omitted, the first scene is selected
- Static scene nodes with a column-major affine `matrix` **or** TRS
  (translation, normalized quaternion rotation, scale)
- A proper tree in the selected scene; cycles, repeated nodes/multiple parents,
  singular transforms affecting a mesh, and more than 256 hierarchy levels fail
- Mesh instances are flattened independently, including parent transformations
- Triangle primitives only, indexed or unindexed; 8-/16-/32-bit unsigned indices
- Float32 `POSITION` and optional float32 `NORMAL` and `TEXCOORD_0`
- Interleaved attribute buffer views, with validated offsets and strides
- Missing normals are area-weighted smooth vertex normals computed from triangle
  winding; export explicit normals or split vertices to preserve hard edges
- Missing UVs become `(0, 0)` only when the material has no base-color texture
- Opaque, single-sided metallic/roughness materials with base-color factor,
  metallic factor, roughness factor, and an optional embedded PNG/JPEG base-color map
- Base-color images decoded to uncompressed RGBA8; no resizing or color conversion
  beyond image-mode conversion to RGBA. UVs are unchanged and image rows are
  top-to-bottom. PNG alpha bytes are preserved in the package; runtime upload
  forces alpha to fully opaque, matching the supported opaque surface materials
- Samplers must use repeat wrapping on both axes and linear, non-mipmapped
  filtering. Omitted sampler/filter settings use the pipeline's repeat/linear
  convention. Nearest, clamp/mirror, and mipmapped minification are rejected

Extensions (even optional ones) are rejected because they can change attribute,
texture, or material semantics. This includes Draco/meshopt compression,
quantization, texture transforms, unlit materials, and alternate texture formats.
Animations, skinning, morph targets/weights, sparse/normalized accessors,
non-triangle modes, vertex colors, tangents, extra UV sets, blend/mask materials,
double-sided materials, normal/occlusion/emissive/metallic-roughness maps, and
nonzero emissive factors are unsupported. Empty scenes or meshes fail. Unused
`extras` and descriptive JSON metadata are discarded. Material and resource
features are checked globally; scene geometry is read from the selected scene.

The runtime renderer uses base-color factor/texture and normal-based diffuse
shading. Metallic and roughness factors are retained by the format for future
use, but the current renderer is **not a full glTF PBR renderer**. An asset can
therefore look different from its original authoring-tool preview even when all
supported values are preserved.

## Binary contract

All integers and IEEE-754 float32 values are **little-endian**. There is no
alignment padding between records. Bytes must end exactly at the final index;
trailing bytes are rejected. The filename suffix `.vrm` here means Vector Range
mesh; it is unrelated to the separate VRM humanoid-avatar ecosystem.

### Header (24 bytes)

| Offset | Size | Meaning |
| --- | --- | --- |
| 0 | 8 | ASCII `VRMESH01` |
| 8 | 4 | `u32` version, exactly `1` |
| 12 | 4 | `u32` payload byte length, excluding this header |
| 16 | 4 | Standard IEEE CRC32 of the entire payload (`zlib.crc32`) |
| 20 | 4 | Reserved `u32`, must be `0` |

### Payload

First comes a `u32 mesh_count`. For each mesh, in order:

| Field | Encoding |
| --- | --- |
| Base color RGBA | Four `f32` values |
| Metallic, roughness | Two `f32` values |
| Texture width, height, byte length | Three `u32` values |
| Texture texels | Exactly byte-length RGBA8 bytes, row-major, top-to-bottom |
| Vertex count, index count | Two `u32` values |
| Vertices | Vertex-count records of eight `f32`: position xyz, normal xyz, UV uv |
| Triangle indices | Index-count `u32` indices into this mesh's vertex array |

For no texture, all three texture fields are zero and no texels follow. A texture
is repeated per primitive instance; there is no shared texture table. Counter-
clockwise front-face winding is retained after reflected transforms by swapping
the second and third indices in each triangle. Normals are transformed with the
inverse transpose and renormalized.

### Decoder limits and validation

Both the Python inspector and Rust decoder enforce:

- Entire package at most 128 MiB; exactly 1–256 mesh records
- At most 1,000,000 vertices and 3,000,000 indices across all meshes
- Nonempty vertex and index arrays; index counts divisible by three; every index
  strictly below the corresponding vertex count
- Texture dimensions at most 2048 each; either all-zero texture fields or
  positive dimensions with byte length exactly `width * height * 4`
- At most 64 MiB of uncompressed texture bytes across all records
- All float values finite; all six material factors in `[0, 1]`
- Absolute position coordinates at most 10,000 and absolute UV coordinates at
  most 1,000,000
- Unit normals, permitting squared length in `[0.98, 1.02]` for decoder tolerance;
  the packer itself emits normalized vectors
- Exact payload length, CRC32, version, reserved word, record bounds, and no
  trailing bytes

The converter additionally validates GLB chunk bounds, JSON duplicate keys,
accessor counts/types/alignment/strides, embedded buffer ranges, finite source
values, scene transforms, and supported semantics before producing bytes. Input
GLBs are also limited to 128 MiB. CRC32 and defensive bounds checking are
correctness measures, not an authenticity or confidentiality claim.

## Tests and fixture regeneration

```sh
python3 -m unittest discover -s tools -p 'test_*.py' -v
python3 tools/test_vrpack.py --write-fixture tests/fixtures/triangle.vrm
python3 tools/vrpack.py inspect tests/fixtures/triangle.vrm
cargo test
```

The Python suite creates original tiny GLBs entirely in memory. Texture tests use
original generated pixels and skip only if optional Pillow is unavailable. Tests
exercise transformed and mirrored meshes, inverse-transpose normals, scene
instancing, matrix/TRS input, scale/axis/translation, interleaved accessors,
PNG/JPEG decoding, unsupported features, malformed accessor bounds, hierarchy
cycles, limits, non-finite data, version/checksum corruption, truncation,
no-clobber atomic writes, and the CLI. Rust tests independently read the same
checked-in triangle bytes.

The original triangle fixture has 1 mesh, 3 vertices, 3 indices, no texture,
156 payload bytes, and 180 total bytes. Its payload CRC32 is `6e95788a`; SHA-256 is
`16b4be0a09a4dbcc2da4bd05fcb942201fb2bed6e2554a3e7e0e56390dd664fc`.
