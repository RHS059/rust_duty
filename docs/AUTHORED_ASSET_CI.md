# Authored assets in complete game builds

GitHub is the source and build location. No Library or external asset-store lookup
is needed. Blender 4.3.2 is downloaded from the official release server and checked
against its pinned SHA-256; source auto-execution is disabled. Packed textures and
native rig drivers are retained.

- `assets/source/reload/current.blend`: current full two-hand reload WIP; explicit
  selections keep primary 0–156, separate opening 0–30, static reset and inspection
  pickup distinct. Stored Action inventory and curve hashes accompany every export
- `assets/authoring/locomotion/locomotion.blend`: portable source with authored
  `normal_walk_r1`, 60 fps, frames 1–45. `export_config.json` defines the selection
- `assets/locomotion`: original 43 runtime clips remain frozen and hash-verified
- `assets/walk`: adds the authored loop while preserving all43 original clip-record
  bytes and the exact canonical VRS/VRM companions
- `assets/animations.cfg`: stable semantic gameplay bindings, including regular walk

The complete-game workflow runs reload and walk export jobs independently, then
both Windows and Linux jobs consume those same-run verified outputs. Walk passes
source→FBX→explicit named-take conversion→canonical merge→actual Rust skin, rigid
geometry and visibility parity. The diagnostic source take is not gameplay data.
Reload retains its independent 60000/1001 fps clock; walking is exactly 60 fps.

Each asset cache has no broad fallback key. Keys include source BLEND and selection,
exporter/converter/compiler/parity scripts, template/skeleton data, the official
Blender/dependency setup action, relevant Rust sampler modules, Cargo files and the
exact `rustc -Vv` fingerprint. Cache hits are still revalidated against the current
source checksum, every output digest, binary binding/CRC contract and matching
passed Rust parity. Walking's 43 original payloads are compared byte-for-byte.
Changing source or any listed producing input invalidates its cache automatically.
No failed export or parity job publishes a complete game or a successful cache.

The game matrix materializes verified gzip transports before real-asset tests.
Game artifacts contain the actual executable at the root, settings, notices and
all required raw runtime companions; no separate updater executable is required.
Linux additionally renders committed-input gameplay and uploads frame/metadata
proof. Numerical and renderer checks do not constitute artistic approval of WIP
hand contacts, transitions, or movement quality.

## Authored ADS build

`assets/authoring/ads/ads.blend` is a nondestructive copy of the canonical walking
source with three additional versioned ADS Actions. Original Action curves and
rig data are hash-audited. The ADS job consumes the same run's verified walk44
pack, exports only the three explicit ADS takes through Blender 4.3.2/FBX, then
appends them without reserializing any original clip record. Its 47-clip pack
keeps the exact canonical geometry and bindings. Every take has an independent
source-to-Rust skin/rigid/visibility parity report, including off-key samples.

The ADS cache binds its source, selection, baseline walk outputs, exporter,
converter, compiler, sampler, validation and toolchain inputs. Fresh outputs and
cache hits both fail closed on stale source hashes, stale parity, wrong loops,
wrong clip durations, changed original44 bytes, or mismatched companions.
Windows and Linux package the same-run checked pack; Linux also renders committed
ADS input, reversals, walk/sprint/reload interruptions and return-to-ready. Windows
build success does not substitute for native Windows gameplay verification.
