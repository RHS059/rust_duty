# Reload return and ADS placement

The current WIP returns from an authored reload to the live walk/run/ADS pose
over 0.20 seconds. Entry also blends from the currently displayed pose. The source
clip still uses native seconds. Its endpoint no longer waits on a longer gameplay
timer; ammunition, credit, firing readiness and cancellation remain owned by the
simulation. Pause does not advance either pose or blend. A new reload during a
return captures that displayed pose, including current prop opacity.

The reload pack has 72 named deform bones and three actors; canonical locomotion
has the same named hierarchy and two actors in a different order. `PoseReturnMap`
checks companion skeleton ordering, named parent relationships and inverse binds
within 1e-5, then maps evaluated global joints by name and reconstructs locals.
`PoseBindings` and each pack's checksum checks remain strict. No differently sized
pose arrays are passed directly to `AnchoredPoseBlend`.

The reload FBX importer stores rigid mesh-local coordinates in the (x,z,-y)
basis. Canonical rigid actors keep their original mesh-local frame. The mapper
therefore right-multiplies canonical actor globals by that basis's inverse;
the existing game model root is still applied once. On the exact dad6071 source
companions, named inverse binds differed by at most 2.19e-6 per component, and
the corrected common rigid vertex sets agreed within 4.7e-8 m. These are
compatibility measurements, not source-motion approval.

During an interrupted return, the reload-only outgoing magazine remains at its
last displayed transform and fades away as the hands return. This is a runtime
visibility transition, not a newly authored drop animation. The reload renderer
owns the entire transition; canonical rendering resumes at its mapped endpoint.
Weapon-relative blending preserves shared pose relationships, but does not
certify hidden grip contact or exact intermediate limb lengths.

Saved placement XYZ now fades with visible ADS progress, including the authored
entry/exit clock and the run blend. It is exactly zero at full aim and returns at
hip. Saved values and per-weapon walking gains are unchanged. Reload entry/return
also carries the current visual aim amount so placement does not reset on that
handoff.

Regression evidence lives at the affected boundaries:

- Rust tests cover all 27 placement extremes, 30/60/120 Hz interrupted ADS,
  current-pose restart, exact native completion/cancellation events, actual
  cross-pack named mapping, invalid rests/dimensions and prop retirement.
- `verify_ads_placement_capture.py` compares identical native gameplay replays
  with zero and extreme XYZ placement. Held ADS images must match exactly,
  moving ADS must be represented, gameplay telemetry must match, and hip images
  must differ both before and after aiming.
- `--capture-sequence=gameplay-return --capture-hz=60` exercises complete reload,
  live walk/run/ADS, cancellation and restarting while a return is active.
  `verify_reload_return_capture.py` requires those episodes, concurrent movement,
  fading reload-only props, finite/bounded sampled anchor translation and conserved
  ammo. Native seconds and declared clip duration distinguish completion from
  cancellation; a fresh native clock during an unfinished return proves restart.
  This translation metric does not bound angular, joint or skin continuity.

Run these native checks on the complete generated package. Windows compilation
does not establish native Windows input/Alt-Tab behavior or antivirus acceptance.
Existing source-articulation precision and motion-review limitations remain WIP.
