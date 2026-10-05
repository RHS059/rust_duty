# 0002: Neutral draw recording and the Windows DX12 migration

Status: component boundaries agreed; production integration and native acceptance
are in progress. This is not approval to cut over or remove the legacy renderer.

Baseline: `e7a36bcaa26e0babe4da79b3a54b3785e56bf943` after PR 43.
Integration is tracked in [draft PR 44](https://github.com/RHS059/rust_duty/pull/44).

## Goal and current scope

Replace the presentation/platform implementation without changing simulation,
120 Hz fixed stepping, input latches, authored motion, CPU skinning or lighting.
The current acceptance target is Windows Direct3D 12. Vulkan validation was
explicitly removed from the requested scope; previous Linux software-renderer
captures are historical evidence, not a required gate or Windows evidence.

Default features retain audio and legacy-macroquad until the human Windows
playtest gate. The optional `wgpu-runtime` feature builds the new window/backend.
A follow-up release, not an early cleanup, owns eventual legacy removal.

## Pinned choices

- glam 0.27.0: same math types previously re-exported by macroquad.
- macroquad 0.4.14: retained compatibility backend.
- wgpu 30.0.1 and winit 0.30.13: GPU and desktop event loop.
- fontdue 0.9.4: existing rasterization/metrics, avoiding a second layout system.
- image 0.24.9 with PNG: fallible capture output.
- pollster 0.4.0: bounded initialization at the renderer/window boundary.
- rodio 0.22.2, playback + hound, optional: existing synthesized sound triggers.

The ProggyClean font keeps its license beside its bytes. Text is rasterized at
physical pixel sizes; metrics used for native UI layout remain logical pixels.
Glyphon was considered, but its shaping/atlas machinery is unnecessary for the
first port's existing text. No browser or WebView is introduced.

## Shared draw contract

The frame-local facade records ordered, backend-neutral CPU snapshots. Meshes
contain position, UV, RGBA8 and normal fields. GPU packing is explicit to avoid
reading padding in aligned math types. CPU vertex lighting is unchanged; WGSL
only multiplies texture and vertex color.

Camera matrices retain right-handed OpenGL clip depth. The wgpu backend alone
remaps -1..1 depth to 0..1. Offscreen sampling and PNG data use top-left origin;
there is no call-site render-target flip. Model transforms are copied into each
draw rather than left in mutable GPU state.

Texture source, extent and sampler are immutable after submission. A changed
resource needs a new identity; both backends reject conflicting reuse.

Main-window draw lists use physical extents. Screen-space facade coordinates and
font sizes are scaled once from logical pixels. Explicit render targets use their
own pixels, including the fixed 960x540 reference target. Two-dimensional draws
use a scoped pixel-space camera and restore the previous camera/target/depth.

Captures are ordered checkpoints, including world-only captures before later
passes. Completion and file errors propagate before a requested final exit.
Backend/adapter metadata belongs in the primary `.png.json`; deterministic
`.gameplay.json` and `.time.json` remain unchanged in schema and values.

## Frame lifecycle and input

Surface acquisition precedes the application future and input snapshot advance.
Timeout, occlusion and minimization return `FrameStart::Skip`; queued input is
retained and simulation is not polled. Lost/outdated surfaces are recovered once
inside the renderer. A ready surface token is consumed exactly once by submit.

The existing asynchronous app yields through platform next_frame. The legacy
path finishes its recorder before the native frame await and begins a new one
afterward. Both paths finish pending draws and readbacks when the app completes.
Rendering never calls Simulation::update or owns gameplay time.

## DX12 selection and validation

`Backends::PRIMARY` alone does not guarantee DX12 on Windows: pinned wgpu-core
initializes Vulkan before DX12 and ranks adapters by device type. Windows Auto
therefore attempts DX12 first, then PRIMARY only if initialization fails. An
explicit `--renderer=dx12` is strict and never changes API silently. Actual
selection and adapter are logged.

The agreed software-adapter CLI is `--force-fallback-adapter`. Windows validation
uses `--renderer=dx12 --force-fallback-adapter --no-update` with capture arguments.
CPU policy tests do not establish WARP or Windows execution. M3 needs genuine
Windows DX12 evidence; M4 needs the human owner's Windows playtest. Performance
observations require a named real machine, scene and measured baseline.

## Known legacy difference

Pinned miniquad 0.4.8 couples OpenGL depth testing to depth_write. The existing
additive muzzle material thus disables both in practice. The compatibility
backend preserves that behavior. wgpu depth-tests additive fragments without
writing depth and preserves destination alpha. This deliberate difference needs
capture review; additive occlusion parity is not claimed. Ordinary alpha meshes
retain their original depth writes.

## CSS-style native UI

The requested styling extension interprets a documented CSS-like subset into a
typed native theme, not a browser engine. Stable widget selectors, explicit
unsupported-rule errors and file/line/column diagnostics are required. Reloading
must be atomic and retain the last valid theme on error.

Initial styling focuses on paint/font/border/opacity properties. Any later layout
property must feed both drawing and hit testing. Static world/viewmodel material
colors remain separate from HUD/CSS colors, preserving the existing 3D palette.
The platform/UI owner defines the final supported selector/property list and
parser pin; no unsupported CSS compatibility is promised.

## Acceptance boundaries

Source restoration, compilation, unit tests, real native execution and human
visual approval are separate evidence. The recovered source has fresh component
checks; external harnesses do not replace production Cargo/app wiring checks.
No tests are skipped or weakened to satisfy a gate. Authored assets, gameplay,
the updater and release channel are outside this migration.
