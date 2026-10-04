# Jump r7: independent fixed-camera visible-motion review

Date: 2026-10-04. Reviewer: Aella, independent of Hal's animation authorship.
Status: **complete-window frame review; subjective visual judgment, no computed
percentage and no replacement of Elara's assessment**.

## Acceptance scope

The user clarified that this animation is viewed from the current camera.
Judge the visible weapon path, apparent rotation, timing and visible hand contact.
Do not move the camera to improve a comparison. Hidden geometry, other viewpoints,
or an unavailable physical muzzle are not acceptance gates unless they cause an
artifact in this view. The mathematical module's unsupported L/axis/anchor clauses
remain honest measurement limits; they are not a new requirement for complete
3D reconstruction or a veto on visible-motion iteration.

## Evidence actually inspected

- Exact published paired MP4 SHA256
  `9584dd3e3c852ff810caa608d3c7afd003b19d3b5548302a326e6d87c0f29b3e`:
  1280x1760, 100 frames at60/1fps, source4014–4113, native model below source.
- Every full-view frame pair has now been inspected. The first57 were reviewed
  from independent original source/native images, including every landing frame;
  the remaining43 were inspected from the exact published paired MP4. The prior
  Colab input/report truthfully preserves the earlier57-pair review checkpoint.
- The exploratory rear-corner point was separately inspected on all100 native
  source/candidate crops. Actual Colab/local metrics remain unchanged.
- Normal/slow real-time playback is not claimed. Browser HTTPS review failed
  when its permission request was dismissed; local file URLs are unsupported in
  that browser. This review uses the ordered full-frame sequence and exact timing.

## Subjective finding

The visible sequence is close: initial lowering/roll, airborne return, landing
counter-motion/dip and recovery occur in the same broad order and timing. The
weapon stays visible and the reviewed sequence has no apparent reset, sudden
flip or support-hand detachment in this camera. Static weapon/optic geometry and
skin appearance differ; those differences are not mistaken for movement errors.

**Recommendation: retain r7 rather than request a speculative new revision.**
The reviewed visible frames do not supply a specific defect that warrants
changing the protected takeoff or airborne segments. This is a visual judgment,
not a claim that an algorithm measured an80% whole-weapon match. Elara's previous
r6=78 remains historical; this note does not overwrite that score or assign one
on her behalf.

The clearest remaining visible difference is the final ready hold: candidate
frames4096–4113 are perfectly still while the source continues small motion.
Treat a softer tail as optional polish for a bounded future test, not a reason
to distort the main jump sequence or alter its event timing now. World/camera
travel in the reference is separate from the candidate's fixed-camera weapon
animation and is not being matched by moving the review camera.

The exploratory point-pair baseline RMS is4.85px for landing/recovery and6.79px
for the whole window. This is consistent with the visual impression, but exact
cross-model component homology remains unverified. The largest16.56px residual
is near the stated usual16px annotation bound, so those numbers do not justify
an automatic correction or percentage. Future visible-motion reviews can proceed
without waiting for unavailable 3D evidence.
