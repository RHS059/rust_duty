# Audio-preserving Windows game continuation v3

This source-only successor preserves the current game's normal audio feature in
its same-candidate Windows build and capture continuation. The shared game
feature list is exactly `audio,legacy-macroquad,wgpu-runtime`. The current measured
`Cargo.toml` defaults are `audio,legacy-macroquad`; `audio` enables rodio 0.22.2
with playback and hound. The game still uses `--no-default-features` with that
explicit complete feature list. Its metadata query, build command and build
receipt consume the same constant. Root metadata and all actual root compiler
artifacts must carry exactly those features. The base sampler keeps its exact original
`--no-default-features` command without any feature option; its actual root
compiler artifacts must carry an empty feature list.

The v3 package is derived from the frozen v1 game continuation. Only the shared
feature constant, narrow root metadata/compiler feature assertions, versioned
preflight export prefix and focused tests change, plus this documentation. The workflow routes game preflight/source tests
to v3 and its exact package/bootstrap pins. Source-inventory v2 and its actual
measurement steps remain byte-for-byte unchanged. Neither frozen v1 nor v2 is
modified. No native/game admission is supplied by this source-only successor.

The actual dd1d2cb4bae6e0b2d2509edfc8e8c301184cf4f4 source specification has
957 rows and 265961235 bytes, including one immutable Jump authoring input. The
selected game source is unchanged by this publication: every new package/test/
documentation file is under `tools/onehand_windows/`, and the only other changed
path is `.github/workflows/onehand-windows-proof.yml`. Both are excluded by the
unchanged `game_source.selected` rule. The independent source acceptance and
final native/game admission are separate review steps.

## Dependency and provenance contract

The measured Cargo.lock already contains rodio and its complete locked
transitive graph, including cpal, hound, dasp_sample and Windows support crates.
The existing build runs Cargo's full locked vendor command with the updater
manifest synchronized into a fresh vendor tree. Cargo documents this as
vendoring all remote dependencies:
https://doc.rust-lang.org/cargo/commands/cargo-vendor.html

This is a static locked-graph and mechanism check. No actual Windows vendor
inventory or audio-enabled compilation is claimed here. The Windows run must
still inventory every vendor file, resolve metadata offline with the game audio
feature, record the actual compiler/linker/SDK identities and processes, and
pass the unchanged compiler-artifact, dep-info membership and OUT_DIR producer
checks. Nothing is removed from the source or vendor closure. There are no fake
inventory rows, package substitutions, relaxed bounds or numerical changes.

All same-run candidate bindings, complete 4,240-sample/67-chunk and focus gates,
frozen motion, existing generation commands, 30/60 Hz DX12 capture checks and
capture-before-delivery ordering remain unchanged. A source-test pass does not
establish audible output or a playable artifact. Actual same-job compilation,
full proof, capture and delivery remain required before completion.
