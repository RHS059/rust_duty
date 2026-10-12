//! One-line, source-bound counterfactual for the destination-buffer experiment.
//! Keep diagnostics and all other production inputs identical in the control.
pub const REUSE_ENABLED: bool = true;

pub fn identity() -> &'static str {
    if REUSE_ENABLED {
        "bounded_reuse_v1"
    } else {
        "immutable_per_frame_v1"
    }
}
