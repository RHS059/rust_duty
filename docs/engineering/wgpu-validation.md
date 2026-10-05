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
| 0.3 | Neutral facade and legacy implementation integrated. Native legacy equivalence and final joint contract freeze pending |
| 0.4 | Accepted CPU boundary: input mapping and existing intent/control contracts pass |
| 1.1 | Window/event/fixed-clock integration implemented; native fullscreen, resize, cursor and quit exercise pending |
| 1.2 | Accepted CPU boundary: tap/repeat/focus-edge contracts pass; real focus interaction remains in manual checklist |
| 1.3 | Accepted CPU boundary: optional audio and same triggers; silent build passes; audible hardware check pending |
| 1.4 | Native text/2D/UI routes integrated; both-backend visual validation pending |
| 2.1 | Backend/surface policy and logging implemented; genuine Windows DX12/WARP run pending |
| 2.2 | Vertex/upload/blend pipeline and CPU layout tests pass; DX12 asymmetric fixture pending |
| 2.3 | Ordered target capture/readback implemented; DX12 orientation and 960x540 game capture pending |
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
