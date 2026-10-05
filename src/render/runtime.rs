//! The winit presentation bridge. Acquisition precedes CPU recording and input
//! consumption; final submission includes every queued PNG readback before exit.
use super::{BackendSelection, WgpuRenderer};
use crate::{
    draw::{facade, Renderer},
    platform::window::{FrameHooks, FrameStart},
};
use std::sync::Arc;
use winit::window::Window;

/// Synchronous factory for `platform::window::run`'s window-created callback.
/// The renderer retains the window Arc for the lifetime of its surface.
pub fn create_frame_hooks(
    window: Arc<Window>,
    selection: BackendSelection,
    force_fallback: bool,
) -> Result<Box<dyn FrameHooks>, String> {
    let size = window.inner_size();
    let scale = window.scale_factor();
    let renderer = pollster::block_on(WgpuRenderer::new_windowed(
        window,
        selection,
        force_fallback,
    ))?;
    Ok(Box::new(DrawHooks {
        renderer,
        width: size.width,
        height: size.height,
        scale,
        recording: false,
    }))
}

trait FrameRenderer: Renderer {
    fn prepare(&mut self, width: u32, height: u32) -> Result<bool, String>;
}
impl FrameRenderer for WgpuRenderer {
    fn prepare(&mut self, width: u32, height: u32) -> Result<bool, String> {
        self.prepare_frame(width, height)
    }
}

struct DrawHooks<R> {
    renderer: R,
    width: u32,
    height: u32,
    scale: f64,
    recording: bool,
}
impl<R: FrameRenderer> FrameHooks for DrawHooks<R> {
    fn resize(&mut self, width: u32, height: u32, scale_factor: f64) -> Result<(), String> {
        if self.recording {
            return Err("cannot resize during a recorded frame".into());
        }
        if !scale_factor.is_finite() || !(scale_factor as f32).is_finite() || scale_factor <= 0. {
            return Err("DPI scale must be finite and positive".into());
        }
        // Store even minimized extents; surface configuration happens only when
        // the next nonzero frame is acquired, never during a resize callback.
        self.width = width;
        self.height = height;
        self.scale = scale_factor;
        Ok(())
    }

    fn begin_frame(&mut self, width: f32, height: f32) -> Result<FrameStart, String> {
        if self.recording {
            return Err("begin_frame called before completing the previous frame".into());
        }
        if self.width == 0 || self.height == 0 {
            return Ok(FrameStart::Skip);
        }
        if !width.is_finite() || !height.is_finite() || width <= 0. || height <= 0. {
            return Err("logical frame extent must be finite and positive".into());
        }
        if !self.renderer.prepare(self.width, self.height)? {
            return Ok(FrameStart::Skip);
        }
        facade::begin_frame(self.width, self.height, self.scale)?;
        facade::set_backend_info(self.renderer.info().clone());
        self.recording = true;
        Ok(FrameStart::Ready)
    }

