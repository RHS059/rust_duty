# VECTOR RANGE

An original, standalone Rust movement and gunplay laboratory for `rust_duty`.
One fictional **Kestrel-30** automatic rifle. One procedural UV-grid test range.
No commercial game installation, code, models, textures, animations, or recordings.

The goal is a responsive late-2000s military-FPS feel. Movement starts from
publicly documented reimplementation values; the rifle profile is newly authored.
**Retail MW2 fidelity is unverified. This is not a claim of indistinguishability.**

![Native Linux runtime capture](docs/screenshots/range.png)

## Play

Install stable Rust from [rustup.rs](https://rustup.rs/), then in this directory:

```sh
cargo run --locked --release
```

Windows: use the default **x86_64-pc-windows-msvc** Rust toolchain and Microsoft's
C++ Build Tools if rustup requests them. No game files or asset downloads are needed.
GitHub Actions builds Windows and Linux executables for the PR; download the matching
artifact from the completed **Rust prototype checks and playable builds** run.
An executable build is not a substitute for a Windows gameplay test.

Linux needs an X11 display, OpenGL, and ALSA development files for building audio.
On Debian/Ubuntu: `sudo apt-get install build-essential libasound2-dev libx11-dev libxi-dev libgl1-mesa-dev`.
For a silent build without ALSA: `cargo run --locked --release --no-default-features`.
macOS uses Xcode command-line tools; not runtime-tested here.

Click or press Enter to start. Escape pauses and releases the mouse. All gameplay
runs offline; there are no network calls, accounts, multiplayer, game-file readers,
or anti-cheat interactions.

| Control | Action |
| --- | --- |
| WASD / mouse | Move / look |
| Left mouse / right mouse | Automatic fire / hold ADS |
| Left Shift | Hold sprint |
| Left Ctrl or C / Z | Hold crouch / hold prone |
| Space | Jump; in a lower stance, request standing first |
| R | Reload |
| Escape / Enter or click | Pause / resume |
| F1 / F2 | Telemetry overlay / reset range and inventory |
| `[` / `]` | Lower / raise mouse sensitivity |
| `-` / `=` | Lower / raise horizontal hip FOV |
| F5 / F6 | Save / reload `settings.cfg` |
| F8 | Start/stop local `telemetry.csv` recording; starting overwrites the old file |
| M / F11 / F10 | Mute / fullscreen / quit |

The first resume click does not fire. After a focus-switch keyboard shortcut or
frame hitch longer than 250 ms, the prototype pauses instead of replaying stale
shots. Escape remains the explicit pause control; see the focus-detection limit below.

## What's implemented

- Deterministic 120 Hz simulation, frame-rate-independent movement and weapon timers
- Acceleration, friction, directional speeds, limited air steering, jump/landing,
  four-second sprint budget, exhaustion latch, crouch/prone clearance, eased camera height
- Original AABB collision and analytic wedge fixtures at 30, 45 and 50 degrees
- Accumulated 90 ms fire schedule, independent recoil/spread random streams,
  uniform-solid-angle spread, ADS in/out, hip bloom, separate camera and gun kick
- Tactical/empty reload credit and ready milestones, safe tactical sprint cancellation,
  sprint-to-fire gate, ammo conservation, eye/muzzle obstruction checks
- Procedural rifle, primitive targets, UV checks, meter floor grid, colored lanes,
  step thresholds, clearance tunnels, dispersion board, hit feedback
- Original in-memory synthesized shot, hit, footstep, and reload sounds
- Live settings and local CSV telemetry; no telemetry is transmitted

## Verify

```sh
cargo fmt --all -- --check
cargo clippy --locked --all-targets -- -D warnings
cargo test --locked
cargo run --locked --example measure
cargo build --locked --release
```

`cargo run --release -- --capture` renders a native frame to `capture.png` and exits.
`--demo` holds aim/fire for graphical diagnostics. `--capture-ads` and
`--capture-fixtures` select additional deterministic camera views. These modes
require a graphical display. Unit/integration tests do not.

## Tuning and architecture

`src/sim.rs` owns gameplay; `src/settings.rs` owns validated, human-editable tuning;
`src/main.rs` owns input/presentation; `src/sound.rs` synthesizes audio without files.
The renderer is [Macroquad](https://macroquad.rs/), pinned in Cargo.toml and Cargo.lock.
One reference unit is **0.0254 m by authored convention**. FOV is horizontal and
converted to the renderer's vertical-radian convention.

See [tuning](docs/TUNING.md), [provenance](docs/PROVENANCE.md), and
[verification](docs/VERIFICATION.md). This is a source-informed, independently
written implementation, not a strict legal clean-room certification.

## Deliberate limits

Single-player keyboard/mouse only. No networking, controller/aim assist, mantle,
ladders, penetration, destruction, AI combat, attachments, or retail assets.
Collision supports axis-aligned boxes and the authored wedge fixtures, not arbitrary
mesh geometry. Presentation is diagnostic primitive art. The native engine does not
expose a universal focus callback to this application: Alt/Super shortcuts and long
hitches pause safely, but every OS focus-change path is not covered. Always press
Escape before switching apps. Retail comparison and blinded feel testing remain open.
