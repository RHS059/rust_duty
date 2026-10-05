# wgpu migration validation ledger

This ledger separates implementation from acceptance. Draft PR 44 is not a
cutover, release, or human visual approval. Windows DX12 is the requested runtime
target; Linux Vulkan validation (original WP4.1) was removed from scope.

## Reproducible integrated checkpoint

Local source commit `553194f851718067175f25270cdd1e591d09143e`, tree
`5162cf66b49c64e8bf15e25b36e458ecfd196ab2`, tested 2026-10-05 on Linux with
Rust/Cargo 1.99.0, one build job:

| Command | Result |
| --- | --- |
| `cargo fmt --all -- --check` | Passed |
| `cargo check --locked --all-targets --no-default-features --features wgpu-runtime` | Passed |
| `cargo test --locked --no-default-features --features wgpu-runtime` | 762 passed, 2 existing ignored |
| `cargo test --locked` | 759 passed, 2 existing ignored |
| `cargo test --locked --no-default-features` | 693 passed, 2 existing ignored |
| `cargo clippy --locked --all-targets --no-default-features --features wgpu-runtime -- -D warnings` | Passed |
| `cargo clippy --locked --all-targets -- -D warnings` | Passed |
| `cargo clippy --locked --all-targets --no-default-features -- -D warnings` | Passed |
| Python `test_dx12_smoke.py` | 27 passed, synthetic process/evidence failures |
| Python `test_render_capture.py` | 25 passed, PNG/orientation validation |
| Python `test_capture_telemetry.py` | 15 passed, finite/exact telemetry validation |

Python commands use `python3 -m unittest discover -s tools -p <filename> -v`.
These are production Cargo targets, not the earlier recovery harness. Python
synthetic checks do not establish that the game or renderer ran on DX12.

A source audit against main `e7a36bcaa26e0babe4da79b3a54b3785e56bf943` found
no gameplay/animation logic regression: fixed-clock and latch semantics remain;
math-only files change imports; authored skin/root/actor math remains; assets and
fixtures are unchanged. Existing assertions were not weakened. Native input,
visuals and real hardware remain separate proof boundaries.

## Work-package acceptance

| WP | Implementation / remaining acceptance |
| --- | --- |
| 0.1 | Accepted CPU boundary: mechanical glam imports, identical math version, tests/clippy pass |
| 0.2 | Accepted extraction component: Hal message234 reports all508 native legacy capture files baseline-identical for extraction233/platform235. Main is now138lines. This historical extraction evidence does not certify the subsequent renderer/UI integration |
| 0.3 | Neutral facade and legacy implementation integrated. Both owners confirmed v1 interface at2887729; native legacy equivalence pending |
| 0.4 | Accepted CPU boundary: input mapping and existing intent/control contracts pass |
| 1.1 | Window/event/fixed-clock integration implemented; native fullscreen, resize, cursor and quit exercise pending |
| 1.2 | Accepted CPU boundary: tap/repeat/focus-edge contracts pass; real focus interaction remains in manual checklist |
| 1.3 | Accepted CPU boundary: optional audio and same triggers; silent build passes; audible hardware check pending |
| 1.4 | Native text/2D/UI routes integrated; both-backend visual validation pending |
| 2.1 | Accepted DX12 scope: actual Windows WARP game launch/present/capture and adapter/FXC logs pass; native interaction remains WP1.1/M4 |
| 2.2 | Accepted: CPU layout/upload contracts and actual DX12 non-empty asymmetric orientation/blend fixture pass |
| 2.3 | Accepted: actual DX12 960x540 reference captures, asymmetric orientation, ordered readback and padded rows pass |
| 2.4 | World lines/wires/spheres migrated; native visibility/depth review pending |
| 2.5 | Text atlas and DPI fixtures implemented; actual 100%/200% legibility review pending |
| 3.1 | World pass migrated; CPU contracts pass; native breakage/telemetry evidence pending |
| 3.2 | Viewmodel adapters migrated; existing contact/IK tests pass; unified emitted hand/weapon root regression passes in the next correction; ADS landmarks and replay captures pending |
| 3.3 | Effects/additive state migrated; CPU blend tests pass; native effect/state review pending |
| 3.4 | HUD/menu/updater/ammo CSS-style UI integrated; manual navigation/interrupted flow checklist pending |
| 4.1 | Removed from requested scope: Linux Vulkan validation |
| 4.2 | Accepted: genuine Windows DX12 WARP game smoke passed on961a5aa; see native evidence below |
| 4.3 | Capture validators tested; real DX12 output and complete capture suite pending |
| 4.4 | Pending user's real Windows GPU: machine, scene, frame-time baseline |
| 5.1 | Pending human Windows DX12 playtest and explicit cutover signoff |
| 5.2 | Deferred by plan to a follow-up release after fallback retention; do not remove legacy now |

