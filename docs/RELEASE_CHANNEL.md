# GitHub game-update channel

The production launcher trusts `RHS059/rust_duty` over HTTPS and checks strict
manifest fields, monotonic versions/sequences, payload size and SHA256. There is
no owner signing-key setup. A compromised repository/release account is inside
this trust boundary; a hash is corruption detection, not an independent author
signature.

## Reviewed release plan

`.github/workflows/publish-updates.yml` runs publication only on the dedicated
`aella/release-channel` branch. Its explicit `.github/release/plan.json` selects
immutable40-character game and launcher commits, version, positive sequence and previous
version. The checked-in plan is disabled. Publishing requires an explicitly
enabled plan on that branch; ordinary feature commits and pull-request builds
do not publish releases. This works without merging the game feature branch.
The optional manual trigger uses the same branch restriction and plan.

The workflow selects successful exact-source push CI runs for the pinned game
and launcher commits, then reuses their already-tested Windows/Linux binaries.
It validates the launcher trust marker and curates payloads with an exact file
allowlist. SOURCE_PROVENANCE.json and release notes identify both source revisions
and CI runs; pull-request merge-ref artifacts are not used. It creates a draft release,
uploads complete immutable assets, then marks it public/latest; an existing
version is never overwritten.

The payload is curated from exactly the game executable, game license and game
dependency notices. It imports no models, settings, saves, telemetry or wildcard
asset directories. Existing user models/settings stay in the stable local root
when the launcher switches version directories. The original/private preview
ZIP must never be used as the input release directory.

## Assets and deltas

Each target publishes `update-TARGET.json`, `rust-duty-VERSION-TARGET.rdb`, an
optional smaller `.rdd`, and a standalone migration launcher (`RustDuty-windows-x64.exe`
or `RustDuty-linux-x64`). CI artifact ZIPs are for developer transport; the player
transition is one standalone launcher executable, followed by automatic updates.

For a later release, `previous` is required. The workflow downloads that exact
retained `.rdb` and manifest from the repository's versioned release, validates
its target/version/hash, and prepares copy/add delta operations against those
bytes. A full bundle remains available for clients without that exact baseline.
The initial release cannot claim a delta from an unknown adopted executable.

Local fixture tests are necessary but do not establish live channel behavior.
Before calling the channel ready, verify a real published A→B transfer on Windows,
pause/resume/cancel, the selected delta path, final byte hashes, activation after
game exit, rollback and unchanged private-model/settings bytes. Record any stage
that was not actually executed.
