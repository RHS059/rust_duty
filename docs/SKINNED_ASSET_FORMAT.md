# VRSKIN02: local skinned mesh container

This is an independently authored, bounded container and importer for locally
licensed first-person rigs. It is separate from VRMESH01. The static importer
`tools/vrpack.py` still rejects all skinning and animation. Neither container is
encryption, DRM, or permission to redistribute an imported asset.

Only generic tools, runtime code, and independently generated test fixtures belong
in a public repository. Keep source rigs, textures, converted files, rig metadata,
and private screenshots outside the repository unless their license allows sharing.

## Commands

The Python importer uses the standard library plus Pillow for embedded images,
and reuses the unchanged validation helpers in its sibling `vrpack.py`.

```sh
python3 tools/vrskin.py pack /private/path/arms.glb /private/path/arms.vrs --base-color-only
python3 tools/vrskin.py inspect /private/path/arms.vrs
python3 tools/verify_skin_bind.py /private/path/arms.glb /private/path/arms.vrs
python3 -m unittest discover -s tests -p 'test_vrskin.py' -v
rustc --edition=2021 --test src/skinned_asset.rs -o /tmp/test-skinned-asset
/tmp/test-skinned-asset
```

Existing outputs are not overwritten without `--force`; writes use an atomic
same-directory, no-clobber operation. Source and destination must differ.

`--base-color-only` is explicit consent to omit normal, occlusion, and
metallic-roughness textures. The converter prints every omitted material map. It
also announces any conversion from linear mipmapped minification to LINEAR
sampling without mipmaps. Base-color factor, base-color RGBA image, metallic
factor, and roughness factor are retained. The image's original encoded color
channels are decoded to RGBA8, without a color-space conversion. No silent PBR
approximation or texture reduction occurs without that flag. Emissive, alpha
blending/masking, double-sided materials, non-REPEAT wrapping, nearest filtering,
and unsupported extensions remain rejected.

## Header

All numbers are little-endian. The 24-byte header contains:

| Offset | Type | Meaning |
| --- | --- | --- |
| 0 | 8 bytes | ASCII `VRSKIN02` |
| 8 | u32 | Version, exactly 2 |
| 12 | u32 | Payload byte length, excluding header |
| 16 | u32 | IEEE CRC-32 of the payload |
| 20 | u32 | Reserved, exactly zero |

CRC detects accidental corruption; it does not authenticate or protect the data.

## Payload

There is exactly one skeleton, followed by one or more mesh primitives:

1. Bone count: u32, 1..128
2. Each bone:
   - Name byte length: u16, 1..64
   - Name: that many valid UTF-8 bytes, no NUL
   - Parent: i32, -1 for a root or a bone index
   - Local rest matrix: 16 float32, column-major
   - Inverse bind matrix: 16 float32, column-major
3. Mesh count: u32, 1..128
4. Each mesh:
   - Base-color factor: four float32
   - Metallic and roughness factors: two float32
   - Texture width, height, byte length: three u32
   - Embedded raw RGBA8 pixels: exactly the declared byte length
   - Vertex count and index count: two u32
   - Vertex records, each exactly **80 bytes**:
     - Position: three float32
     - Unit normal: three float32
     - UV: two float32
     - Joint indices: **eight u16**
     - Joint weights: **eight float32**
   - Triangle indices: index count u32 values

No padding, alignment gaps, trailing data, animation clips, or external resources
exist in the container. Textures are repeated per primitive, not deduplicated.
An absent texture has width, height, and byte length all zero. Otherwise its size
must be width × height × 4, with dimensions 1..2048.

### Skeleton and coordinate semantics

Matrices follow glTF's column-major convention. Bone indices are exactly the
source `skin.joints` ordering, so a parent may have a later index than its child.
Consumers must compose the hierarchy by parent links, not array order. Multiple
roots are permitted; cycles and out-of-range parents are rejected.

For each source joint, the converter walks toward the nearest joint ancestor and
multiplies every intervening non-joint local transform into its rest-local matrix.
For a root joint, all non-joint ancestors up to the scene root are baked in. Thus:

