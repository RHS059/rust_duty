# Prone entry r3 WIP

Adds prone_crawl_enter_r3 to the preserved 109-Action r2 source; all previous Actions and fixed camera/geometry/rig are unchanged. New source has 110 Actions. Stable integration ID remains prone_crawl_enter; activation remains pending independent review.

R1 native PNGs36–38 and reference source2276–2278 independently confirmed an isolated cuff surge absent in the source. Inspection found an inferred weapon-root depth spike at37, with constant arm location keys; normal IK moved the elbow in response. This is source animation, not MP4 encoding.

Only the new Action's root depth channel changes on f36–38. Frame37 is replaced with the midpoint depth between36 and38. Two quintic segments retain boundary poses and tangents, with matched midpoint first/second derivatives; samples are keyed at480Hz. All other r2 motion, including its late-stock correction, is retained. All bone matrices outside the interval match r2 exactly on the480Hz grid.

Fresh reopen: all545 sampled bone matrices finite; both240/480Hz wrist residual checks pass, worst0.0108mm. cuff_before_after.json records actual evaluated wrist depth and elbow displacement. No rendering or visual pass is claimed here; genuine fixed-camera69-frame preview and independent review are next.
