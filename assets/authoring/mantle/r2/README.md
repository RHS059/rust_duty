# Low-vault r2: diagnostic support-hand source

Status: **diagnostic**, not a reviewed animation or runtime-ready clip.

The saved candidate is `candidate/aella_mantle_r2.blend`, SHA-256
`740e7e2b16d6947075c321467cfe21d36314f68b93829cf8a2d954b4d382cdb5`.
It adds only `aella_vault_low_r2`, mapped to R3 native [7284,7348),
Blender 1–64, original 60 fps. It is nonlooping. No runtime activation,
common exporter, release workflow or production manifest changes are included.

## Recovered source and baseline choice

This preserves the previously unpublished original checkpoint
`e8eae64c0bb758d1dbc6711fbf30dc3fb7470576`, including both r1 BLENDs.
The r1 mantle file has the public r5 baseline's 82 Actions plus two mantle
Actions, so r2 preserves **all 84**, adding a single Action for 85 total.
It does not silently replace the newer canonical Jump 103-Action or Prone
108-Action sources. A future integrator must explicitly reconcile the new
Action with its chosen compatible canonical rig. The original mesh, weights,
rest skeleton, constraints, driver definitions, guards, attachment inverses,
source defaults, camera, textures, and NLA are preserved. Only original public
Arms/HK416 authoring content is present; no Soldier assets were introduced.

## Bounded hypothesis

The previous root-only version retained its fore-end grip through visible
release and clipped the left wrist guard by up to 42.60 degrees. The firing
hand did not show that defect. This revision preserves every weapon curve and
its evaluated track while authoring a support-hand ownership fade, free reach,
finger opening, and regrip. Source-pixel review puts release at 7291–7293 and
wrapping/regrip at 7330–7332. Ownership fades use 7291–7293 and 7331–7332.
The reaching hand's depth and hidden anatomy are explicit hypotheses. A
bounded existing elbow-pole translation (at most 0.12 rig metres in pose Y,
7327–7336) changes the elbow plane to remove late regrip wrist clipping;
no limits or drivers were widened. Finger properties use the established rig.

This is a technical repair while the r1 weapon hypothesis remains unlocked.
It does not establish the dependency-stage visual approval required to lock
weapon motion or certify a contact pose.

## Saved-source evidence

Fresh reopen checked 1,021 times, including 960 Hz samples and neighborhoods
±0.0001/0.001/0.01 frame around ownership-window endpoints. Quarter-frame full
skin evaluation covered 2,589,202 vertices; all evaluated bones/vertices are
finite and all drivers valid. Weapon matrices are exactly unchanged from r1.
Worst wrist-position residual: 0.000566 mm. Fully attached wrist-guard residual:
0 degrees. Minimum free-wrist margin: 2.01 degrees. At the release endpoint,
positions differ 0.00546 mm across ±0.0001 frame, with zero measured quaternion
angle; regrip endpoint is zero in that same numerical check. These are sampled
technical facts, not hand-surface, silhouette, full-trajectory or artistic proof.
Maximum sampled hand step is 3.71 mm per 1/16 frame during return; speed and
visible plausibility still require the complete fixed-camera preview.

`discrete_switch_evaluation.json` retains a rejected experiment: compensating
only at stored keys with discrete ownership produced a 52.9 mm between-key
jump. Continuous inverse-compensated fades replace that family. The original
rejected binary remains locally preserved, not the candidate for review.

## Reproduction

Use Blender 4.3.2, a fresh checkout, factory startup and disabled auto-execution.
The author refuses to overwrite its output. No embedded Text is executed.

    blender -b --factory-startup --disable-autoexec assets/authoring/mantle/aella_mantle_r1.blend --python-exit-code 1 --python assets/authoring/mantle/r2/author_low_vault.py
    blender -b --factory-startup --disable-autoexec assets/authoring/mantle/r2/candidate/aella_mantle_r2.blend --python-exit-code 1 --python assets/authoring/mantle/r2/verify_low_vault.py -- --output /tmp/r2-fresh-evaluation.json
    python -m unittest discover -s assets/authoring/mantle/r2 -p 'test_*.py'

The first command requires relocating the committed candidate output directory
to a separate evidence location first, or running against an isolated source
checkout without generated candidate outputs. Never overwrite an original.
`report_contract.py` is the actual verification gate. Tests include the actual
rejected switch report and discriminating malformed evidence controls.

No rendering has been performed for this checkpoint. Only a genuine fixed-camera
Eevee viewport preview may establish visible results; non-Eevee methods are not
permitted. One-hand mantle and roof-climb remain unchanged diagnostic r1 work.
