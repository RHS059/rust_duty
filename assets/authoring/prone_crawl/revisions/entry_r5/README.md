# Prone entry r5 source revision

Status: source authored and fresh-reopen numerical verification passed in Blender 4.3.2. Candidate SHA256 `67cf025fc31d9804cb0259432a91e496d7d8f84d1d4ac6be2b1914a6a98510ad`. No preview or artistic pass is claimed.

Input is PR #34 at f230079ccf60f78aebddc702dfeed368615e3dc7, `revisions/entry_r4/halcyon_prone_crawl_r4.blend`, SHA256 `9c9aef2f059a14653cd3eb7fddda8505af5b48aeefe29d65a31667f3ef5b6ee8`. All 111 source Actions must survive. Output is a separate 112-Action BLEND containing new Action `prone_crawl_enter_r5`.

## Changes made

- Preserve frames 1–41 including the cuff fix. Check every bone at 480 Hz, exactly, before saving and again on fresh reopen.
- Apply additional camera-space roll about the original tracked rear-sight pivot after frame 41, reaching the proposed correction at frame 50. Keep prior pitch/yaw, scale, timing and path.
- From frame 49 to 55, pull the left shoulder down/back in camera space while keeping its existing hand target through local Action-only contact compensation.
- Preserve all earlier Actions, geometry, camera, rig/rest pose, bindings, materials, drivers, NLA, packed images and active state. Keep changes in this folder; no canonical overwrite or runtime activation.

The candidate values in `correction_design.json` are bounded artistic choices. They are not reconstructed COD measurements. The original reference tracks measure optic-region movement, not late rail or sleeve segmentation. The historical candidate panel cannot prove a defect in the pinned r4 source. The reference panel remains useful directional evidence. The correction uses +20 degrees additional camera-space roll blended over f41–50 and a 3 cm downward / 1.5 cm backward shoulder offset blended over f49–55, with hand-target compensation. Fresh capture will establish visible effect; no extra approval gate is introduced.

## Reproduce and verify

Use Blender 4.3.2 with `--background --factory-startup --disable-autoexec INPUT.blend --python-exit-code 1 --python revise_entry.py`. The recipe refuses an incorrect source hash, unexpected Action inventory, source overwrite, existing output, non-finite contact residual, contact above 0.1 mm, or any early-pose difference. Run `verify_revision.py` in a separate fresh Blender process on the resulting output. That checks saved preservation, exact early poses and 240/480 Hz attachment residuals. Both authoring and fresh-reopen Blender tests passed. The saved source has 112 Actions, with all 111 prior Actions and source structure unchanged. Frames 1–41 have exactly zero all-bone matrix difference at 480 Hz. All 545 sampled poses are finite. Maximum hand-target residual is 0.00829 mm at 480 Hz and 0.00520 mm at 240 Hz, below 0.1 mm. See `fresh_reopen_checks.json` and `revision_report.json`.

## Genuine preview still required

Capture all 69 native frames at 60 fps using foreground Blender Eevee Viewport Render Animation and the unchanged `RD First Person Review` camera. Do not substitute a Cycles render or claim background numerical evaluation is a preview. Use guarded initialization and record source/Action fingerprint, capture process, settings, each image hash, and exact `frame_map.json`: output i ↔ candidate i+1 ↔ COD 2241+i. Reference media SHA256 is `491a1729aa0f32373025d35fff86da76c6c1c8f057c0c553d0fbb5fb6226ff46`.

Compare native witnesses around candidate frames 41, 46, 50, 55 and 69, plus the complete sequence, for the rail diagonal and support-arm coverage. No retime, crop-to-conceal, camera/geometry change, or artistic score is supplied by this recipe. This executor has Blender/ffmpeg. A temporary foreground Xorg dummy-display test failed because the sandbox denies the local/unix sockets required to open a display. No genuine Eevee capture was produced here; capture requires an available display-capable executor.
