# One-hand mantle r5: numerical correction, visual review pending

Status: **diagnostic**. Fresh saved-source numerical checks pass. There is no
new Eevee render, visual/contact approval, export or runtime validation yet.

Local candidate SHA-256:
`ce9e7f5aa89f47201b7a95ab8c731a40a82e6eb854264cfe7814de458879e1df`

Action: `aella_mantle_onehand_r5`. Input is the retained failed r4 source,
SHA-256 `f6d8cf85c065f703cfd7d480303568fad3ebba5246fc3068600f4804f3d703bb`.
All 88 input Actions remain unchanged; r5 adds one for 89. The authoring path
is recomputed from the unchanged original r3 Action, avoiding accumulated
correction or double blending. Failed r4 remains available and documented in
`../onehand_r4`.

## Bounded change and evidence

The first r4 solve clipped the attached left wrist by 22.753 degrees. A finite
40-pose shoulder-offset family could not repair it and was rejected. A second
20-pose barrel-axis roll family found that +30 degrees removed clipping at all
four failing witnesses, while keeping the actual receiver/muzzle projections
within 0.00056 pixel. The r5 correction tapers that roll adjustment into and out
of f20–44. It changes no wrist guard, joint rest, mesh or camera. The full skin,
fingers and contours must still be judged in genuine Eevee pixels.

The initial correction now reaches its intended path by f11 instead of f16,
on the same source clock. Frame 11's evaluated receiver-axis target is near
(810,665) and muzzle near (660,475) in the unchanged 1280x720 camera. These are
functional barrel-axis landmark targets on the supplied geometry, not claims
that unlike gun optics or silhouettes are identical to the reference.

The support hand continuously rejoins by f65. The reviewer clarified that the
protected ending means the settled pose: weapon/camera stay unchanged on
f85–96, support recovery may change through f88, and the complete f89–96 hold
stays identical. The original 96-frame R3 [7787,7883) map remains 60/1 fps.

## Fresh saved-source checks

- 1,563 evaluated times, including 1/16-frame samples and switch neighborhoods
- 3,899,154 finite evaluated skin vertices; all bones finite and drivers valid
- All 88 prior Actions, rest/geometry/weights, constraints/guards, materials,
  drivers and NLA preserved
- Protected complete-pose matrix delta: at most 8.95e-7
- Protected weapon matrix delta: at most 5.97e-8
- Left/right attached guard residual: 0 degrees
- Minimum free-wrist guard margin: 6.454 degrees
- Maximum wrist-to-rig-target error: 0.000516 mm
- Fully attached support at f65; no detected sampled switch discontinuity
- Nine pure contract unit tests passed

`evaluation_summary.json` is the exact small saved-source numerical summary.
`bounded_probe_summary.json` records both failed and successful diagnostic
families. Passing these checks does not approve finger surface contact,
anatomy, appearance, source fidelity, retarget/export behavior or gameplay.

## Reproduce

Use Blender 4.3.2 with factory startup, disabled autoexec and one thread.
Run `author_correction.py` against the exact local r4 input with `--output
LOCAL_R5.blend` and `--integrity-dir PATH_TO_assets/authoring/locomotion_directional/r5`.
The author refuses an existing output. Reopen the exact saved BLEND with
`verify_correction.py --output LOCAL_EVALUATION.json --authoring-dir OUTPUT_PARENT
--integrity-dir PATH_TO_R5_HELPERS`. Run the pure tests with `python -m unittest
discover -s assets/authoring/mantle/onehand_r5 -p 'test_*.py'`.

Only original code, tests, design and small summaries are published. The local
BLEND, private source assets, extracted meshes and inherited control data are
not uploaded. Local save/reopen has been verified; no external private-BLEND
recovery or complete pipeline claim is made. Elara's frame-based review is next.
