# Jump integration WIP

Checkpoint 2026-10-04: original committed-time controller is implemented; renderer,
manifest slot wiring and source export remain pending. This is not game-playback
completion.

`src/authored_jump.rs` observes only the simulation's accepted launch timestamp,
grounded state and presentation eligibility. It does not consume raw Space input
or modify `sim.rs`, physics, ADS, firing or reload decisions. Takeoff plays at
native time; the non-looping air clip clamps and holds its endpoint. Actual ground
contact starts the landing clock, including early/late contact. A presentation
transition serial allows the owning sampler to blend from the actual prior pose
without changing source Action curves.

Eight focused contract tests pass: native timing/air hold, early/late contact,
rejected/old input and falls, held input versus a fresh accepted jump, reload/
mantle suppression, pause and invalid-step atomicity, tick-partition independence,
and invalid durations. The first run was blocked by sparse-checkout updater files;
after materialization the linker needed the already-installed ALSA shared library.
A workspace-local `libasound.so` link to the existing system `.so.2`, supplied via
`LIBRARY_PATH`, resolved that environment issue without installing system software.

Command (environment-specific cache/library locations omitted):

```sh
cargo test --locked --test authored_jump_contract
```

No source blend is edited or replaced at this checkpoint. The immutable r7 source
and named stable runtime IDs remain the contract. Shared integration paths were
reserved with Hal; ADS composition, export/load parity and actual fixed-camera
runtime transitions must still be exercised. No merge, release, new render or
full-game build is claimed.
