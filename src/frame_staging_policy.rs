//! One-line counterfactual for the source-bound staging experiment.
//! Destination-buffer reuse is controlled independently.
pub const STAGING_REUSE_ENABLED: bool = true;

pub fn identity() -> &'static str {
    if STAGING_REUSE_ENABLED {
        "bounded_staging_v1"
    } else {
        "queue_write_staging_v1"
    }
}