## Subsequent corrections and mandatory gates

The next revision explicitly pins DX12 FXC, repairs large-font HUD notice bounds
and asynchronous updater warning styling, and extends rendered-root proof. Its
results must be recorded against its own source revision, not attributed to the
checkpoint above.

- M0: legacy-native equivalence and joint frozen contract, then review/merge.
- M1: genuine DX12 world/orientation/non-empty evidence (Vulkan requirement removed).
- M2: ADS/contact/replay/telemetry evidence plus human capture-set review.
- M3: complete required DX12 capture jobs green with actual adapter/compiler logs.
- M4: human hardware DX12 playtest, performance evidence, then cutover approval.

Named-target PNGs contain associated RGB/emission and coverage alpha; final
screen PNG alpha is opaque. The miniquad additive-depth coupling is a documented
legacy difference requiring visual review. Neither intentional difference waives
breakage checks. The detailed fixture contract is in [renderer-contract.md](renderer-contract.md).

## Correction checkpoint (parent 428cd2a)

The correction adds explicit FXC policy/logging, UI252 notice/warning fixes, and
one authored emitted hand/weapon shared-root CPU regression using original tiny
synthetic geometry. Fresh production checks on 2026-10-05 before this commit:
wgpu tests767 passed; default763 passed; silent693 passed. Each retained two
existing ignored tests. All three strict all-target clippy lanes and formatting
passed. The two UI findings were independently re-reviewed as fixed. These CPU
results still do not certify DX12 shader execution or native visuals.

## First genuine Windows DX12 smoke

