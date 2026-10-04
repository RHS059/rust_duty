# Forward ADS v9 runtime handoff

This is an unreviewed WIP runtime extension of the exact PR23 source, commit `f6c0d0f9efc3c8b78f63c6b3e292326e476f30b1`. It uses the existing r5 native HIP clips. Do not loop the 126-frame comparison-bake Actions or import them as locomotion loops. No new runtime animation pack is necessary.

## Exact authored forward case

The source is `ads_v9_depthphase_public47_hipr5_diagnostic.blend`, SHA256 `094c54c25815126479ca30051a15b8e8dd8f0b4f7bab0767ba96599534652c62`. It is the lossless compact encoding of the rendered source; the decoded native stream is identical. Public ADS47 held pose and unchanged HIP r5 `hip_walk_forward_r5` supply all pose data. The latter has 38 unique frames at 60 Hz, with a repeated endpoint at frame39.

Maintain one accumulated native phase. Sample forward at that phase and at the same phase plus19 native frames. The auxiliary lookup is derived from the primary clock, never a separately advancing clock. Full forward ADS advances the native clock at4/5 of wall time. The gallery's23/240-second reference offset is comparison alignment only; do not add it to gameplay phase.

Let W0 be the ready weapon global, H the fully aimed weapon global, B[i] the fully aimed bone globals, W the primary forward weapon global, N[i] the primary forward bone globals, and Whalf the half-period forward weapon global. All are evaluated native poses in the existing canonical asset basis. Compute D=W*inverse(W0) and Dhalf=Whalf*inverse(W0).

For each delta, change to camera coordinates by R*D*R, where R=diag(-1,1,-1,1). Attenuate translation by.40 and shortest-path quaternion rotation from identity by.40. Apply this rigid delta to fixed receiver point p0=(2.8157956e-8,-.040691406,-.2020175). If the resulting primary point is a and secondary point is b, use u=u0+.25*(a.x/-a.z-u0), v=b.y/-b.z, where u0=p0.x/-p0.z. Compute theta=wrapped(atan2(v,u)-atan2(p0.y,p0.x)), dz=-hypot(p0.x,p0.y)/hypot(u,v)-p0.z. The camera offset is rotationZ(theta) plus translation(0,0,dz); convert it back with R*offset*R.

The output weapon anchor is A=offset*H. Each ideal bone output is A*TRSblend(inverse(H)*B[i],inverse(W)*N[i],.15). TRSblend decomposes both relative matrices, linearly interpolates translation and scale, and shortest-path slerps the quaternions. This is interpolation of complete evaluated globals in weapon-relative space, followed by the shared anchor. Do not rerun IK after this composition. Reconstruct parent-local transforms only after all output globals are available.

The rigid weapon and magazine preserve their held weapon-relative transforms: outputActor[j]=A*inverse(H)*heldActor[j]. The native actor relative transforms are also included in the oracle so any practical interpolation residue is measurable. No attachment or camera transform is changed.

## Frozen WIP extension beyond the rendered forward case

Author and integrator agreed this extension for the current WIP build. The machine-readable contract is `v9_runtime_policy.json`. These are explicit engineering fallbacks for immediate inclusion, not claims that diagonals or transitions were rendered or reviewed. Use the existing eased normalized direction weights in forward/back/left/right order, with f=forwardWeight and lateral=leftWeight+rightWeight.

- Pure backward, left and right retain the existing v4 spatial map, including the existing lateral vertical attenuation and held ADS articulation.
- Compute the current v4 optical offset from the existing blended primary HIP pose. Compute v9 independently from pure forward primary/half-period poses. Interpolate the two rigid optical offsets with f, using quaternion slerp and translation lerp. Pure forward is exactly v9; f=0 is exactly the v4 spatial fallback. Do not phase-shift an already mixed four-direction pose.
- Apply the current partial-ADS interpolation between the raw HIP delta and that aimed optical offset, then the existing walk-envelope attenuation. Preserve the existing run crossfade, ownership, and interruption behavior.
- The relative articulation weight is walkEnvelope*((1-aim)+.15*aim*f). Its target remains the existing blended primary HIP complete pose. At full pure-forward ADS this is the authored.15; at full nonforward ADS it is zero. At aim0 it is the existing HIP layering weight.
- The continuous native phase rate is1-aim*(.15+.05*f). Thus full forward ADS is.80, full nonforward ADS is.85, and hip is1. Integrate this rate over each committed interval; never recompute elapsedTime*currentRate. Preserve the committed-pose cache, and do not advance phase from render queries. The integration method and partition error must be tested by the common-runtime owner.
- If four-direction clips are unavailable, retain the existing legacy mapping and clock. This source does not invent a forward identity from a pose or fall back to a comparison bake.

## Oracle and known failures

`v9_complete_pose_runtime_oracle.json` contains26 native pure-forward samples, including fractional loop neighborhoods. It records the72 canonical deform bones, two actors, held and primary globals, primary/secondary deltas, ideal output globals, and the saved PR23 output globals. Matrices are row-major arrays with column-vector multiplication, in metres. Asset coordinates are F*BlenderWorld, F=(x,z,-y). F*sourceCamera differs from R by at most8.75e-8. Apply the game's existing model root once for display, not inside these oracle globals.

The original26-case optical mapping oracle remains unchanged. The complete-pose fixture adds the articulation witnesses. The existing source bake still fails its unchanged1e-5 deform-matrix limit: its earlier501-sample maximum is4.10825e-5; this26-case subset reaches3.04133e-5. The rigid-actor subset maximum is3.57628e-7. Ideal globals are the intended source-driven composition; saved globals retain the actual bake discrepancy rather than silently replacing it.

Existing source measurements also retain a1.3079mm connected-joint anchor residue versus.3692mm in the input, and.015495mm saved hand translation residue. These are limitations to inspect and improve after inclusion. No visual-contact, full-clip, runtime, or reference-match approval is implied.

For runtime validation, compare all72 ideal global bone transforms and two actors at the oracle phases, report local-TRS reconstruction error separately, check forward/native and auxiliary wrap neighborhoods, then test aim and direction changes, simultaneous ADS/walk fade to run, and rapid interruptions. The runtime owner supplies build and playable evidence. Failed quality checks stay attached to the WIP rather than withholding it from the game.
