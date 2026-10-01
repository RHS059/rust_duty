# Blender-first viewmodel authoring

The editable `.blend` is the source of truth. Author neutral poses and independent
Actions/NLA clips in Blender, then bake evaluated transforms into runtime data.
The exporter does not import Rust pose snapshots, alter the master file, or ask the
runtime to reconstruct Blender's IK solution.

## Authoring contract

- Use metres, Blender **+Z up and −Y forward**
- Keep an Arms rig and a Weapon rig together in one master file
- Preserve the skin's bone names, hierarchy, vertex weights and inverse binds
- Put each animation in independently selectable Actions/NLA tracks; explicitly
  name the participating track on every animated object in the export registry
- Independent left/right hand IK influence is an authoring control, when present
  in the source. Its evaluated bone motion is baked; constraints are not exported
  as a second runtime solver
- Treat the loaded neutral pose as an intentional pose, distinct from bind/rest
- Source-only controls may remain unselected while still participating in the
  dependency graph. Runtime objects are selected explicitly
- Every clip starts from restored source defaults. A previously sampled clip must
  not leave custom-property, object or bone values behind

The current clean neutral handoff contains no animation clips or constraints.
The synthetic fixture below demonstrates constraint baking without changing that
file or introducing unwanted rig dependencies into it.

Each clip must export the same immutable geometry and inverse binds as the
neutral/rest export. The compiler rejects a clip that changes those bindings.
If keying an armature object's initial transform changes Blender's exported bind
matrices, keep that object bind transform fixed and author the animation on a root
bone instead; do not fit or patch a different bind in the runtime.

## Outputs and coordinates

`export_viewmodel.py` writes three matching sibling files:

- `.vrs`: existing VRSKIN02 deform geometry, skeleton and eight-influence skin
- `.vrm`: existing VRMESH01 rigid geometry baked at its rest transform
- `.vra`: bounded VRANIM01 independent animation clips and rigid-part bindings

These outputs retain standard glTF +Y-up coordinates. The whole viewmodel gets
one runtime 180-degree Y rotation. Therefore Blender `(x,y,z)` becomes game
`(-x,z,y)`: Blender −Y forward becomes game −Z forward, and Blender +Z up becomes
game +Y up. This is a proper rotation, with no reflection. Do not also rotate
individual vertices, bind matrices or animation tracks.

For skinning, the runtime reconstructs globals from exported joint-local TRS and
uses `model_root * joint_global * inverse_bind`. Rigid geometry has already been
rest-global baked, so each part uses
`model_root * actor_global * inverse_rest_global`.

The compiler supports an explicitly declared rigid weapon armature only when
its geometry is fully weighted to one joint. More general extra deform skins
must fail clearly rather than silently lose deformation.

## Source registry and export

An example registry for two NLA clips:

```json
{
  "schema": "rust-duty-viewmodel-export/v1",
  "armature": "Arms",
  "rigid_armatures": ["Weapon"],
  "export_objects": ["Arms", "ArmMesh", "Weapon", "GunMesh"],
  "clips": [
    {"name":"neutral", "frame_start":1, "frame_end":1, "loop":false, "tracks":{}},
    {"name":"reload", "frame_start":1, "frame_end":121, "loop":false,
     "tracks":{"Arms":["reload"], "Weapon":["reload"]}},
    {"name":"idle", "frame_start":1, "frame_end":61, "loop":true,
     "tracks":{"Arms":["idle"], "Weapon":["idle"]}}
  ]
}
```

The names and ranges are illustrative, not authored gameplay animations.
Choose the scene FPS and clip ranges deliberately. Loop seams require matching
source endpoints; the player does not invent a return path.

```sh
blender -b /private/master.blend --python-exit-code 1 \
  --python tools/export_viewmodel.py -- \
  --registry /private/clips.json --output-dir /private/export --name first-person
```

Use `--base-color-only` only when intentionally retaining the existing renderer's
base-color material subset; omitted material maps are reported. Unsupported
features must fail explicitly. `--single-sided-materials` is a separate explicit
compatibility choice for inputs containing double-sided materials; it reports
each affected material and does not modify the source `.blend`. Existing outputs
require `--force`. Temporary
sampled GLBs and the export manifest are private derived assets too.

## Opt-in game playback

```sh
cargo run --locked --no-default-features -- \
  --viewmodel-asset=/private/export/first-person.vra \
  --viewmodel-clip=neutral
```

The default clip is `neutral`. Use `--viewmodel-clip=NAME` to select an independent
exported clip and optional `--viewmodel-time=SECONDS` to hold an exact comparison
pose. Otherwise the simulation clock advances the selected clip; pause/reset
therefore have the existing clock semantics. A nonlooping clip holds its endpoint.
This initial opt-in path is a clip playback/verification path, not a completed
mapping of new authored clips onto every gameplay action. No gameplay clips are
generated by this change.