Commit `961a5aac3e8edda714c2adfdfbf6c3162023623f`, GitHub Windows runner:
[run37329012293/job111827384735](https://github.com/RHS059/rust_duty/actions/runs/37329012293/job/111827384735)
passed actual game launch, capture and clean exit. The artifact is
[11353043620](https://github.com/RHS059/rust_duty/actions/runs/37329012293/artifacts/11353043620).

- Log: requested `dx12`, actual `Dx12`, adapter `Microsoft Basic Render Driver`.
- Additional actual initialization log: `renderer dx12_shader_compiler=Fxc`.
- 127 PNG frames at960x540, 381 JSON files including127 renderer sidecars.
- Non-empty images, finite/exact-field telemetry checks and exit0 passed.
- Executable SHA256: `ee4d63cd7e9abd2e2075db279a3071a5cdf321b49748e0c4057b01ad12afadf7`.
- Artifact ZIP SHA256: `be07ba0d19640bace1032a1396dfa97a2d9b25463c9e47d21210df3807a3a7f4`.

This is procedural weapon sway with a reference target. It completes WP4.2,
and provides a subset of device/frame/capture integration evidence. It does not
validate authored companions, ADS pixel landmarks, the asymmetric renderer
fixture, full-world/HUD presentation, actual hardware performance, M2 capture
approval, or M4 human playtesting. Orientation was not checked by this smoke.
The first attempt failed only an equivalent Windows short/long temporary-path
assertion; patch253 normalized the two expected paths without relaxing equality.

## Independent DX12 renderer contract

Commit `28877298ab8acd137b432a9f6df0880fb434a8be`, Windows WARP with explicit
FXC: [job111834490299](https://github.com/RHS059/rust_duty/actions/runs/37331078290/job/111834490299)
passed all19 captures, four expected error cases and post-error recovery.
[Artifact11354701220](https://github.com/RHS059/rust_duty/actions/runs/37331078290/artifacts/11354701220)
ZIP SHA256: `5f26c07489fb2b41e8f8fdd04945bf4fd03b7271c8f8e47a5d3a2b1d9c7418e9`.

All fixed color/depth/alpha probe regions achieved match_fraction1.0. Actual
checks cover asymmetric top-left orientation, width65 padded readback, ordered
red/green snapshots, independent target depth/reset, disabled depth, associated
alpha and zero-alpha emission, tint, clear/replacement encoding, and recovery.
The16/32px text images were inspected as legible `Ag` glyphs; raster dimensions
match1x/2x expectations. This is not native OS DPI-event or complete HUD proof.

The stricter game smoke on this same revision also passed127 frames/381 JSON
with the FXC guard. Neither result substitutes for the pending authored replay
suite, real hardware performance, or human M2/M4 gates. Nine original work
packages now have their scoped acceptance evidence; original WP4.1 is removed.

## Legacy baseline correction before authored acceptance

The2887729 legacy native-validation job passed its CPU/Python checks, then failed
at the first native jump capture: the GLSL ES100 associated target fragment
shader lacked a default float precision for its local `vec4`. The opaque
replacement variant had the same defect. All legacy fragment variants now
declare `precision mediump float;`, with a targeted source regression. Fresh
production tests pass default764/wgpu767/silent693, two existing ignored each,
and all three strict clippy lanes pass. This fixes the observed source cause;
only the subsequent native CI run can confirm legacy shader/render recovery.
The baseline dependency and original validator thresholds remain intact.

## Joint interface freeze

Both owners confirmed draw/facade/FrameHooks v1 at2887729 after reviewing actual
caller and backend code (Hal message263). Resource identity, one depth remap,
top-left origin, ordered capture, Ready/Skip input retention and final submission
semantics are agreed. This is an interface freeze, not visual or human approval.

## Legacy exit-lifetime correction

After the precision repair, e903b8 completed all403 jump PNG/sidecar groups but
exited139. Artifact11356680310 was inspected by Hal; the last frame's elapsed6.7s
matches the6.5s replay plus0.2s tail. Independent source reviews identified TLS
renderer destruction after Miniquad had destroyed GLX and unloaded libGL.
Cached RenderPass destructors then called stale GL deletion functions.

The correction explicitly takes the driver out of TLS, submits the final frame,
flushes, and drops resources inside the still-live Macroquad application future.
The main caller invokes shutdown instead of the final per-frame finish. Two CPU
regressions cover submit/flush/drop ordering, cleared state and error preservation.
Fresh tests: combined audio+legacy+wgpu807, default766, silent693; two existing
ignored each. Strict all-target clippy and formatting pass in all three modes.
Native exit recovery remains pending the next CI attempt; complete written
captures did not make the crashed process a passing baseline.

## Recovered native baseline and current integration (2026-10-05)

PR head `72663e2b18dda818c800dec96af1ce452dbdd4da`,
[run37339601251](https://github.com/RHS059/rust_duty/actions/runs/37339601251):
the complete legacy native-validation job111864565365 passed, confirming the
shader and resource-lifetime repairs in native execution. Windows aggregate
checks/build and both DX12 renderer-contract/game-smoke jobs also passed.
At17:24UTC, authored job111868451019 was still capturing/comparing; no authored
suite result, pixel landmark measurement or human approval is claimed.

Historical artifact provenance clarification: the first DX12 smoke used PR
head961a5aa but executed GitHub's merge revision
`f83aa69183ba9a3bb74931914c4772a3fe270181`; the19-case fixture used PR
head2887729 but executed merge revision
`27e526c761aa799153e96803050eb254824b28a9`. The latter two DX12 jobs passed,
while that attempt's separate legacy baseline failed as described above.

The next local integration adds the accepted CSS examples, byte-preserving
focus-module relocation, strict raw-sidecar binding, landmark review tooling,
and explicit named-target-to-main orientation coverage. Fresh production tests:
combined audio+legacy+wgpu811, default770, silent697; each retains the same two
existing ignored tests. All three strict all-target clippy lanes and formatting
pass. Renderer example CPU tests10, strict fixture validator45, authored
validator39, landmark tool38, package tests12 and release-delta tests8 pass.
These local results are distinct from the older remote native evidence.

The25067-byte focus implementation, including its ten tests, moved unchanged to
`platform/session_focus.rs`; old and new SHA256 are
`6b964c7ac72182cb8a99f6e9b1cbdb81c55e83d48a9943601dc734e76213e0fd`.
The former module only reexports its public types. Outside platform and the
legacy backend, direct Macroquad references are now confined to the main entry
point's legacy event-loop startup. This satisfies the mechanical routing audit;
real focus/DPI interaction remains a native human check.

The two additional orientation cases preserve the original19 checks. Their
21-case native execution is pending the next published revision. Landmark-tool
regressions cover evidence provenance, malformed inputs, per-axis uncertainty,
raw-target exclusion and safe report output; no real landmarks were invented.
