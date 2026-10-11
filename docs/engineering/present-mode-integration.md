# Opt-in present-mode integration

The production default remains explicit `Fifo`. The native runtime accepts
`--present-mode=fifo`, `--present-mode=mailbox`, or `--present-mode=immediate`
(a separated value is also accepted). A duplicate, missing, unknown, or unsupported
mode fails closed. An explicit request with legacy Macroquad is rejected.
Launch, renderer, graphics-device and present-policy parsing stop at `--`.

The policy helper originates from the independently reviewed
`f97c878f63a72c979ed6033fa72689490cbfd024` source. Runtime wiring passes the parsed
request through window creation, checks the exact surface/adapter capability
list, and records the retained configuration only after validation succeeds.
Automatic or relaxed wgpu modes are never relabeled as one of the concrete
diagnostic choices. An unsupported present request is terminal even when the
backend selection is Auto; it cannot trigger a retry on another API.

Resize and surface recovery retain the request and re-query the current surface
with the same retained adapter before configuration. Configuration validation and
device-error checks remain enabled. A lost device remains terminal.

The seven-field `renderer device_evidence` log remains unchanged. The richer
graphics-device/session evidence adds `present_policy` with `requested_mode`,
`actual_mode`, and `explicit_request`. The existing `present_mode` field continues
to use the actual wgpu configuration spelling, including `Fifo` for the default.

The finite matrix runner still requests and requires Fifo. Its existing plans
are not a mailbox/immediate comparison, and this option is not an FPS limiter.
Configured Immediate does not establish that DX12 acquisition waits disappear,
that tearing occurred, or that a monitor displayed a particular rate. Keep CPU
acquire/present spans, physical extent, adapter/driver/monitor identity and exact
build provenance when comparing modes. GPU timestamp measurements have their own
scope and are not supplied by this present-policy wiring.

## Verification scope

This local integration is work in progress. Pure policy tests from its isolated
upstream harness do not execute these production launch/device paths. The added
Rust integration-boundary regressions now pass in the Linux native-feature
library suite, and formatting/all-target Clippy have run with Rust 1.99.0.
Window resize/recovery and selected RTX 3080 Ti Windows DX12 measurements must
still run against the exact combined revision before native or performance
acceptance.
