//! Exact compile-time control for a matched resident-versus-CPU experiment.
//! This is not selected by environment variables or an unrecorded runtime flag.
pub const ENABLED: bool = true;
pub const fn identity() -> &'static str {
    if ENABLED {
        "vertex_lit_skin_v1"
    } else {
        "cpu_vertex_reference_v1"
    }
}
