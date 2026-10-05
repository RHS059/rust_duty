# Windows release integration 0.1.11

Candidate **0.1.11 / sequence 11** integrates Windows-only delivery, Jump r7,
visible run/attempt numbering, the retained executable-baseline delta change,
and main's uploaded reference commits. Reserved 0.1.10 remains unchanged and is
not published by this integration. The upgrade baseline is public 0.1.9.

Prepromotion native fixture tests and postpromotion production GitHub migration
are distinct: the existing public game trusts the fixed latest channel, so actual
same-path 0.1.9 to 0.1.11 migration can only be verified after channel promotion.
No alternate trust endpoint is introduced into a shipped executable.

## Retained 0.1.10 development record


Candidate **0.1.10 / sequence 10**, based on the final Jump .9 source. This is a source/CI candidate only; release promotion waits for .9 to succeed.

The existing updater uses a retained full bundle when a matching delta exists. A directly launched game can instead retain only a one-file bundle of its executable. The publisher now optionally emits a second copy/add delta against that executable image. This lets matching clients reuse local executable bytes rather than download the complete new bundle. Changed executable sections and new assets remain part of the patch.

The updater still prefers a matching retained full bundle. If unavailable, it can construct the one-file image from the installed executable and use it only when version and SHA256 match an advertised, smaller delta. It reconstructs and verifies the entire target bundle before extraction. Staging leaves the active version unchanged; existing process-exit, activation, rollback, sequence, user-file and private-asset rules remain authoritative. A missing retained one-file bundle can be recovered from the matching executable. Without an eligible patch, no executable baseline is generated. Invalid-size, unreadable, short-read or concurrently growing optional executable bases fall back to the verified full transfer. Unsafe source paths and symlinks still fail closed.

Publication uses the unchanged manifest schema and the existing exact-source packaging path. The release-control branch must adopt this candidate's `tools/release_update.py` before it can advertise executable-baseline deltas. This candidate does not change that branch or publish anything. Clients lacking this optimization can still use full bundles or matching existing delta bases.

The previous-bundle executable reader validates the complete inventory, safe paths, modes, duplicate names, sizes and trailing bytes before emitting the alternate patch. Existing published assets are never rewritten.

Validation performed locally on Linux: updater unit/integration suite (56 passed, one helper subprocess test intentionally ignored in direct discovery), eight release-bundle Python tests, and 23 exact-source publication/identity tests. Targeted cases cover unchanged executable reuse, changed executable sections, missing retained baseline recovery, full fallback without eligible deltas, malformed prior bundles, byte-identical reconstruction and no early activation. Native Windows CI and real published-channel migration remain unverified.

Exact local validation commands: `cargo test --manifest-path updater/Cargo.toml --locked --offline`, `cargo clippy --manifest-path updater/Cargo.toml --locked --offline --all-targets -- -D warnings`, updater `cargo fmt --check`, and Python unittest discovery separately for `test_release_update.py` and `test_publish_game_build.py`. Deterministic reader fixtures cover source truncation, growth and permission failure; a real HTTP fixture verifies unusable optional-base fallback to the complete authenticated bundle without activation. These fixtures do not claim a reproduced operating-system race or Windows execution. Candidate identity tests explicitly reject stale .9/.8 pins and executables; historical release guards are unchanged.
