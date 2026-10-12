# Staging pool integration into the resident renderer

This is a separate experiment from the resident-mesh GPU lighting/skinning change.
The resident geometry policy, shader, immutable mesh cache, authored loader routes,
destination-buffer reuse and draw/capture ordering stay enabled and unchanged.

## One encoder, one submission

The frame creates its existing command encoder after planning and before the
GeometryUpload phase. `UploadCache::begin_frame_with_device` collects completed
mapping tokens. Each cached nonempty CPU arena uses `upload_with_encoder` on that
same encoder. Whole-arena fallback keeps the existing queue-write behavior.
Resident mesh uploads are outside this pool and retain their existing accounting.

The timestamp start is recorded after the staging copies. GPU timestamp samples
therefore exclude these copies, as they already exclude implicit queue writes.
They must not be used as a measurement of total GPU upload plus rendering cost.
The existing `submitted()` call remains immediately after the single queue submit.
The outer error handler clears caches only after abandoned encoders/command
buffers have gone out of scope. No additional submit, poll or wait is introduced.

## CPU encode detail v4

The v4 sidecar preserves every v3 observation and adds `staging_policy` plus the
helper's ten named staging observations. The old v1/v2/v3 schemas and summaries
remain readable without added fields or invented zeroes. v4 explicitly identifies
the phase change: encoder creation is now part of the EncodeSubmit aggregate's
unassigned residual before GeometryUpload, rather than CommandEncoding.

All staging values are sampled once at GeometryUpload exit, including partial
error exits. `staging_retained_bytes` and `staging_pending_buffers` are live source
pool gauges at that point, before submission. The summary lists these separately
under `gauges` with no summed `total`. Other fields are per-attempt events/bytes.
Incomplete attempt observations remain outside every measured distribution.

Complete rows require one pooled allocation, pooled reuse or fallback route per
cached nonempty arena. Fallback covers all three payloads; transferred bytes keep
the original four-byte index padding. Pool gauges remain bounded by eight chunks
and 64 MiB, including unavailable/retired chunks. This limit does not describe
all GPU memory, resident geometry, destination buffers or driver staging.
Mapping failures cannot be reported as complete successful uploads.

## Controlled source pair and evidence

Only `STAGING_REUSE_ENABLED` in `src/frame_staging_policy.rs` changes for the
queue-write control. Both sides retain the same v4 phases, resident GPU route,
destination reuse and shaders. The new 46-file witness has separate exact
candidate/control digests; previous 43-file resident witnesses keep their pins.
A separately named 46-file resident CPU control changes only
`frame_resident_policy.rs`, keeping staging enabled. It supports a matched
resident-on/off hardware test of this combined revision without conflating the
two experiments. Turning both policies off is not an admitted source class.
Unknown, dirty, missing or mixed staging source cannot fall back to old admission.

The integrated native gates must exercise queued changed data, completed-source
reuse, abort/retirement and normal production frames, then replay the original
renderer controls and actual authored CPU/resident corner/image checks. Existing
resident evidence does not by itself validate staging. No performance improvement
is claimed until a matched real-hardware capture verifies source, data, policy,
normal shutdown and the complete CPU/primary cohorts.
