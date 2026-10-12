# Bounded legacy facade comparison

The native before/after comparison in
[run 37415102494](https://github.com/RHS059/rust_duty/actions/runs/37415102494)
completed all four static captures and reported `differences-observed`, with
`passed: false`. Keep that exact result. The observed difference is the deliberate
default-framebuffer screenshot binding repair, not an additional geometry change
exposed by these views.

## Sources and retained evidence

- Pre-facade reference: `e7a36bcaa26e0babe4da79b3a54b3785e56bf943`, original
  Windows build 37264388504.1.
- Current capture: `8f571464be706d0abde862e124582a188f633baf`, Windows build
  37415102494.1, using the same pinned app-local Mesa files, approved untextured
  weapon, reference extent, settings and frozen scene.
- [Comparison packet 11391995653](https://github.com/RHS059/rust_duty/actions/runs/37415102494/artifacts/11391995653):
  409,533 bytes; SHA256
  `59f7911d945ac82456aae60808442778e93ec510a3e0ed3ab71857eea1b39161`.

The retained packet's 61 listed files, 34 JSON records and ten process receipts
were checked. All capture and build-identity processes exited successfully.
Deliberately omitted binary/runtime/input files cannot be rehashed from this
small packet; their recorded producer/staging identities retain that limitation.

## Observed differences

Both world PNGs are exactly equal. Hip and ADS viewmodel foreground masks are
also exactly equal: 40,112 and 34,493 pixels respectively. Every foreground pixel
changes RGB, while background and alpha remain equal. Lighting JSON matches;
the shared presentation differences are only integer versus decimal spelling of
`ads` and `hfov`, such as `76` versus `76.0`.

Outside the explicitly excluded 64 by 22 frame-witness rectangle:

- The old reference viewmodels exactly match the contaminated GL captures from
  `5b062951` before the repair.
- The current viewmodels exactly match the fixed GL captures from `902d13bb`.

The entire legacy renderer file at `5b062951` becomes the `902d13bb` file by
replacing only the default-framebuffer readback arm with binding invalidation.
Named-target readback is unchanged. The mechanism and independent original-color
control are documented in [legacy-capture-neutrality.md](legacy-capture-neutrality.md).
Its native run at `1d71da29655046c02cfeb403e34c7789974be6f5` checked all 307,520
interior pixels across five captures against fixed colors without tolerance.

## Scope

This supplies bounded evidence that the frozen world and viewmodel placement
survived the facade transition, with the later screenshot-state correction
accounted for explicitly. Restoring the old tint, adding a pixel tolerance, or
changing this packet's strict verdict would misrepresent the result.

The facade routing audit and jointly frozen v1 contract remain documented in
[decision 0002](decisions/0002-wgpu-renderer.md). Two static views alone do not
prove every gameplay path, hardware performance, human review or complete
authored-suite acceptance. Those retain their separate evidence and gates.