```text
jointGlobal[j] = jointGlobal[parent[j]] * restLocal[j]
rootGlobal[j] = restLocal[j]
skinMatrix[j] = jointGlobal[j] * inverseBind[j]
worldPosition = sum(weight[k] * skinMatrix[joint[k]] * sourcePosition)
```

No axis, unit, first-person placement, or mesh-node transform is baked into vertex
positions. The output retains glTF coordinates and source units. The runtime may
apply a separate model/viewmodel transform after skinning.

In glTF's common local-rendering formulation, each joint matrix contains
`inverse(meshGlobal) * jointGlobal * inverseBind`; the draw then applies
`meshGlobal`. These mesh transforms cancel for the resulting world-space vertex.
The converter deliberately uses this world-space formulation. It validates every
selected mesh-node global transform as finite, affine, and nonsingular, but does
not multiply that transform into vertices or inverse binds. Baking it again would
apply the transform twice. The synthetic fixture includes a translated mesh node
to detect that error.

Each rest matrix and inverse bind must be finite, affine, and nonsingular. Affine
last-row values are exactly (0, 0, 0, 1). Inverse binds are copied unchanged from
the source float32 data; if glTF omits them, the specified identity default is used.
Rest pose is not required to equal bind pose. For example, identity inverse binds
may intentionally produce non-identity rest deformation. The verifier compares
against the source skinning formula rather than requiring an identity skin matrix.

Source JOINTS_0/WEIGHTS_0 are required. Optional JOINTS_1/WEIGHTS_1 must appear
together. All eight influences, including repeated joints and ordering, are
preserved. Missing second sets are zero-padded. Nonnegative source weights with a
positive sum are normalized across both sets; no strongest-four truncation occurs.
Joint indices must be valid even for zero-weight slots. Float weights and normalized
unsigned 8-/16-bit weights are accepted. Joint attributes use unsigned 8-/16-bit
unnormalized components. Imported source normals are normalized, or generated for
nondegenerate triangles when absent.

For animation, update joint local matrices, reconstruct globals by parent links,
and skin vertices. Normals should use the inverse transpose of the blended skin
linear matrix when transforms contain nonuniform scale; a normalized linear
rotation blend is only an approximation under scale. The container itself does not
render, animate, solve IK, or choose camera placement.

## Bounds and rejected input

- File maximum: 128 MiB, including header
- Skeleton and mesh primitive maximum: 128 each
- Aggregate vertices: 1,000,000; aggregate indices: 3,000,000
- Aggregate raw texture data: 64 MiB; each dimension at most 2048
- Positions bounded to ±10,000; UVs bounded to ±1,000,000
- All float fields finite; material factors in [0, 1]
- Normal squared length in [0.98, 1.02]
- All eight weights in [0, 1], sum in [0.9999, 1.0001] using float32 arithmetic
- Geometry nonempty; triangle index counts divisible by three; indices in range
- At most 100,000 source nodes and hierarchy depth 256

The importer accepts one embedded GLB 2.0 buffer, one selected scene, exactly one
skin, and only mesh nodes using that skin. It rejects embedded animations, morphs,
sparse accessors, unsupported attributes/extensions, external/data-URI resources,
invalid alignment/strides, multiply parented nodes, and cycles. It never retrieves
resources or executes source metadata. Extra material/name metadata is not copied,
except joint names needed for animation lookup.

The Rust decoder uses only the standard library. Every read and count is checked;
it proves geometry bytes exist before allocating vertex/index vectors. Decode and
load return `Result`, with no panic-based malformed-input handling.

## Independent verification

`tools/make_skin_fixture.py` builds both a tiny GLB and expected VRS independently
of the converter. The original two-bone triangle uses a forward-indexed parent,
transformed non-joint ancestors, and a non-identity mesh transform. Its expected
VRS is compared byte-for-byte with the converter output.

`tools/verify_skin_bind.py` independently reconstructs source and output globals,
compares every joint and every skinned vertex, and checks all eight influence
slots. It can optionally compare separate exported rest matrices with
`--rest-metadata /private/path/rest.json`. This remains a local operation.
Python and Rust malformed-input tests cover truncation, headers, parent cycles,
names, matrices, counts, indices, textures, geometry attributes, and weights.
