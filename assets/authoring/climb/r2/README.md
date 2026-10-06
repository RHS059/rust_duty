# High-obstacle climb: source diagnostics

This directory contains non-rendering diagnostics of the unchanged r1 source. **No r2 Action or Blender candidate has been authored.** `aella_climb_roof_r1` remains the stable source ID; the intended feature is climbing an obstacle taller than the player, not a vehicle-specific mechanic.

Source: `../aella_climb_r1.blend`, SHA256 `baca19e147f8384bdebcb78b54837ad559b4882a3992deab503190f21040d593`. The 83 Actions are the 82-Action r5 baseline plus this original high-obstacle Action. Frame 1–76 maps to native source 8507–8582 at 60 fps, with source PTS `native_frame * 256`, time base 1/15360. Reference SHA256: `491a1729aa0f32373025d35fff86da76c6c1c8f057c0c553d0fbb5fb6226ff46`.

## Findings and limits

- A fresh quarter-frame evaluation (301 samples) detects left guarded-goal orientation discrepancy up to 47.5413 degrees at native 8531. The wrist target position remains within 0.001409 mm. This is a diagnostic discrepancy, not proof of visible contact failure.
- The right wrist has a 14.7078 mm target miss in the hidden middle, where reach margin reaches −14.7056 mm. A sampled 4 cm shoulder correction resolves that numerical defect. Hidden mechanics are unscored and do not block fixed-camera visual acceptance. No correction was saved.
- Bounded shoulder and elbow-plane probes reduce some visible-phase discrepancies but do not resolve the whole transition: combined tests still leave 5.66 degrees at native 8522 and 5.05 degrees at 8524. We stopped rather than expanding rig limits or continuing open-ended parameter search.
- Native reference 8518 shows hands holding the raised rifle. By 8530 the rifle is low in frame. The middle is occluded/out of view; surface contact, body trajectory, and first physical release cannot be inferred from it. The weapon begins returning around 8560. No hidden motion is scored as a fidelity improvement.

The earlier evaluator recorded quaternion distances above 180 degrees. `shortest_angle_summary.json` explicitly normalizes these to `min(theta, 360-theta)`; the raw evidence is retained. No pose or acceptance threshold was changed to improve the report.

## Next review

Obtain a genuine foreground Eevee viewport witness of the unchanged r1 at the fixed review camera before proposing a larger visible left-hand correction. Keep all 76 native frames and prime materials outside the retained map. This request follows the already queued vault r3 capture. No new render has been started here, and no visual score, contact approval, runtime integration, or export pass is claimed.

`probe_existing_controls.py`, `probe_elbow_swivel.py`, and `probe_combined_visible.py` evaluate temporary poses without saving source or rendering. They preserve the original file. `evaluate_baseline.py` accepts `-- --output <directory>`. Run with Blender 4.3.2, one thread, factory startup and disabled autoexec. These probes are diagnostics, not chosen animation curves.
