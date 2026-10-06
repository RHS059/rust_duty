//! Later finite source-driven corroboration, never an original capture receipt.
#[cfg(feature = "wgpu-runtime")]
fn main() {
    if let Err(error) = vector_range::render::finite_warp_probe::run(std::env::args().skip(1)) {
        eprintln!("finite_warp_probe: {error}");
        std::process::exit(1);
    }
}
#[cfg(not(feature = "wgpu-runtime"))]
fn main() {
    eprintln!("finite_warp_probe requires --no-default-features --features wgpu-runtime");
    std::process::exit(1);
}
