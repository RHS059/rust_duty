# GitHub game-update channel

The game trusts `RHS059/rust_duty` over HTTPS and checks strict schema-1 manifests,
monotonic versions/sequences, payload sizes and SHA-256. No owner signing-key
setup is required. A compromised repository/release account is inside this trust
boundary; hashes detect corruption, not an independent publisher identity.

## Explicit one-time 0.1.5 delivery

The owner has explicitly requested release 0.1.5 now so the current integrated
game reaches existing installations. `.github/workflows/build.yml` implements
that one-time exception after the entire Windows/Linux build matrix succeeds,
for push events only on `aella/automatic-game-updates-r1` in `RHS059/rust_duty`.

The only permitted release identity is **version 0.1.5, sequence 5**. There is no
run-number versioning and no automatic version increase on draft PRs or ordinary
builds. The ongoing policy is to increase the patch version by one for each PR
merged to `main` (0.1.5, 0.1.6, and so on); serialized merged-PR release automation
is separate follow-on work and is not implemented by this exception. This path
does not merge a PR or authorize additional releases.

Pull requests, forks, `main`, other feature branches and failed/cancelled builds
cannot publish through this path. The one-time delivery has no separate launcher
artifact, manual release-plan or `aella/release-channel` branch dependency. The
old manual workflow is retained as historical tooling.

Every game compile/test in the build matrix receives
`RUST_DUTY_BUILD_VERSION=0.1.5`. Both release binaries must report that exact value
through their headless `--build-version` command before artifact upload.
`BUILD_IDENTITY.json` binds the reported version, executable size/hash, target,
commit, branch and exact build run. The publisher checks that identity again
after downloading both complete game artifacts from **its own run**, without
rebuilding either executable.

Re-running the same build keeps version 0.1.5 and sequence 5. Once published,
those bytes cannot be replaced by a later branch push. Source changes alone are
not proof of a playable release: generated asset checks, Python tests, root game
formatting/lint/tests, updater crate formatting/lint/tests, both release builds
and Linux native gameplay capture gates all run before publication.

## Complete and safe payloads

`tools/publish_game_build.py` validates both source identities and re-stages each
artifact through `tools/package_game.py stage --update --require-generated`.
Only the exact public distribution allowlist is copied. Missing or corrupt
reload, locomotion, walking, ADS or directional companions fail publication.
Settings, saves, telemetry and private soldier assets never enter a managed
update. The same allowlist's fresh-install mode supplies complete public ZIPs
with default settings and profiles.

Managed updates preserve executable-relative authored-asset paths inside the
verified version directory. After activation, the game validates its active
bundle, extracted contents, executable hash and build version before reading the
shipped animation manifest and companions there. The persistent game root and
explicit settings/private-asset mappings stay intact. This supports existing
0.1.4 in-game update helpers that only replace the executable; the new runtime
selects the rest of the installed version's files directly.

The one-time release includes:

- `Rust-Duty-VERSION-Windows-x64.zip` and `Rust-Duty-VERSION-Linux-x64.zip`
- Both `update-TARGET.json` schema-1 manifests
- Both `rust-duty-VERSION-TARGET.rdb` full managed game bundles
- `vector-range.exe` and `vector-range-linux-x64` migration executables
- `SOURCE_PROVENANCE.json`, binding commit, branch, run, artifact identities and
  all other release asset hashes

No separate launcher is necessary for players already using the in-game updater.
Complete ZIPs are for fresh installs; an installed game discovers the appropriate
manifest at `/releases/latest/download/update-TARGET.json`.

## Atomic publication and retries

The publisher creates a draft at the exact source commit, uploads and verifies
all nine assets, then makes it public/latest in one release update. Both target
manifests become discoverable together. The publication job shares the
`rust-duty-release-channel` concurrency group with the old manual publisher.
The authorized branch’s push workflows are not cancelled while publication may
be active.

Before creation and again immediately before public promotion, the publisher
reads both latest manifests and requires the candidate version **and** sequence
to advance. An older run finishing late is reported as superseded and cannot
regress latest. Inconsistent platform identities, unknown channel manifests or
version/sequence disagreements fail closed. An existing tag pointing at another
commit is never moved.

Published assets are never replaced or completed in place. A retry of an
already-published identical version verifies its assets and performs no writes.
An interrupted draft resumes only missing assets after confirming that every
existing asset has the exact expected hash, source and release identity. ZIP
metadata and file modes are normalized, so transport timestamps cannot change
retry bytes. Conflicting draft bytes fail rather than being clobbered. A rerun
that genuinely recompiles to different bytes therefore needs a new build/version;
it cannot silently rewrite the old version. This is publisher-enforced
immutability; it does not change repository access or release-security settings.

The concurrency lock protects cooperating workflows; a manual edit outside that lock is not an atomic
compare-and-swap and remains within the trusted repository-owner boundary.

## Deltas and verification

The one-time route emits deterministic full bundles with an empty
`deltas` array. That is a complete supported schema-1 update path, including for
existing 0.1.4 clients. `tools/release_update.py` and the game retain real copy/add
delta generation, strict retained-base checks and full fallback. A future release
can advertise a delta only when generated from a validated older retained bundle
and smaller than the full target; published full bundles remain available.

Run the targeted publication tests with:

```
python -m unittest discover -s tools -p 'test_publish_game_build.py' -v
python -m unittest discover -s tools -p 'test_release_update.py' -v
```

Tests cover publication gating, embedded-version and artifact/source identity,
complete payload preparation, deterministic archives, interrupted draft resume,
immutable retries/conflicts, wrong tags, missing or inconsistent latest assets,
monotonic ordering and out-of-order completion. They use local fixtures, not the
live GitHub API. A successful CI build is also distinct from native Windows
migration/interactive gameplay. Verify actual published discovery, old-client
activation, managed-asset loading and settings/private-model preservation before
reporting live delivery complete.
