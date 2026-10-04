# Jump r7 independent fixed-view visual review

Date: 2026-10-04. Reviewer: Hal's independent remaining-movement review lane.

## Conclusion

**PASS at the requested approximately 80% visible-motion match level, as a qualitative reviewer judgment in the delivered fixed first-person view.**

This is an independent visual judgment, not a computed similarity percentage, not an Elara score, and not a change to any existing gallery score. Preserve the current r7 candidate rather than revise protected takeoff/air from uncertain one-point residuals. Proceed to the separately required export/load/runtime checks.

The earlier numerical-support ceiling concerns the proposed automatic multi-landmark calculation only. It does **not** block useful visual review, impose complete 3D reconstruction, or change the user's visible-motion acceptance scope. Hidden muzzle position, other camera angles and unseen anatomy are not failures unless they cause a visible problem in the delivered view.

## Pinned evidence and inspection

- Source blend revision: PR20 `4363837e46ee89b5ca8baa1b5c08e1e3f81cac91`.
- Blend SHA-256: `a2c4b2bbe98da1a608450bba92404cb39008eae5861bcf8fc3f5d2f978df0e3b`.
- Existing paired preview: https://rhs059.github.io/rust_duty_updates/media/jump_animation.mp4
- Paired MP4 SHA-256 independently checked: `9584dd3e3c852ff810caa608d3c7afd003b19d3b5548302a326e6d87c0f29b3e`.
- 100 frames, 60 fps, duration 1.666667 seconds; source n4014–4113, inclusive, equivalent to [4014,4114). Original 1x mapping retained.
- In the cloud browser, played the existing complete paired clip at 1x and then 0.5x, inspecting sequential playback captures through the end and verifying each playback rate and completed time.
- Additionally inspected all 100 native paired frames in chronological 10-frame contact sheets. The smaller sheets supplement the full-view playback captures; no newly rendered candidate or edited animation was used.
- Reference is above, candidate below. The reference includes world/camera movement; the candidate camera is fixed as delivered. Review concentrates on visible foreground weapon movement, not reproducing the reference world arc.

## Timestamped findings

Times below are relative to the paired clip start; source n = 4014 + 60*t.

- **0.000–0.317 s, n4014–4033: ready lead-in.** Candidate holds a stable ready pose. Reference has mild residual sway. No candidate entry snap is evident.
- **0.317–0.500 s, n4033–4044: takeoff.** The candidate's visible weapon lag and rotation develop in the correct order with the source departure. The foreground motion reads as the same kind of jump response; the supporting hand follows the weapon without an obvious detach in this view.
- **Approximately 0.47–0.55 s, around n4042–4047: takeoff/early-air extremum.** Candidate motion looks slightly stronger/deeper than the source at the receiver region. This is a minor visible difference, consistent with the bounded one-point diagnostic, not sufficient evidence to reopen the protected takeoff/air curves.
- **0.500–0.883 s, n4044–4067: air and return toward impact.** The path reverses smoothly and the weapon lifts/settles toward the landing phase in the source's visible sequence. No obvious pose reset appears at the takeoff/air or air/landing transition in the inspected playback and native sequence.
- **0.883–1.367 s, n4067–4096: landing/compression/recovery.** The downward response and return are coherent and close to the source's visible progression. The recovery reads as one continuous event rather than a reset to idle. No clear one-frame pop or visible support-hand release was found.
- **1.367–1.650 s, n4096–4113: ready tail.** Candidate becomes exactly still while the source retains small motion. This is the clearest remaining difference, but it is a nonblocking ready-hold limitation at this fidelity target. If later polish is requested, address it through the intended idle/recovery integration behavior, without adding unrelated camera motion or changing current source timing.

## Scope and remaining gates

The pass covers visible weapon movement, its apparent rotation/path and the visible hand relationship from the delivered camera. It does not certify hidden geometry, whole-body motion, other viewpoints, exact physical transforms or an unavailable muzzle track. Those are scope limits, not reasons to fail this visual review.

No game-runtime capture, export reload test or runtime-triggered landing/air-hold behavior was tested in this review. Those functional checks remain required in the owning integration lane. A visual pass does not authorize merging or overwrite Elara's prior r6=78, the current gallery history, or other reviewers' decisions.
