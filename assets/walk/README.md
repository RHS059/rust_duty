# Authored regular walk, merged with preserved locomotion

`normal_walk_r1` is Hal's authored 60-fps Action, source frames 1–45 (44 unique
frames, 0.733333 s loop), from the source tracked under
`assets/authoring/locomotion`. This is not the old procedural Rust bob.

This 44-clip pack adds that walk while keeping all 43 canonical animation payloads
byte-for-byte, including `normal_ready` and the 73-frame `normal_settle`.
The `.vrs` and `.vrm` companions are identical to the canonical locomotion pack.
The old `assets/locomotion` files remain unchanged.

`manifest.json` records input/output SHA-256 hashes and preservation evidence.
`parity.json` records actual Rust CPU skin, rigid vertex, actor origin/matrix, and
visibility comparison against 25 independent native Blender witnesses, including
between-key times. The numerical limit is 1 mm; this is not visual acceptance.

## Reproduce

Use Blender 4.3.2, Python with `tools/requirements-assets.txt`, and a compiled Rust
sampler. Source PR #10 must be present. Run from repository root:

```sh
cargo build --locked --release --no-default-features --example sample_viewmodel_clip
python tools/build_walk_assets.py --blender blender \
  --sampler target/release/examples/sample_viewmodel_clip \
  --work build-assets/walk-reproduction --output build-assets/walk-result
```

The build explicitly disables Blender autoexec, verifies the source integrity,
exports all 44 source FBX takes, selects only `normal_walk_r1` for the append,
converts at 480 Hz, copies old runtime payloads without re-encoding, and requires
Rust parity before writing the distribution manifest. Existing destinations are
rejected. The diagnostic take is never included in this runtime pack.

The FBX NLA stack imports at frames 0–44, so the converter uses a zero frame
offset and 60 Hz. Reload keeps its independently declared 60000/1001 Hz clock and
one-frame offset. Changing either source contract requires new verification.

`asset.vrs.gz` is the repository transport; unpack it as `asset.vrs` for runtime.
Bind `regular_walk.asset=walk/asset.vra` and `regular_walk.clip=normal_walk_r1`.
All gameplay and cross-asset transition bindings are owned by the runtime layer.
