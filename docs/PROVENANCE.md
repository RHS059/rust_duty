> Intermediate source-only update: the supplied HK416 was verified locally, but its model binary and new screenshots are not in this commit. The game uses its procedural fallback until the separately authorized single asset upload finishes.

# Provenance and boundaries

This project contains newly authored Rust gameplay, collision, rendering, UI,
procedural shapes, test fixtures, tests, and synthesized audio. No code was copied
or translated from the two reference game reimplementations. No commercial-game
installation, executable, data table, map, model, texture, animation, sound, shader,
or font was acquired or loaded for this prototype.

## Source-informed observations

The implementation used an implementation-neutral behavioral report of public
repository facts. This is **source-informed research**, not a legal certification
of a strict clean-room process. Values in an experimental reimplementation are not
measurements of retail MW2. Shared ancestry between the references is not independent
corroboration. No retail playtest or extraction was performed.

Reference versions:

- [IW4L README](https://github.com/vladtrc/iw4L/blob/11514ea37d1e80d75bf2c1ba332bbd68fac5db4e/README.md)
- [IW4L movement defaults](https://github.com/vladtrc/iw4L/blob/11514ea37d1e80d75bf2c1ba332bbd68fac5db4e/crates/sim/src/step.rs#L1853-L1902)
- [IW4L initialization](https://github.com/vladtrc/iw4L/blob/11514ea37d1e80d75bf2c1ba332bbd68fac5db4e/crates/sim/src/world.rs#L3553-L3559)
- [IW4L stance values](https://github.com/vladtrc/iw4L/blob/11514ea37d1e80d75bf2c1ba332bbd68fac5db4e/crates/movement_iw4/src/stance.rs)
- [Mashup README](https://github.com/chasmlol/2010-rust-rewrite-mashup/blob/7842b9e70e9aac22ed176b655dd63302618ee023/README.md)

The reference projects' root licenses were inspected as Apache-2.0. Their game-data
loaders and game-data requirements are deliberately not used. This project neither
republishes nor depends on those projects, and their licensing is not relied upon
as permission to redistribute any original game's content.

## Newly authored choices

Kestrel-30 naming, geometry, 90 ms cadence, ammunition/reload/ADS/recoil/spread
profile, target balancing, map layout, sound synthesis, presentation, physical-unit
conversion, fixed 120 Hz clock, sprint recharge/input behavior, landing penalty,
and air-speed cap are authored prototype choices. They must not be labeled retail
weapon statistics or verified retail behavior.

## Third-party dependencies

Macroquad 0.4.14 (MIT/Apache-2.0), Miniquad and transitive crates are declared and
locked through Cargo. These are ordinary rendering/input/audio/math dependencies;
no reference-game code is linked. Macroquad supplies its own default UI font.
Use `cargo metadata --locked` to inspect the complete version/license graph.
THIRD_PARTY_LICENSES.txt bundles package notices and available upstream license texts, including the bundled font.
Cargo package licenses remain applicable to their own code. The root MIT license
covers newly authored project files only.


## Authorized test weapon and candidate profile (2026-09-30 update)

The user supplied an untextured third-party HK416A5 FBX and confirmed artist
permission to include its specific converted test asset in this game's public
repository. It is not a model from the original commercial game. Only the single converted
VRMESH01 package is included; original FBX and GLB intermediates remain excluded.
Asset rights are separate from the source MIT license: see [asset notice](../assets/README.md).
The generic converter and decoder are original project code. Format conversion is
reversible and is not a substitute for distribution permission.

The selectable/default M4A1-inspired candidate uses a public analyst sheet's
reported timings and modifiers, with unresolved conflicts and authored remainder.
See [M4 profile](M4_PROFILE.md). Neither that candidate nor the independently
selected HK416A5 visual establishes retail equivalence.
