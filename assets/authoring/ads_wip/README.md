# Active ADS v4 WIP integration

The user requested all current animation work in the playable build before further
fidelity review. `layers.ads_walk=receiver_v4_wip` activates this current approximation.

The original source contract and numerical oracle are retained unchanged here for
provenance; their historical diagnostic-only labels describe the earlier review
state, not the current user-authorized WIP inclusion decision.

Runtime implements the author-provided frozen receiver mapping in
`src/authored_walk.rs`: convert the native HIP delta to camera space using the
existing exact diag(-1,1,-1) root, attenuate by0.40, halve only vertical target
displacement for fully lateral movement, and solve optical roll/depth from the
frozen receiver point. One rigid transform moves the whole evaluated aimed
assembly. No IK, camera adjustment, new mesh, or per-frame fit is introduced.

`src/authored_ads.rs` samples the existing ADS47 entry/exit over0.30 visual seconds,
equivalent to the author's retimed native0.30-second Actions without another
binary source upload. Original source samples, endpoints and files remain present;
gameplay readiness/accuracy timing does not change. The phase clock accumulates
`dt - 0.15 * integral(ADS weight dt)` exactly over each source transition interval,
so entering or leaving ADS cannot reset its existing walking phase.

Held-aim sight/contact has independent source-diagnostic evidence. Reference
cadence/shape, partial ADS, diagonals, rapid transitions and real Windows gameplay
remain WIP and may need refinement. Their review does not block inclusion.
