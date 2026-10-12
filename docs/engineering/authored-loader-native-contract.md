# Exact authored-loader dedup contract

This is the isolated PR51 loader experiment. It keeps the reviewed destination
reuse and arena serializer identical in both builds. The baseline restores only
`src/authored_viewmodel.rs` and `src/weapon_model.rs` from exact source
`5a88053e1668000744bbebbf967c6d24833dddd5`; the candidate imports those two files
from PR51 `7b4c75bdbd0631289ee90e858b5cfd530258ee23`. The complete production
compile inventory is closed and separately hashed. A new 37-file runtime witness
includes both loaders. Historical live witnesses require the unchanged loader
bytes; old retained witness inventories and hashes are not relabeled.

## Native gate

The existing Windows image workflow obtains the same original, source-validated
reload, locomotion, walk, ADS, directional and jump companions as the existing
sampling workflow. It excludes private weapon inputs. Both fresh builds compile
the identical `authored_loader_contract` example, plus the unchanged 21-image
renderer contract and mixed line/text fixture. Runtime source, compiler context,
shared assets, every earlier output, and the fresh executables are rechecked
through final acceptance. No downloaded executable is run.

The companion-backed example contains 22 deterministic cases:

- Ready, walk, ADS entry and tactical reload at 0%, 50%, 90%, then 0% of the
  declared clip duration. Each group reuses the same loaded mutable model and
  calls its production `load` and `draw` route.
- `load_manifest`, then idle `Simulation::update` and `committed_step`, with draws
  at fixed steps 0, 12 and 24. This covers the idle manifest/controller route,
  not a complete gameplay action replay. The existing informational WIP notice
  for missing unrelated action clips is retained and must stay unchanged; actual
  loader/controller errors still fail the gate.
- Original rigid parts at alpha 0.5, 0.25 and 0.5 through the production authored
  draw route, with a fixed nonuniform scale and rotation for normal lighting.

Lighting, root transforms, clip times and case order are fixed. The baseline
preparation computes one overview camera from all baseline index-expanded world
corners with a fixed viewing direction. Both native variants consume its exact
16 float-bit words. Preparation and the baseline native run must repeat the same
commands. This is a diagnostic overview, not acceptance of gameplay framing or
an exception to the existing authored source-visibility/ADS gates.

Every ordered mesh command binds its model matrix bits, blend, texture dimensions,
sampler and RGBA hash, unchanged index count and index-expanded 40-byte vertices.
The raw expanded-corner files are retained and independently hashed per command.
Equality covers exact position, UV, normal and color bits in triangle order;
resource allocation IDs are deliberately excluded. Stored vertex counts may only
shrink, and the actual drawn total must shrink. A separate source-record oracle
counts old source-index uniqueness and complete vertex-record uniqueness within
each unchanged 4,998-index chunk and material/actor partition. At least one real
source duplicate must exist; a no-op fixture cannot claim a reduction.

All 22 native images require exact 960×540 RGBA output, opaque display alpha,
at least 100 pixels different from the fixed clear color, and at least eight
colors. The original and deduplicated images must have byte-identical decoded
RGBA and foreground counts. The unchanged 21-image validators and four mixed
controls must also pass. The directory-bearing inner ZIP retains empty negative
fixtures for replay after artifact download. Three additional separately bound ZIPs
retain the camera-preparation, baseline and candidate raw corners/images, so one
large combined packet is not the only retrieval route. A compact reports/image
artifact includes the smaller original-control ZIP independently; it does not
replace raw-corner replay. Actual packet sizes are not known before the native
run; separate packets do not guarantee each is below a retrieval-size limit.

## Execution and evidence

After the existing companion materialization succeeds, the bounded command is:

```
python tools/run_authored_loader_pair.py --root . \
  --output evidence/cpu-image-native --build-timeout 1200 --process-timeout 600
```

The workflow first writes its original `package_game.py materialize
--include-walk --include-ads --include-directional --include-jump
--require-generated` receipt to that output directory. The native runner requires
Windows, the actual CI source commit, and direct Rust 1.99.0 MSVC binaries. All
builds use the same explicit opt-level-2/no-audio/wgpu configuration. Failures
retain their receipts and do not produce a passing summary.

The matched sampling workflow uses the separate named `compare-loaders` mode.
Its stationary authored scene, Record and WPR timing windows, physical 1080p,
release profile and ABBA order remain common. Any timing conclusion requires
its own raw source/session/trace review and the native loader correctness gate.
The image fixtures themselves are not performance measurements. WARP results do
not establish RTX3080Ti performance or the requested 60 FPS floor.
