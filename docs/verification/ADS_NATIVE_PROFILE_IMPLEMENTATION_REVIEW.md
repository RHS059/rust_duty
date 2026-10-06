# ADS native visibility: implementation review

Review date: 2026-10-06. **Acceptance remains conditional.** This record establishes specific source, upload, and pipeline properties for the original ADS captures. It does not establish the remaining arithmetic, clipping, or fragment-error bounds, change an acceptance threshold, or claim original native per-draw receipts. The migration remains provisional pending those bounded supplements and the other existing gates.

## Evidence identity and review method

- Original capture: [`8f571464be706d0abde862e124582a188f633baf`, run `37415102452`, attempt 1](https://github.com/RHS059/rust_duty/actions/runs/37415102452).
- Windows source replay and recovery: [`371bca3d848f5b749cf9ea989fa1fbfaca8c20cc`, run `37427554951`, attempt 1](https://github.com/RHS059/rust_duty/actions/runs/37427554951).
- Audited checkout: `fe5fb815136a6fe47cbf4c6b32658f75de2dd3c7`.
- Original `source-receipt.json`: SHA-256 `241bb21d23bb711daaff9dac33b75b504e1c69104fa0949099b38f0f86453370`. Its before/after maps identify 137 files; the review uses these original identities rather than assigning provenance from a newly computed digest alone.
- Original OpenGL source JSONL: 9,579,381 bytes, SHA-256 `93d730d84e5f0055cd51e4e613f7210974ae7a4682bdb7e7f8e246d3ad1227ca`.
- Original DX12 source JSONL: 9,585,202 bytes, SHA-256 `cba85f192290beb1686c35b11bc923b1eeb4a1ca2c855f71c273e62c1d9aa896`.
- Original compiler fingerprint: `5477f9bad65b15c4c5b31fc050fc72feba651ea1b330bc75cf356a4d6b0fbc80`; Windows MSVC Rust 1.99.0. Compiler identity does not itself prove GPU arithmetic.

The source replay diagnostics report 210 fallback frames per backend: 160 empty under the declared profile and 50 visible with matching required/possible supports. Original failing verdicts remain preserved. The 13/13 leaf and 61/61 aggregate automated checks are conditional evidence, not discharge of the profile assumptions.

The reviewer SHA-matched these production files to the original receipt: `src/draw/{facade,mod}.rs`, `src/legacy_macroquad/mod.rs`, `src/render/{arena,mesh,plan,frame,target,device}.rs`, `src/render/mesh.wgsl`, `src/{weapon_model,scene_lighting,viewmodel_draw,app,capture}.rs`, and both Cargo files below. Production rendering implementations in this set are unchanged from the original capture commit. The added `source_pose_snapshot` bridge and its tests were separately reviewed against the original `authored_viewmodel.rs`; they do not replace production drawing with the oracle.

| Bound file | SHA-256 |
| --- | --- |
| `Cargo.lock` | `2aa35ed5561b7e40f515520ec36cb7eaa5c4175f12f0fcf9c764dd0ae6cbdeef` |
| `Cargo.toml` | `ec02a76fb9e8eb29178d707c0f6cfea8206b0299d81f6594fd3cfe0707f55584` |
| Oracle `src/authored_viewmodel.rs` | `c87f0a15241d8a03ec3426eef3b6c3809b257789e4d533c9006e80c3807fdaf5` |
| `examples/source_visibility_certificate.rs` | `c144f7a2a1ecc87bc21a9f3ca76e10e71e14d515ca6d2d4d01f7fbaeceda7862` |

Cached dependency archives were SHA-256 checked against that lockfile. Existing extracted source files were then compared byte-for-byte to their archive members, including the implementation files cited below.

| Dependency | Version | Archive SHA-256 |
| --- | --- | --- |
| glam | 0.27.0 | `9e05e7e6723e3455f4818c7b26e855439f7546cf617ef669d1adedb8669e5cb9` |
| macroquad | 0.4.14 | `d2befbae373456143ef55aa93a73594d080adfb111dc32ec96a1123a3e4ff4ae` |
| miniquad | 0.4.8 | `2fb3e758e46dbc45716a8a49ca9edc54b15bcca826277e80b1f690708f67f9e3` |
| naga | 30.0.1 | `a616d2fb8c89516ac2723a581f69d6c18576046bed761bd6b305e5618e6ae130` |
| wgpu | 30.0.1 | `527ccdf43dd5b2e8676eed9984ce00e2bbb0a1b85b70c1969dcb6cd2eb55ab9e` |
| wgpu-core | 30.0.1 | `14c018fce9b6270aa203c2fdd56f3cce996713534bd757e4ea58c8560b121f14` |
| wgpu-hal | 30.0.1 | `b6b7fb58561a792bc237628ba0792e332de418fefe145f13b5ed8201e6d52f58` |
| wgpu-types | 30.0.1 | `99dad6f1fbdbbdb4c278a6508b059d44688f5cebddf78d005a46a31340269286` |

## Source geometry to submitted draws

The [oracle bridge and drawing implementation](https://github.com/RHS059/rust_duty/blob/371bca3d848f5b749cf9ea989fa1fbfaca8c20cc/src/authored_viewmodel.rs) select the same effective animation and pose: active reload presentation, otherwise layered locomotion, otherwise fixed-time or simulation-time sampling. The bridge fails on renderer errors, nonfinite time/root, and nonzero cant. Independent source companions own the oracle's mesh inventory; matching CRCs are checked for ambiguous differing bytes.

Skin batching partitions the complete index stream into 4,998-index chunks, preserves order, and maps every local index back to its original vertex. Production deformation and source enumeration both apply the skin palette, weighted positions, common root, normal transformation, and CPU lighting. [Rigid drawing](https://github.com/RHS059/rust_duty/blob/8f571464be706d0abde862e124582a188f633baf/src/weapon_model.rs) similarly retains source mesh identity, complete triangle partitions, actor transforms, visibility, and quantized opacity. Mesh validation rejects invalid indices or nonfinite attributes. These arguments assume the already-bound replay state; they do not infer state from candidate pixels.

The facade records the mesh and model transform. Its camera projection includes `look_at_rh(0, -Z, Y)`, which is the identity view for this capture. The model stacks begin at identity and the audited pushes/pops are balanced. Their identity multiplications do not introduce an additional nontrivial transform into the certificate's model.

### OpenGL

In [the legacy backend](https://github.com/RHS059/rust_duty/blob/8f571464be706d0abde862e124582a188f633baf/src/legacy_macroquad/mod.rs), `execute_command` expands each index chunk to at most 4,095 vertices and sequential local indices. This is below macroquad's 10,000-vertex/5,000-index capacities. Both partition sizes are divisible by three. Macroquad's subsequent batching starts a new draw before exceeding capacity and offsets appended indices by the existing vertex count.

Macroquad's `Cargo.toml:198` enables glam `scalar-math`. Its `models::Vertex` is therefore 40 bytes with offsets position=0, UV=12, color=20, normal=24. This agrees with `quad_gl.rs:484` declaring Float3/Float2/Byte4/Float4 and miniquad's computed stride. The byte color attribute is unnormalized; the vertex shader divides by 255.

Macroquad `quad_gl.rs:707–787` uploads each draw's vertex/index slices, assigns its texture, sets Projection and Model, applies uniforms, and submits its full index count. Miniquad `graphics/gl.rs` forwards bytes through `glBufferSubData` (`buffer_update`), matrices through `glUniformMatrix4fv` with transpose=false (`apply_uniforms_from_bytes`), and indices as unsigned shorts to `glDrawElementsInstanced`. The production vertex expression is `Projection * Model * vec4(position, 1)`.

### DX12

[FrameArena](https://github.com/RHS059/rust_duty/blob/8f571464be706d0abde862e124582a188f633baf/src/render/arena.rs) explicitly serializes the same 40-byte vertex schema and u16 indices. Each draw retains its own slices and aligned 64-byte transform. `clip_matrix` computes `(remap * projection) * model`; the matrix is serialized in column order. `mesh.rs::upload_geometry` creates buffers from exactly these byte arrays. `frame.rs::issue` binds the draw's slices and dynamic matrix offset, then draws the complete local index count with base vertex zero.

The [WGSL shader](https://github.com/RHS059/rust_duty/blob/8f571464be706d0abde862e124582a188f633baf/src/render/mesh.wgsl) multiplies that matrix by the position. Naga `back/hlsl/mod.rs:29–55` and `writer.rs:1477,3814` intentionally pair row-major HLSL matrix storage with reversed `mul` operands, preserving WGSL semantics. The application pins Fxc; wgpu-hal loads `d3dcompiler_47.dll` and uses `D3DCOMPILE_ENABLE_STRICTNESS`. This traces the compiler path, not an original compiled-shader disassembly.

## Offscreen target and pipeline

The captured reference image is the viewmodel target, not the multisampled window. `src/capture.rs::write_frame` selects this target for reference captures.

GL `ensure_texture` calls `render_target_ex` with `sample_count=0`. Macroquad `texture.rs:407–450` takes the non-resolving branch. Miniquad `graphics/gl.rs:194–253,1077–1118` consequently creates ordinary GL_TEXTURE_2D color/depth textures and attaches them using `glFramebufferTexture2D`, without multisample storage or resolve attachments. This establishes single-sample allocation by implementation; `queried_framebuffer_samples=null` remains an accurate description of the original receipt.

DX12 `target.rs` explicitly creates single-sample textures. Its pipeline defaults resolve to count=1, full sample mask, alpha-to-coverage=false. The HAL passes those values to the native sample description. The reviewed paths select triangle fill, no culling, ordinary depth testing, full-target viewport/scissor, and shaders without discard. Alpha meshes write depth and use source-over blending; opaque behavior at required samples still depends on the bounded alpha/color reasoning below.

## Input-specific rigid-only contrast reduction

The reviewer independently decoded and SHA-matched these actual companion bytes:

| Input | Bytes | SHA-256 |
| --- | ---: | --- |
| Locomotion VRM | 10,641,724 | `d11736162b2cda993db3cdd5d4015aff2b151ea6377b8b954370b54006e02d67` |
| Locomotion VRS | 16,663,274 | `b38b7f823ddf7bd6f032ed98d33f055cd444caf51558146911b7a678c6e3ce92` |
| Reload VRM | 4,156,248 | `721986357228951a33cba32cbe088aceb76169fa9c0c97482355775aad85026a` |
| Reload VRS | 13,605,994 | `c2b585cb8dcc68652fb523bad976730d2d3db88f6442c5efc69f009ceb2b20d7` |

All 30/33 rigid meshes have zero texture bytes and base RGB=(0.38,0.40,0.42). Both backends supply an immutable 1×1 white fallback: macroquad `quad_gl.rs:578,746`, and application `src/render/backend.rs:90`.

Each source's three skin meshes have base RGB=(1,1,1), with per-channel texture ranges [0,255], [40,196], [0,255]. `SceneLighting::irradiance` is at least 0.35; source skin vertex bytes are therefore at least 89. In `source_visibility_certificate.rs::contrast`:

- The full-range textures yield lower bound zero and upper bound at least 89, so no channel passes.
- The middle texture always gives lower bound at most 40 and upper bound at least `ceil(89*196/255)=69`. Neither side satisfies any channel's existing strict clear=(36,48,61), tolerance-plus-error=11 test.

Consequently no skin triangle supplies required contrast. `Samples::required` additionally subtracts the possible support of every unsafe-color triangle, including all skin triangles and nonopaque rigid triangles. Every required sample is therefore supplied by untextured rigid geometry, with possible unsafe overlap excluded, conditional on the coverage bounds. This applies to all 553 source frames and hence the 50 visible fallback frames. It removes arbitrary skin texture filtering from the positive-color obligation; it does not remove skin geometry from possible-support completeness.

## Remaining premises and acceptance boundary

1. **Transform arithmetic.** Gamma17/gamma24 describe conservative operation-count envelopes for the audited expressions under the stated floating-point model. The random host matrix tests do not establish all actual-input intermediate ranges, underflow behavior, or native shader arithmetic. The bounded supplement must justify those domains or account for permitted absolute underflow error.
2. **Clipping and raster support.** The existing mask uses original projected triangles plus intervals; generated X/Y clip vertices and subsequent snapping need an explicit bound. The required result is set containment: required support is covered, and actual coverage lies within possible support. Microsoft's clipping/snapping rules distinguish these stages; minimum subpixel precision alone does not discharge the clipping bound. [Direct3D specification, §§3.4 and 15.4–15.16](https://microsoft.github.io/DirectX-Specs/d3d/archive/D3D11_3_FunctionalSpec.htm)
3. **Rigid color and alpha.** The original GL receipt reports vertex highp=23 bits, but vertex lowp and fragment lowp/mediump=10 bits. The production shaders use version 100 and lowp varyings. A three-byte bound must include varying interpolation, alpha, blending, and output conversion; reported storage precision alone is insufficient. A full-fp32 assumption is not established here. [GLSL ES 1.00, §4.5](https://registry.khronos.org/OpenGL/specs/es/2.0/GLSL_ES_Specification_1.00.pdf)
4. **Actual GL component format.** Miniquad's ordinary RGBA8 enum maps to unsized GL_RGBA plus GL_UNSIGNED_BYTE, not sized GL_RGBA8. Component resolution is implementation-chosen. A bounded Mesa implementation review or appropriately bound measurement must establish the storage/conversion bound. GL dithering chooses adjacent representable values, whose spacing depends on that format. [OpenGL 4.6, §§8.5 and 17.3.8](https://registry.khronos.org/OpenGL/specs/gl/glspec46.core.pdf)

This review supplies an implementation-equivalence basis for the audited upload and pipeline properties. It leaves the original false/null profile flags and failing verdicts intact. Any later bounded supplement must identify exactly which premises it discharges and bind its result to these unchanged inputs and captures. Later native observations, if needed, are corroboration and must not be relabeled as original-run per-draw receipts. This review performed no native rendering, changed no production source, and published no evidence.
