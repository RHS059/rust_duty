# Visible build identity

Every GitHub game workflow attempt has a distinct human-facing label:
`0.1.9+build.123456789.2` means release version `0.1.9`, workflow run ID
`123456789`, attempt `2`. Both platform builds in that attempt share the label.
Rerunning the same commit changes the attempt or run ID. Different branches and
workflows cannot collide merely because their workflow-local run numbers match.
Missing, malformed or oversized GitHub identity values fail closed.

The label is visible in the window title and main/pause menu, returned by
`--build-label`, embedded in `BUILD_IDENTITY.json` as `display_version`, and used
in the downloadable artifact name. `--build-number` returns the run/attempt pair.
The packager executes the built binary and verifies both its release version and
full build label before stamping it. A cached binary from another attempt fails.
The build script tracks run/attempt environment changes so Cargo invalidates its
cached embedded label on reruns.

## Release compatibility

`--build-version`, `BUILD_VERSION`, the manifest `version`, and signed update
sequence retain their existing stable release semantics. Build labels identify
attempts, **not** global chronological allocation order. Rerunning an older
release does not make it a newer release. The updater's stable version and
sequence ordering remain authoritative; reserved `0.1.9` and `0.1.10` releases
are unchanged. No token, secret, write permission or persistent counter is added.

The existing publisher still consumes fixed artifact aliases. CI uploads those
as identical-byte compatibility aliases alongside the uniquely named downloads.
This does not compile a second build. Publisher control-branch pushes are excluded
from gameplay build triggers: republishing tested artifacts is not a new build.
The build identity JSON is kept in each packaged game's payload. Existing signed
update-manifest field names are unchanged and do not gain unsupported fields.

## Local builds

Fresh local compilations display `VERSION+build.local.TIMESTAMP_NANOSECONDS.PID`.
This is explicitly local provenance, not an allocated release or globally ordered
number. Source/Cargo-lock changes and CI identity changes rerun the build script.
Cargo reusing an unchanged executable also reuses its label, correctly identifying
the same bytes rather than claiming a new produced build. Forcing a fresh local
compilation via `cargo clean` generates a fresh local label. Local timestamp/PID
labels do not claim a distributed collision-free allocation guarantee.

## Checks

- `rustc --test build_number.rs -o /tmp/build-number-tests && /tmp/build-number-tests`
- `python -m unittest discover -s tools -p test_build_numbering.py`
- `python -m unittest discover -s tools -p test_publish_game_build.py`
- `cargo fmt --all -- --check`, `cargo clippy --locked --all-targets -- -D warnings`,
  `cargo test --locked`

Tests cover reruns, independent branches/runs, invalid attempts, stable retry
identity, old-run/new-release ordering, cached-binary rejection, both platforms'
stamped identities, and CLI/artifact-label agreement. Native visual checks remain
separate evidence from these headless contracts.