With `--viewmodel-asset`, the renderer loads only the matching three authored files,
bypasses the old arm/weapon procedural pose route, and blocks on invalid assets
instead of silently falling back. Without it, existing gameplay presentation is
unchanged. The adapter performs generic skinning and draws explicit rigid-part
bindings; it has no grip coordinates, arm naming assumptions or IK solver.

## Runtime data and safety

VRANIM01 has a 24-byte little-endian header: magic `VRANIM01`, version 1, payload
length, payload CRC32, reserved zero. The payload contains whole-file companion
CRCs, named bone-parent bindings, named rigid-primitive bindings/inverse rest
matrices, then named clips with per-frame time, bone-local TRS, actor-global TRS
and STEP visibility. Quaternions use XYZW order.

The decoder checks lengths and allocation budgets before allocating frame data;
it rejects malformed UTF-8, duplicate names/bindings, invalid parents/cycles,
nonfinite values, nonunit quaternions, nonpositive scales, invalid timestamps,
trailing bytes and companion mismatches. CRC is an accidental-corruption check,
not authentication or encryption.

The player uses linear translation/scale interpolation and shortest-arc quaternion
slerp. Nonlooping clips clamp; looping clips wrap. `sample_clamped` preserves a
loop's final authored endpoint for comparison. Generic local-TRS pose blending
is available, but does not promise exact constraint contacts between different
clips. Gameplay timing and ammunition remain simulation-owned.

## Original synthetic proof

```sh
blender -b --factory-startup --python-exit-code 1 \
  --python tools/make_viewmodel_fixture.py -- --out /tmp/viewmodel-fixture
blender -b /tmp/viewmodel-fixture/fixture.blend --python-exit-code 1 \
  --python tools/export_viewmodel.py -- \
  --registry /tmp/viewmodel-fixture/fixture-registry.json \
  --output-dir /tmp/viewmodel-fixture/export --name fixture
cargo build --locked --no-default-features --example sample_viewmodel_clip
python tools/verify_viewmodel_roundtrip.py \
  /tmp/viewmodel-fixture/blender-oracle.json \
  /tmp/viewmodel-fixture/export/fixture.vra \
  --sampler target/debug/examples/sample_viewmodel_clip \
  --report /tmp/viewmodel-fixture/roundtrip.json
```

Repeat with `make_viewmodel_fixture.py --rigid-skin-weapon` in a separate output
directory to cover the weapon's single-joint skin path.

The fixture contains only original synthetic triangles and rigging. Its Blender
oracle measures evaluated joint matrices and actual deformed vertices. Neutral,
left-release and right-release clips exercise each independent hand's 0, 0.5 and
1 influence while the other hand stays attached. Sampled-frame errors and
between-frame interpolation errors are measured separately, with explicit
thresholds. The proof checks every synthetic vertex and the runtime axis change.
This does not establish anatomical quality, gameplay animation quality, or
commercial-game reference fidelity.

Private masters, geometry, textures, pose oracles, sampled GLBs and derived
packages must stay outside public commits. Public CI uses original fixtures only.

## Verification checkpoint

On Blender 4.3.2, both original fixture variants passed 27 sampled-frame and
10 between-frame comparisons across the three clips. Maximum sampled-frame skin
position error was 6.13e-7 m and joint-matrix component error was 1.07e-6. The
whole-model axis check was 3.57e-7 m. The intentionally fast 60 Hz fixture differed
from continuously reevaluated Blender IK by up to 4.70 mm between baked samples;
this finite-rate approximation is reported separately and is not bit-identical
continuous IK. Increase authoring/bake sampling density where that error matters.

A separate private neutral validation checked every joint and source vertex
against Blender's evaluated state, without changing or redistributing its master.
It required explicit material compatibility conversion. Those private oracles and
compiled assets are not public fixtures.

The optional game adapter compiled successfully. Native GPU rendering was not
verified in this execution environment: no X display was available and a capture
launch returned `XOpenDisplay() failed`. CPU pose/skin parity does not replace that
remaining native render check.

Final shell checks: 463 Rust tests passed with audio disabled (one explicitly
private test ignored), formatting and all-target Clippy passed, and 79 Python
tests passed with one optional Blender test skipped (80 total in that aggregate). The
separate Blender-enabled viewmodel suite passed all 16 tests. Default audio-linked
tests could not link because this environment lacks `libasound`; that is separate
from the successful no-audio build and pose checks.

The isolated source-only draft-PR patch was additionally tested against its
remote base independently of unrelated working changes: 407 Rust tests passed
with audio disabled (one private test ignored), and all 80 Python tests passed
with Blender integration enabled. Formatting and strict all-target Clippy passed.