    fn end_frame(&mut self) -> Result<(), String> {
        if !std::mem::take(&mut self.recording) {
            return Err("end_frame called without a ready frame".into());
        }
        let list = facade::take_draw_list()?;
        // submit finishes all ordered captures synchronously. A write/map/GPU
        // error escapes to winit, including on the application's final frame.
        self.renderer.submit(&list)?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::draw::{BackendInfo, Command, DrawList, FrameOutput, TextDimensions};
    use std::collections::VecDeque;

    struct FakeRenderer {
        info: BackendInfo,
        readiness: VecDeque<Result<bool, String>>,
        prepared: Vec<(u32, u32)>,
        submitted: Vec<DrawList>,
        submission_error: Option<String>,
    }
    impl FrameRenderer for FakeRenderer {
        fn prepare(&mut self, width: u32, height: u32) -> Result<bool, String> {
            // The recorder must not exist while a surface is being acquired.
            assert!(facade::current_camera().is_err());
            self.prepared.push((width, height));
            self.readiness.pop_front().unwrap_or(Ok(true))
        }
    }
    impl Renderer for FakeRenderer {
        fn info(&self) -> &BackendInfo {
            &self.info
        }
        fn measure_text(&self, _: &str, _: f32) -> Result<TextDimensions, String> {
            Ok(TextDimensions::default())
        }
        fn submit(&mut self, list: &DrawList) -> Result<FrameOutput, String> {
            self.submitted.push(list.clone());
            self.submission_error
                .take()
                .map_or(Ok(FrameOutput::default()), Err)
        }
    }
    fn hooks() -> DrawHooks<FakeRenderer> {
        DrawHooks {
            renderer: FakeRenderer {
                info: BackendInfo {
                    requested: "dx12".into(),
                    backend: "Dx12".into(),
                    adapter: "CPU-only lifecycle fixture".into(),
                },
                readiness: VecDeque::new(),
                prepared: Vec::new(),
                submitted: Vec::new(),
                submission_error: None,
            },
            width: 320,
            height: 180,
            scale: 2.,
            recording: false,
        }
    }

    #[test]
    fn acquisition_precedes_recording_and_ready_frame_uses_physical_extent() {
        let mut hooks = hooks();
        assert_eq!(hooks.begin_frame(160., 90.).unwrap(), FrameStart::Ready);
        assert_eq!(facade::backend_info().unwrap(), hooks.renderer.info);
        facade::draw_rectangle(1., 2., 3., 4., facade::WHITE);
        facade::capture_png(None, "final.png");
        hooks.end_frame().unwrap();
        assert_eq!(hooks.renderer.prepared, [(320, 180)]);
        assert_eq!(hooks.renderer.submitted.len(), 1);
        let list = &hooks.renderer.submitted[0];
        assert_eq!((list.width, list.height), (320, 180));
        assert!(
            matches!(list.commands.last(), Some(Command::Capture { path, .. }) if path.to_str() == Some("final.png"))
        );
        assert!(facade::current_camera().is_err());
    }

    #[test]
    fn timeout_does_not_start_recorder_and_retry_acquires_again() {
        let mut hooks = hooks();
        hooks.renderer.readiness.extend([Ok(false), Ok(true)]);
        assert_eq!(hooks.begin_frame(160., 90.).unwrap(), FrameStart::Skip);
        assert!(facade::current_camera().is_err());
        assert!(hooks.renderer.submitted.is_empty());
        assert_eq!(hooks.begin_frame(160., 90.).unwrap(), FrameStart::Ready);
        hooks.end_frame().unwrap();
        assert_eq!(hooks.renderer.prepared.len(), 2);
        assert_eq!(hooks.renderer.submitted.len(), 1);
    }

    #[test]
    fn minimized_frame_skips_acquisition_until_resized() {
        let mut hooks = hooks();
        hooks.resize(0, 0, 2.).unwrap();
        assert_eq!(hooks.begin_frame(0., 0.).unwrap(), FrameStart::Skip);
        assert!(hooks.renderer.prepared.is_empty());
        hooks.resize(800, 600, 1.25).unwrap();
        assert_eq!(hooks.begin_frame(640., 480.).unwrap(), FrameStart::Ready);
        hooks.end_frame().unwrap();
        assert_eq!(hooks.renderer.prepared, [(800, 600)]);
    }

    #[test]
    fn fatal_acquisition_error_leaves_recorder_unstarted() {
        let mut hooks = hooks();
        hooks
            .renderer
            .readiness
            .push_back(Err("surface recovery failed".into()));
        assert_eq!(
            hooks.begin_frame(160., 90.).unwrap_err(),
            "surface recovery failed"
        );
        assert!(facade::current_camera().is_err());
        assert!(hooks.renderer.submitted.is_empty());
    }

    #[test]
    fn repeated_begin_end_and_mid_frame_resize_are_rejected() {
        let mut hooks = hooks();
        hooks.begin_frame(160., 90.).unwrap();
        assert!(hooks.begin_frame(160., 90.).is_err());
        assert!(hooks.resize(100, 100, 1.).is_err());
        hooks.end_frame().unwrap();
        assert!(hooks.end_frame().is_err());
        assert_eq!(hooks.renderer.prepared.len(), 1);
        assert_eq!(hooks.renderer.submitted.len(), 1);
    }

    #[test]
    fn final_capture_error_is_propagated_after_consuming_recording_once() {
        let mut hooks = hooks();
        hooks.renderer.submission_error = Some("write capture final.png: denied".into());
        hooks.begin_frame(160., 90.).unwrap();
        facade::capture_png(None, "final.png");
        assert_eq!(
            hooks.end_frame().unwrap_err(),
            "write capture final.png: denied"
        );
        assert!(facade::current_camera().is_err());
        assert!(hooks.end_frame().is_err());
        assert_eq!(hooks.renderer.submitted.len(), 1);
    }
}
