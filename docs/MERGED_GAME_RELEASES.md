# One PATCH release per PR merged into main

Version `0.1.5`, update sequence `5`, is already consumed by the explicitly
requested one-time release. The immutable activation boundary is main commit
`bfa2042d60b48f9ce076e066b3cd862630d3424e`. Every PR merged into main after that
boundary receives the next patch and sequence: `0.1.6`/`6`, `0.1.7`/`7`, and so on.
This includes the PR installing this policy if it is the first such merge.
All PRs merged into main count, including source, assets, tests, and documentation;
there is no label/path filter or subjective definition of a game update.
Drafts, PR branch pushes, direct status commits, and CI reruns allocate nothing.
Merges into intermediate integration branches do not consume a main release.

## Allocation

`merged-game-release.yml` receives merged/closed PR events from trusted main
workflow code. The allocator independently verifies GitHub's actual merged PR,
base repository/main branch, and exact merge SHA on main. This also covers merged
fork PRs without running an unmerged fork with a write token.

The dedicated `rust-duty-release-ledger` branch contains only a JSON ledger.
Each immutable entry binds PR number, merge SHA, patch version, update sequence,
and its canonical build run. Initial creation is an orphan state commit; updates
have one parent and use non-force ref updates. A concurrent or uncertain write is
reread and reconciled before retry. Existing assignments never move or get reused.
No source/main commit is created for a version bump, so there is no feedback loop.

Allocation reconciles the whole anchored first-parent main history in order,
not workflow arrival, PR number, timestamp, or run number. A later event arriving
first still assigns earlier merged PRs first. Merge, squash, and rebase merges use
GitHub's definitive `merge_commit_sha`; direct commits are ignored. Rewritten
main history, duplicate assignments, invalid state, truncated pagination, or an
older merge discovered after an incompatible allocation fail closed.

GitHub concurrency uses `queue: max`, `cancel-in-progress: false`, and separate
ledger/publication lock names. Because GitHub caps each queue at 100 waiters, a
15-minute reconciliation trigger claims the oldest still-unclaimed merge after
missed events or queue overflow. With no pending merge it performs no game build
or release publication. The durable ledger, rather than the queue, owns identity.

## Exact-source complete builds

The allocation's source SHA is passed to all four reusable authored-asset jobs
and both native game jobs. Each checkout verifies its exact SHA. Only the native
game builds receive the allocated `RUST_DUTY_BUILD_VERSION`; `Cargo.toml` remains
the development package baseline. The running game, updater comparison, startup
acknowledgment, and `--build-version` all report the allocated embedded version.

Every complete artifact records the exact source SHA, canonical run, PR,
version, sequence, platform, executable size, and SHA-256. Publication requires
all asset jobs and both native jobs to pass, including source checks, formatting,
lint, Rust/Python tests, complete packaging, and native Linux gameplay captures.
Draft validation builds retain the development version and have no publisher.

## Publication and retry

Only the publication job has release write permission. It independently rereads
the ledger, merged PR, main ancestry, source run, both latest successful native
jobs, and the two exact same-run artifact identities before creating a draft.
It prepares the existing strict package allowlist and verifies all nine assets:
Windows/Linux ZIPs, full update bundles, update manifests, migration executables,
and provenance. It discovers drafts by listing releases and uploads only missing,
byte-identical assets by release ID. It never replaces an existing asset.
The final draft-to-public change occurs only after the complete inventory matches.
Settings and private soldier assets remain excluded from managed updates.

The channel never rolls back. If a newer merge finished first, an older successful
merge can publish its complete immutable release with `make_latest=false`.
The in-game updater continues seeing the newest successful complete release.
A failed build still consumes its merge's version, but never advertises an
incomplete package; a later successful merge may therefore skip that failed
version in the public latest feed.

Retry the canonical run's failed jobs. That retains the same version, source run,
and already successful artifacts. A duplicate event or manual dispatch for an
already-claimed PR returns the canonical run link instead of rebuilding with a
different identity. An interrupted publication resumes that run's existing draft
and adds only missing identical assets. Do not select 'rerun all jobs' after a
partial publication: rebuilt binaries or provenance may differ, and immutable
asset checks deliberately refuse replacement. If retained artifacts expire or
are missing, recovery is a visible blocker requiring a reviewed exact-identity
recovery; the allocator never silently recycles the version or changes ownership.

`workflow_dispatch` accepts a merged PR number for lookup, or no number to claim
the oldest unclaimed merge. It is permitted only from main. On branches containing this change, the old manual release
plan workflow is read-only and explains this policy; it cannot allocate or
publish competing version numbers. Historical branches are not rewritten by
this PR; do not use an old branch's obsolete manual publisher for new versions. The historical 0.1.5 exact-ID recovery remains
bounded to its original branch, release ID, source run, and pinned provenance.

## Activation and verification

This change is a draft proposal until merged to main with its prerequisites.
Creating this PR does not publish a release, reserve a live version, or change
main. Runtime integration PRs can proceed separately from these release files.

Offline tests cover duplicate/reversed events, CAS conflicts and uncertain writes,
merge modes, direct commits, replay/tampered identity, immutable uploads,
newer-versus-older completion, failed native jobs, and workflow trust/permission
contracts. The lightweight `Verify merge release policy` job runs these tests
without publishing or modifying the live ledger. Full complete-game checks run
on the draft PR. The first actual merge event and release remain unexecuted until
the policy is deliberately merged; tests do not claim live activation.

References: [GitHub merge identity](https://docs.github.com/en/rest/pulls/pulls#get-a-pull-request),
[non-force refs](https://docs.github.com/en/rest/git/refs#update-a-reference),
[concurrency queues](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).
