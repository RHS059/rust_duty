# Cedar Junction screen-size LODs

Task B stage 4 uses pinned `meshopt = 0.7.0` (meshoptimizer 1.3) to generate
up to two genuinely reduced meshes for each authored static asset record.
The original mesh is level 0 and is never modified. Reduction targets are
50% and 25% of the original triangle count, with 0.5% and 1.5% combined
geometric/attribute relative-error limits. Those are targets, not guarantees:
tiny or topology-constrained assets retain fewer distinct levels.

The runtime applies this to catalog `bNN_` asset identities except the `b21_`
architectural kit. Walls, floors, window/door openings, procedural trim and
lettering remain exact. Legacy coarse material batches also remain exact:
they cannot safely be treated as one asset. This deliberately means the
current implementation does not promise three levels for every city record.
Each generated level is an immutable `StaticMesh`, created once at load and
uploaded only on first use. The live `CityLevel::draw` selects the mesh after
the same instance frustum, range and portal tests used without LODs.

Normals, baked RGBA colors and UVs participate in the error metric. Borders
remain locked; permissive seam handling allows colored/faceted assets to
simplify. Every output vertex is an exact original vertex sample. Vertex
cache optimization and dense vertex remapping remove unused samples without
inventing interpolated attributes. No simulation or collision geometry changes.

Selection is based on projected AABB size with a conservative bounding-sphere
floor, measured as a fraction of viewport height. Level 1 starts below 18%;
level 2 below 6%. Zooming changes detail selection. Camera-inside, near-plane
intersection, invalid projection and behind-camera cases retain full detail.
The two reduction attempts keep fixed half/quarter slots. If the stricter
half-detail attempt cannot simplify but the quarter-detail attempt can, the
quarter mesh still starts only below 6%; it is never promoted to the 18%
threshold. An unavailable tier falls back to the next finer available mesh,
including the unchanged original.

Generation happens outside frame recording. Startup generation costs must be
reported separately from steady-state render measurements. There is no
per-frame simplification and no quality/FPS claim from a triangle-count change.
The benchmark reports `startup.scene_load_ns` separately and includes the
full-scene triangle inventory at each available level (falling back to the
next finer available level), plus the number of records with reduced geometry.
Review distant silhouettes, color boundaries and transitions on the target
GPU before accepting visual quality. Large coarse legacy chunks do not imply
per-asset LOD identity; the instance exporter is required for that claim.

## Verified module evidence

The focused Rust suite exercises two distinct reductions, exact preservation
of vertex samples, compact index validity, malformed-input rejection before
FFI, zoom-sensitive screen selection, near-plane and camera-inside behavior, and all four half/quarter availability
combinations through both runtime projection and benchmark inventory selection.
An exploratory native CPU run on three public source assets produced:

| Asset | Full triangles | LOD 1 | LOD 2 |
|---|---:|---:|---:|
| Classic A-frame picnic table | 792 | 776 | 376 |
| Concrete Jersey barrier | 220 | 156 | 116 |
| Honeylocust | 3,850 | 1,998 | 962 |

These are simplifier output counts, not render-performance measurements or a
visual acceptance result. Source repository: `RHS059/low_poly_items`, commit
`3a87b1f2611c56fcfbfc7b39adaf914ab5359446`. No asset bytes are included here.

Upstream implementation/documentation: [meshopt Rust bindings](https://github.com/gwihlidal/meshopt-rs)
and [meshoptimizer](https://github.com/zeux/meshoptimizer). License notices are
under `docs/third_party/`; the dependency is obtained from the locked registry,
not copied into this repository.
