# Low vault r3: bounded free-hand correction

Status: **diagnostic, awaiting genuine Eevee viewport review**. R2's rendered
visible failure is preserved; technical validity is not artistic acceptance.

Candidate: `candidate/aella_mantle_r3.blend`
SHA-256: `6b95bdcdfa78e8127ef4b4fa5ac88e4cf9a0654bd0a1271c9916b903f6ee4e79`
Action: `aella_vault_low_r3`. Blender 1–64 maps to R3 native [7284,7348),
original 60 fps. No retiming, runtime hooks, common exporter or camera changes.

## Observed residual and allowed change

Independent review inspected all 64 source/candidate pairs from PR37's genuine
Eevee capture. R2 held a large open palm in the upper-left through the middle,
including native 7315 where the source hand was absent. Its visible finger
opening was also late: candidate 10–11 still wrapped, opening 12–14, versus
source opening 8–9 and separation by 10. Regrip around frame 48 matched the
source's broader 47–49 bracket. See `review_basis/` for the exact review and
full-resolution witnesses; no score or percentage was invented.

Only the free-hand path/orientation and finger-opening lead change. The hand
now travels down/left, rolls away from the raised-palm hypothesis, and returns
to the same regrip. Finger opening starts one native frame earlier, without
changing the overall source clock or regrip window. Hidden depth/contact remain
explicit hypotheses. All 87 older Actions, including r2 and separate one-hand
r3, are preserved; the new Action makes 88. The input is the preserved one-hand
source, not a silent canonical Jump/Prone replacement.

Original weapon curves and sampled matrices, rest, geometry, materials, camera,
constraints, driver definitions, guards, attachment inverses and NLA remain
unchanged. The existing bounded regrip elbow-plane correction is retained.

## Evidence and limits

Fresh source checks cover 1,021 evaluated times, including 960 Hz and near-switch
samples, and 2,589,202 full-skin vertex samples. The pre-label-only source passed
with finite skin/bones, valid drivers, exact weapon-matrix equality, maximum
wrist-target residual 0.000746 mm, zero attached guard residual and minimum free
wrist margin 2.77 degrees. A stale inherited preview-status label was corrected
without changing any Action curve or source structure; the final exact source
is reopened and checked separately in `candidate/evaluation.json`.

`sample_hand_projection.py` uses evaluated skinned hand vertices and records
camera-space bounds. It shows the main native 7315 hand hypothesis out of view,
while the early and regrip samples intersect the viewport. This is projection
support only: it does not prove renderer visibility, correct silhouette,
anatomical contact, complete trajectory or a reference-fidelity score. A real
new Eevee capture and complete visible review remain required.

`initial_spatial_diagnostic/` retains an intermediate source and its projection
failure: it hid the hand too early around 7296. It is not the current candidate.
The metadata-only prior bytes are retained locally; pose evidence is tied to
its stated SHA. R2 frame 1 also had a separate cold-material capture artifact;
no source change here attempts to repair that renderer issue.

## Reproduce

Use Blender 4.3.2, factory startup and disabled auto-execution. In a source-only
copy without generated candidate outputs, run `author_low_vault.py` on the exact
input SHA from `design.json`. The author refuses to overwrite existing output.
Reopen with `verify_low_vault.py --output NEW_REPORT.json`, and optionally run
`sample_hand_projection.py --output NEW_PROJECTION.json`. Only foreground
rendered Eevee viewport may create the subsequent visual witness.
