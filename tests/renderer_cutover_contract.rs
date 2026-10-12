//! CPU-only integration checks at the executable/renderer boundary. These do
//! not open a window or graphics device and are not native DX12 evidence.

use std::process::Command;

fn rejected_launch(args: &[&str], diagnostic: &str) {
    let output = Command::new(env!("CARGO_BIN_EXE_vector-range"))
        .arg("--no-update")
        .args(args)
        .output()
        .expect("run the compiled game entry point");
    assert_eq!(output.status.code(), Some(1), "{args:?}: {output:?}");
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains(diagnostic), "{args:?}: {stderr}");
    assert!(
        !stderr.contains("renderer requested="),
        "rejected launch initialized a renderer: {stderr}"
    );
}

#[test]
fn executable_rejects_invalid_or_ambiguous_selection_before_window_creation() {
    // Parser unit tests alone cannot establish that main honors their errors
    // before selecting its default backend or creating a native window.
    rejected_launch(&["--renderer=dx12", "--renderer=auto"], "only once");
    rejected_launch(&["--renderer=unsupported"], "unknown renderer");
    rejected_launch(&["--renderer"], "--renderer requires a value");
    rejected_launch(
        &["--renderer=dx12", "--force-fallback-adapter=false"],
        "boolean flag and takes no value",
    );
}

#[cfg(not(feature = "wgpu-runtime"))]
#[test]
fn executable_cannot_satisfy_explicit_dx12_with_the_legacy_build() {
    rejected_launch(
        &["--renderer=dx12"],
        "requested renderer is unavailable; build with wgpu-runtime",
    );
}

#[cfg(not(feature = "legacy-macroquad"))]
#[test]
fn executable_cannot_satisfy_explicit_legacy_with_the_wgpu_build() {
    rejected_launch(
        &["--renderer=gl"],
        "legacy OpenGL is unavailable; build with legacy-macroquad",
    );
}

#[cfg(all(feature = "wgpu-runtime", target_os = "linux"))]
#[test]
fn actual_dx12_constructor_fails_closed_when_that_api_is_not_compiled() {
    use vector_range::render::{BackendSelection, WgpuRenderer};

    assert!(!wgpu::Instance::enabled_backend_features().intersects(wgpu::Backends::DX12));
    for force_fallback in [false, true] {
        let result = pollster::block_on(WgpuRenderer::new_headless(
            64,
            64,
            BackendSelection::Dx12,
            force_fallback,
        ));
        let error = result.err().expect("DX12 must not become another API");
        assert!(
            error.contains("renderer dx12 initialization failed"),
            "{error}"
        );
        assert!(
            error.contains("Backends(DX12) is not available in this build"),
            "{error}"
        );
    }
}

#[cfg(feature = "wgpu-runtime")]
#[test]
fn zero_extent_constructor_rejects_before_backend_or_fallback_selection() {
    use vector_range::render::{BackendSelection, WgpuRenderer};

    for (width, height) in [(0, 0), (0, 64), (64, 0)] {
        for selection in [BackendSelection::Dx12, BackendSelection::Auto] {
            for force_fallback in [false, true] {
                let result = pollster::block_on(WgpuRenderer::new_headless(
                    width,
                    height,
                    selection,
                    force_fallback,
                ));
                assert_eq!(
                    result
                        .err()
                        .expect("zero extent must not initialize a device"),
                    "renderer extent must be nonzero"
                );
            }
        }
    }
}
