# One-hand mantle r4 correction

Status: first hypothesis executed and reopened; guard failure retained as WIP.
No render or visual approval. See `evaluation_summary.json` for actual checks.

Input: PR35 at 1daee9ff0d250b6ad926dedaab4977663f560406, Action
`aella_mantle_onehand_r3`, BLEND SHA-256
`f289c6d404a6c9c276baac3089887f77a15ac2d18029e1aa39f66d6e335081df`.
Source clock: R3 decoded [7787,7883), 96 frames, 60/1 fps.

## Observed residual

The genuine r3 viewport witness loses the weapon below the camera for most of
the low carry and omits the visible support-hand release/recovery. The r3
authoring code changed the support hand only; the failed weapon-root Action
was inherited unchanged from the initial r1 hypothesis.

Elara's review: https://github.com/RHS059/rust_duty/pull/35#issuecomment-6158919317
Recommended score 35/Fail. Pixel numbers are guidance, not authoritative
identities. Direct inspection of original full-size PNGs shows, for example,
the f26 muzzle near (320,540), with rear receiver largely at the bottom; and
the raised f48 hand near x500 rather than the review's suggested x330. Those
manual observations are approximate and must not be confused with exact
tracked or corresponded points. Reference weapon and supplied HK416 geometry
are different, so preserve the supplied geometry and judge shared landmarks,
orientation, phase, contour and visible contact without forcing false matches.

## Bounded physical hypothesis

The inherited camera-relative yaw/pitch path sends the weapon out of view.
Replace only a new copied Action's weapon-root path and dependent support-hand
curves on f8–85, with identical endpoint evaluations and unmodified old Actions.
The weapon should travel from the original f8 pose to a muzzle-up-left low
carry, remain visible, rise over f44–72, and rejoin the original f85 pose.
Retain the existing source clock. Use the unchanged perspective camera and
actual weapon geometry to solve translation and orientation. Do not move the
camera, scale the mesh, alter rest bones, modify guards or broaden constraints.

Support hand: preserve initial attachment, maintain the raw reference's free
hand beat on f44–52, then match a return to the weapon by about f65. Both
position and orientation must be continuous at attachment transitions. Surface
contact, fingers, wrist limits, elbow bend and full sleeve deformation all need
separate proof after the weapon path is stable. Hidden depth remains inferred.

## Protected invariants

- f1–8 complete evaluated pose and f85–96 weapon pose
- f89–96 complete settled hold; only support recovery may change through f88
- All prior Actions and original pose defaults/NLA
- Camera, mesh, weights, materials, rest skeleton, drivers and constraints
- 96-frame native 60 Hz mapping, with no duplicate or retimed frames
- No changes in Hal's low-vault lane or common runtime/release files
- No private BLEND, meshes, textures, rig, FBX or derivative source upload

## Diagnostic gates and stop

First obtain an actual evaluated baseline and projected physical landmarks at
f1,8,11,16,20,26,36,44,48,52,57,60,65,72,84,85,96. Then run one bounded
camera-space candidate and inspect genuine foreground Eevee witnesses before
any dense solve. Reject the candidate if framing or anatomy is worse; do not
optimize a wrong landmark family. Acceptance requires complete native-frame
visual review plus dense subframe technical checks, save/reopen identity and
preservation checks. Export/runtime validation remain separate, unclaimed.

## Boundary interpretation confirmed after baseline inventory

The evaluated r3 has support follow exactly zero at f85, reaching one only at
f88. The reviewer confirmed at 2026-10-14 02:14 UTC that support recovery alone may
change through f88 to avoid releasing a new f65 grasp a second time. Weapon
and camera preservation remain strict, as does the complete f89–96 hold.
The new Action must join the original support curves at f89 with identical
outward evaluation; this is an explicit, bounded interpretation of the review.
Elara confirmed the interpretation at 02:14 UTC: the protected ending means the settled pose, not a repeat
of r3's late release; retain weapon/camera on f85–88, settle support by f88,
preserve f89–96 exactly, and avoid an f88→89 pop. No timing change is permitted.
