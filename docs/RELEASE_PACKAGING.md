# Exact-source release packaging

The release plan selects a game commit and its successful complete Windows/Linux
artifacts. It must also select the packaging toolchain from that same commit.
The release-control branch can be older than the game; its historical packager
only included the 43-clip locomotion baseline and silently omitted newer runtime
packages when preparing 0.1.7.

The corrected preparation job checks out the complete game source into
`game-source` using the validated plan SHA, retaining all Python helper imports.
It never rebuilds the game or authors/renders assets. `stage_release_game.py`:

1. Checks the toolchain's exact Git HEAD, artifact BUILD_IDENTITY, executable
   hash, and release version.
2. Matches animation bindings and reload/alternate contracts against source,
   rather than trusting an internally consistent truncated artifact.
3. Runs the exact-source `package_game.py` with `--require-generated` for both
   the fresh distribution and managed update.
4. Checks all authored runtime members against the untouched complete artifact,
   including locomotion, walk, ADS, directional, and reload alternates; verifies
   the executable again after staging. Unknown future asset bindings fail closed
   until the guard is intentionally extended. No fixed total file count is used.
5. Rejects symlinks and protected user/private paths in managed updates. Fresh
   ZIPs retain their normal settings file; updates do not overwrite settings.
6. Reads the final ZIP and RDB members independently and compares their exact
   paths, sizes and SHA-256 values with the staged files before publication.

The existing post-publication smoke no longer incorrectly bans an `assets`
directory. It verifies all extracted members against the authenticated bundle,
requires the complete authored runtime asset set, and retains private-data
sentinel, delta-integrity, rollback, and anti-replay checks.

The read-only `Verify exact-source complete release packaging` workflow reproduces
the repair using the successful 0.1.7 native artifacts at source
`21dc70af50ea49f76fc3d6716e3717aaf68d2377`, build run `37161083445`.
It repackages and independently checks both platforms without publishing,
changing a release plan, allocating a version, or replacing an existing release.
Its report records every preserved managed asset. An actual future release still
requires coordinated application of this fix to the release-control branch.

This patch does not modify the selected release version or either game source.
Published 0.1.6/0.1.7 remain immutable; corrected packages must use the coordinated
next release. Apply only after checking the release branch's current head so
concurrent plan changes are preserved.
