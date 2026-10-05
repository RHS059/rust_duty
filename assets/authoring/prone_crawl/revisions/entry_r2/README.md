# Prone entry r2 WIP

Frozen source SHA256: fd5b55b21acdcd73ff39cafd258c6d7281f8dc51359e65cadc76f769909f74e4

Independent r1 frame review identified an oversized aft-stock/butt-face presentation in late recovery at Blender frames 41, 55 and 69 (R3 frames 2281, 2295 and 2309). The r1 genuine viewport evidence remains in ../../review/r1.

This candidate adds prone_crawl_enter_r2 to the frozen 108-Action source; all 108 previous Actions remain byte-fingerprint identical. Camera, geometry, materials, rig/rest state, constraints, drivers and NLA are unchanged. The source has 109 Actions.

Before: optic-region scale/roll inference with no pitch/yaw recovery correction. After: camera-space pitch +18 degrees and yaw -10 degrees around the existing rear-sight pivot, quintic blend from f41 to f55 and held through f69. The sight trajectory and 69 native frames are retained. These angles are bounded artistic inference for viewport comparison, not measured source 3D values or a visual acceptance claim. Early f1–41 all bone matrices are exactly unchanged on the 480 Hz comparison grid.

A left-shoulder location correction within only the new Action maintains support-hand IK reach. Fresh reopen tests pass at 240/480 Hz, worst wrist target residual 0.0108 mm, all 545 sampled bone matrices finite. No runtime binding or common exporter changes. Stable integration ID remains prone_crawl_enter; no looping or hard-join approval.

The r2 actual Eevee viewport preview and independent review are pending. The r1 MP4 is not an r2 preview. This source is an editable WIP, not production activation.
