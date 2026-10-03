# Original pose-equivalence rubric: preserved v01 result

Status: original mean-pose and grip-anchor category fails its positional criteria. No80% overall pose-equivalence result was established or claimed. The subsequent motion-only contract is a separate scope with explicit task rationale and does not overwrite this result.

The baseline native HK416 and reference shotgun have different visible hand/weapon triangle proportions. A single best constant similarity registration to primary forward mean landmarks leaves65.7px mean residual (muzzle81.4px,receiver40.5px,cuff-region75.2px). Translation-only leaves71.6px. The baseline anatomical hand_l point was the early proxy; it is documented as such and is replaced only in later motion-only scoring by an actual visible cuff surface anchor.

v01 full-window primary R2 metrics with frozen scale, one global translation and one phase:

- Forward: mean pose72.01px;21.8% within0.10L; centered translation RMS6.10px; all six XY amplitude comparisons pass; uncentered angular RMS8.46° fails5° threshold
- Backward: mean pose65.07px;36.6% within0.10L; centered translation RMS7.03px; receiverX and support-regionX/Y amplitudes fail; angular amplitude6.89° versus10.66° fails20%/2° tolerance
- Left: mean pose74.54px;5.8% within0.10L; centered translation RMS4.69px; support-regionY amplitude21.34px versus36px fails; uncentered angular RMS8.24° fails5° threshold
- Right was not yet in v01 capture and is not assigned a fabricated score

Exact numeric diagnostics are in candidate_v01_review_metrics.json. These were measured before the surface-cuff correction, and remain historical anatomical-point proxy diagnostics, not the final homologous-cuff motion result. The original25-point mean-pose category was never divided into invented post-hoc partial weights; hence no numerical overall percentage is assigned. Transition response and runtime integration remained untested here. Firing wrist is offscreen in the reference, so it earned no positional score.
