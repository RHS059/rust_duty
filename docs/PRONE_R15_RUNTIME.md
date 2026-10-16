# Paired prone r15 integration candidate

This extends the paired-camera runtime from PR #63 onto main
`c04706de2e559a08532be78e4bd37c989f62938e`. It preserves the existing renderer,
city, UI, lighting, fixed-clock and scoped-CI changes. No private geometry,
BLEND, FBX, VRA/VRS/VRM, evaluated pose array or private oracle is included.
The ordinary manifest remains unchanged; binding requires a complete private
pair. Do not merge both the historical PR63 scaffold and this replacement
implementation independently.

## Frozen approved source

- Source SHA-256: `cbed3051bb8c4bbdb78f72a49a7a51bd585db33636ddc5312dde38b05a2a86c4`
- Rig Action: `aella_prone_crawl_enter_r15_roll_v1`
- Rig fingerprint: `93ffbed2bd91d33bb2d6e1788ce3c3d95f915c228b8ce7f3c17af05b265c9640`
- Camera Action: `aella_prone_crawl_enter_camera_r9_viewray_v3`
- Camera fingerprint: `6872ef8f4301690dfd340ec9479f4a533fba743f1dc23b6a3691cd85c9e08844`
- Source clock: frames 1–69, 60 fps. Reference decoded frames 2241–2309.
- Elara reviewed this exact motion: 82/PASS, 2026-10-16 02:00 UTC.

Bind the rig and camera explicitly after the canonical reset Action. Saved
default bindings are not the pairing contract. Art review does not establish
export, runtime or gameplay correctness.

## Dense export and conversion

The old FBX contains 69 native samples. The separate dense FBX uses a 1/64-frame
bake, simplification zero, one scene take with the exact rig Action name, and
retains all 148 bones, three skins, three rigid actors and the camera.

- Dense FBX SHA-256: `f025876ede4ec28098337ea645da679765678d75d94fdcf51965a92eba4e4a02`
- Actual runtime VRA SHA-256: `53e360817acd58e4f826ae0be7c316a55f699a5c46d211dbbaf6256e779bec86`
- Camera sidecar SHA-256: `9b91331d264444fec48813a769f67d02273ba96d8d922d49e50f7497e6ee22f9`
- Pair receipt SHA-256: `21b40755782e8731d25525af432d3db54820b0100caa0e0debb2f0f3a4c22da1`

Fresh FBX reimport passed 1,944 independently evaluated times, including the
1/128 and 1/512-frame neighborhoods around the roll. It checked 19,894,896 skin
vertex samples. Maximum world-space skin error was 6.019 micrometres; maximum
camera-relative skin error was 34.036 micrometres. Matrix component residuals
have separate units and must not be reported as distances.

The conversion samples 4,353 keys at 3,840 Hz. Blender reimport `anim_offset=0`
and importer `imported_frame_offset=1` are distinct conventions. The latter
maps source native index zero to imported scene frame one. Both are recorded.

For each evaluated global transform the importer removes exactly
`inverse(C(t) * inverse(C0))` before the Blender-to-glTF basis conversion, then
restores the canonical initial skeleton/skin rest worlds. The game renders
this camera-local pair with one world camera orientation and one replacement
stance-height track. It must not add a second stance descent or camera delta.

`tools/sample_prone_r15_camera.py` reads the frozen scene without authoring or
saving it. `tools/sample_prone_r15_rigid.py` produces a private, hash-pinned
rigid geometry witness and verifies constant evaluated local geometry at all
1,944 source times. These script sources contain no private geometry.

## Runtime ownership and transitions

Use the explicit manifest policy `paired_r15_wip`, exact clip name and all
three companion references: `prone_entry.asset`, `.camera`, `.receipt`.
Admission verifies byte hashes, exact source/Action identities, the native
clock and complete sample grid. Legacy r6 has its own unchanged bounded
schema; relabeling its 545 keys as r15 fails.

The accepted crouch-to-prone simulation boundary owns source frame one.
Frame 69 is held while the paired state remains valid. Incoming motion is not
retimed or crossfaded. The camera's protected entry frames and authored depth
overshoot are retained. Gameplay collision, aim, ammunition and stance rules
remain independent of cosmetic camera orientation.

Normal cancellation freezes the last presented source pose and starts one
committed configurable return clock (default 0.20 seconds). Smoothstep drives
the weapon, camera rotation and procedural root/cant return together, toward
the current live locomotion/ADS/reload presentation. Reload actor opacity can
be fractional. Pause does not advance or restart the return. Death, reset,
level replacement and renderer failure clear the pair immediately.

`gameplay-prone` is an input-only capture: ordinary crouch/prone requests,
complete entry and hold, stance exit, a second entry, ADS interruption and
live movement. It does not inject velocity, pose, animation time or physics
results. Per-frame `.prone.json` records validated binding identity, committed
source clock, outgoing clock, actual camera basis/eye, route, procedural
weight and gameplay state. `--capture-native-window` captures the actual
world window; the existing reference-viewport path remains available.

## Verification boundaries

Source-only synthetic tests exercise parsing, rejection, transitions and
live target contact. Actual Rust CPU parity must independently compare all
1,944 private source samples through `sample_viewmodel_clip` and
`sample_prone_camera`, using fixed frame-one geometry correspondence. No
Python animation substitute or per-frame remapping is acceptable.

The separate Linux GL/llvmpipe gameplay capture establishes only that named
backend and exact pinned private pack. Windows DX12 validation and the
private build delivery route remain required before a shipped-runtime claim.
Source art approval and export success do not replace either check.
