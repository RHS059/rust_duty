# Prone entry r4 WIP

Frozen candidate SHA256: 9c9aef2f059a14653cd3eb7fddda8505af5b48aeefe29d65a31667f3ef5b6ee8

Adds `prone_crawl_enter_r4` to the r3 source. All 110 prior Actions, fixed camera, geometry, materials, rig/rest state, drivers, NLA, and packed images are preserved. There are now 111 Actions. Runtime activation and artistic acceptance remain pending.

## Visible reason and narrow change

The independently reviewed r3 native pair sequence shows a near-vertical target rail during roughly 0.75–0.90 seconds (frames 46–55), while the COD reference retains a diagonal. Direct inspection of the actual paired MP4 at frames 41, 46, 49, 50, 55 and 69 supports that residual. Different model geometry and the COD optic prevent an exact 3D reconstruction; the lower-left support-arm coverage is also still visibly different.

This candidate applies only a modest camera-space +8 degree roll and +2 degree yaw around the existing tracked rear-sight pivot. A quintic blend starts at frame 41, reaches full correction at 55, and holds through 69. The r2 pitch/stock correction is retained, and there is no geometry, scale, camera or time change. These new angles are bounded artistic inference, not measured source values. Actual stock presentation and rail/arm improvement must be judged in a fresh fixed-camera Eevee capture; no visual pass is claimed.

The new Action's support-shoulder location channels receive only the compensation needed to maintain existing hand targets. Fresh-reopen evaluation proves all bone matrices on frames 1–41, including the r3 f36–38 cuff fix, exactly match r3 at 480 Hz. All 545 sampled matrices are finite; both 240/480 Hz hand-target checks pass, with worst residual 0.0109 mm.

## Reproduce and verify

Run `revise_entry.py` with Blender 4.3.2, `--background --factory-startup --disable-autoexec`, opening the r3 source SHA256 be9161fcba0f8550e1aa894e3d6df0dec5f98b0364e11cd0265556a07ca1da00. The author script refuses to overwrite an existing output. Run `verify_revision.py` in a fresh process opening the r4 BLEND; it compares saved structure against `baseline_preservation.json` before evaluating motion.

Native timing remains 69 frames at 60 fps, mapped to COD R3 source frames [2241, 2310). Stable runtime ID remains `prone_crawl_enter`. No runtime binding, common exporter, merge, production integration, or playback-loop approval is included.
