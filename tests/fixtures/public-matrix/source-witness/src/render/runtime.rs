//! The winit presentation bridge. Acquisition precedes CPU recording and input
//! consumption; final submission includes every queued PNG readback before exit.
use super::{BackendSelection, WgpuRenderer};
use crate::{
    draw::{facade, Command, Renderer},
    frame_performance::{BoundaryReason, CpuFrameStage},
    frame_performance_session::{self as performance, log_completion},
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
            log_completion(performance::present_failure());
            return Err("begin_frame called before completing the previous frame".into());
        }
        performance::begin_cpu_frame(self.width, self.height);
        if self.width == 0 || self.height == 0 {
            log_completion(performance::present_skipped());
            return Ok(FrameStart::Skip);
        }
        if !width.is_finite() || !height.is_finite() || width <= 0. || height <= 0. {
            log_completion(performance::present_failure());
            return Err("logical frame extent must be finite and positive".into());
        }
        match self.renderer.prepare(self.width, self.height) {
            Ok(true) => {}
            Ok(false) => {
                log_completion(performance::present_skipped());
                return Ok(FrameStart::Skip);
            }
            Err(error) => {
                log_completion(performance::present_failure());
                return Err(error);
            }
        }
        performance::begin_cpu_stage(CpuFrameStage::GameRecording);
        if let Err(error) = facade::begin_frame(self.width, self.height, self.scale) {
            log_completion(performance::present_failure());
            return Err(error);
        }
        facade::set_backend_info(self.renderer.info().clone());
        self.recording = true;
        Ok(FrameStart::Ready)
    }

    fn end_frame(&mut self) -> Result<(), String> {
        if !std::mem::take(&mut self.recording) {
            log_completion(performance::present_failure());
            return Err("end_frame called without a ready frame".into());
        }
        let list = match facade::take_draw_list() {
            Ok(list) => list,
            Err(error) => {
                log_completion(performance::present_failure());
                return Err(error);
            }
        };
        // Synchronous PNG readback is diagnostic work, not a gameplay interval.
        // Avoid even scanning commands when observation has not been enabled.
        if performance::is_active()
            && list
                .commands
                .iter()
                .any(|command| matches!(command, Command::Capture { .. }))
        {
            log_completion(performance::boundary(BoundaryReason::CaptureReadback));
        }
        // submit finishes all ordered captures synchronously. A write/map/GPU
        // error escapes to winit, including on the application's final frame.
        performance::end_cpu_stage(CpuFrameStage::GameRecording);
        if let Err(error) = self.renderer.submit(&list) {
            log_completion(performance::present_failure());
            return Err(error);
        }
        log_completion(performance::present_success());
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::draw::{BackendInfo, Command, DrawList, FrameOutput, TextDimensions};
    use crate::frame_performance::{
        CaptureLimits, RunIdentity, RuntimeIdentity, WindowContext, WindowMode,
    };
    use serde_json::{json, Value};
    use std::collections::VecDeque;
    use std::path::PathBuf;
    use std::sync::atomic::{AtomicU64, Ordering};

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

    /// Exercise the production TLS bridge and JSON export through DrawHooks.
    /// Clock values come from its real Instant clock, but assertions concern
    /// event ordering and exact timestamp differences, never elapsed thresholds
    /// or an asserted performance result. The renderer has no GPU or surface.
    struct PerformanceOutput(PathBuf);
    impl PerformanceOutput {
        fn start(hooks: &DrawHooks<FakeRenderer>) -> Self {
            static NEXT: AtomicU64 = AtomicU64::new(0);
            let path = std::env::temp_dir().join(format!(
                "rust-duty-hook-performance-{}-{}.json",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            assert!(!performance::is_active());
            performance::start(
                RunIdentity {
                    runtime: RuntimeIdentity {
                        actual_backend: Some("test-only FakeRenderer".into()),
                        actual_adapter: Value::Null,
                        build: json!({"test_fixture":true}),
                        initial_window: WindowContext {
                            physical_width: hooks.width,
                            physical_height: hooks.height,
                            scale_factor: hooks.scale,
                            mode: WindowMode::Unknown,
                        },
                        scene: Value::Null,
                    },
                    operator_supplied: Value::Null,
                },
                path.clone(),
                CaptureLimits {
                    max_records: 64,
                    ..CaptureLimits::default()
                },
            )
            .unwrap();
            Self(path)
        }

        fn read(&self) -> Value {
            serde_json::from_slice(&std::fs::read(&self.0).unwrap()).unwrap()
        }
    }
    impl Drop for PerformanceOutput {
        fn drop(&mut self) {
            // A failed assertion must not leave an enabled session behind.
            let _ = performance::shutdown();
            let _ = std::fs::remove_file(&self.0);
        }
    }

    fn retained_presents(report: &Value) -> Vec<&Value> {
        report["records"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|record| record["kind"] == "successful_present_return")
            .collect()
    }

    fn record_ready_frame(hooks: &mut DrawHooks<FakeRenderer>) {
        assert_eq!(hooks.begin_frame(160., 90.).unwrap(), FrameStart::Ready);
        facade::draw_rectangle(1., 2., 3., 4., facade::WHITE);
        hooks.end_frame().unwrap();
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

    #[test]
    fn enabled_observer_exports_only_after_counting_the_final_successful_frame() {
        let mut hooks = hooks();
        let output = PerformanceOutput::start(&hooks);
        record_ready_frame(&mut hooks);
        assert!(!output.0.exists());
        assert_eq!(hooks.begin_frame(160., 90.).unwrap(), FrameStart::Ready);
        performance::request_stop();
        assert!(performance::is_active());
        assert!(performance::is_stop_requested());
        assert!(!output.0.exists());
        hooks.end_frame().unwrap();

        assert!(!performance::is_active());
        assert_eq!(hooks.renderer.submitted.len(), 2);
        let report = output.read();
        assert_eq!(report["status"]["state"], "complete");
        assert_eq!(report["successful_present_count"], 2);
        assert_eq!(report["summary"]["interval_count"], 1);
        assert_eq!(report["identity"]["hardware_classification"], "unknown");
        let presents = retained_presents(&report);
        assert_eq!(presents.len(), 2);
        assert!(presents[0]["interval_ns"].is_null());
        assert_eq!(
            presents[1]["interval_ns"].as_u64().unwrap(),
            presents[1]["at_ns"].as_u64().unwrap() - presents[0]["at_ns"].as_u64().unwrap()
        );
        assert_eq!(report["stopped_at_ns"], presents[1]["at_ns"]);
        assert!(
            report["stop_requested_ns"].as_u64().unwrap() <= presents[1]["at_ns"].as_u64().unwrap()
        );
        let samples = report["cpu_frame_stages"]["samples"].as_array().unwrap();
        assert_eq!(samples.len(), 2);
        for sample in samples {
            assert_eq!(sample["physical_width"], 320);
            assert_eq!(sample["physical_height"], 180);
            let span = &sample["spans"]["game_recording"];
            let start = span["started_at_ns"].as_u64().unwrap();
            let end = span["ended_at_ns"].as_u64().unwrap();
            assert!(sample["started_at_ns"].as_u64().unwrap() <= start);
            assert!(end <= sample["finished_at_ns"].as_u64().unwrap());
            assert_eq!(span["duration_ns"].as_u64().unwrap(), end - start);
            // This fake renderer has no real acquire, encoder or present call.
            // Missing hooks must remain unavailable instead of inferred time.
            for stage in ["surface_acquire", "renderer_submit", "present_call"] {
                assert!(sample["spans"][stage].is_null());
            }
        }
    }

    #[test]
    fn enabled_observer_exports_failed_submission_as_incomplete_without_a_present() {
        let mut hooks = hooks();
        let output = PerformanceOutput::start(&hooks);
        record_ready_frame(&mut hooks);
        record_ready_frame(&mut hooks);
        hooks.renderer.submission_error = Some("synthetic submit failure".into());
        assert_eq!(hooks.begin_frame(160., 90.).unwrap(), FrameStart::Ready);
        performance::request_stop();
        assert_eq!(hooks.end_frame().unwrap_err(), "synthetic submit failure");

        assert!(!performance::is_active());
        assert!(facade::current_camera().is_err());
        assert_eq!(hooks.renderer.submitted.len(), 3);
        let report = output.read();
        assert_eq!(report["status"]["state"], "incomplete");
        assert_eq!(
            report["status"]["error"],
            crate::frame_performance::CaptureError::PresentFailed.to_string()
        );
        assert_eq!(report["successful_present_count"], 2);
        assert_eq!(report["summary"]["interval_count"], 1);
        assert_eq!(retained_presents(&report).len(), 2);
        let records = report["records"].as_array().unwrap();
        assert_eq!(records.last().unwrap()["kind"], "boundary");
        assert_eq!(records.last().unwrap()["reason"], "surface_error");
        assert_eq!(report["incomplete_at_ns"], records.last().unwrap()["at_ns"]);
    }

    #[test]
    fn enabled_observer_preserves_the_present_interval_across_surface_retries() {
        let mut hooks = hooks();
        let output = PerformanceOutput::start(&hooks);
        record_ready_frame(&mut hooks);
        hooks
            .renderer
            .readiness
            .extend([Ok(false), Ok(false), Ok(true)]);
        for _ in 0..2 {
            assert_eq!(hooks.begin_frame(160., 90.).unwrap(), FrameStart::Skip);
            assert!(facade::current_camera().is_err());
            assert_eq!(hooks.renderer.submitted.len(), 1);
            assert!(performance::is_active());
            assert!(!output.0.exists());
        }
        assert_eq!(hooks.begin_frame(160., 90.).unwrap(), FrameStart::Ready);
        performance::request_stop();
        hooks.end_frame().unwrap();

        let report = output.read();
        assert_eq!(report["status"]["state"], "complete");
        assert_eq!(report["successful_present_count"], 2);
        assert_eq!(report["skipped_frame_count"], 2);
        assert_eq!(report["summary"]["interval_count"], 1);
        let records = report["records"].as_array().unwrap();
        assert_eq!(records.len(), 4);
        assert_eq!(records[1]["kind"], "skipped_frame");
        assert_eq!(records[2]["kind"], "skipped_frame");
        assert_eq!(records[1]["reason"], "surface_skipped");
        assert_eq!(records[2]["reason"], "surface_skipped");
        let interval =
            records[3]["at_ns"].as_u64().unwrap() - records[0]["at_ns"].as_u64().unwrap();
        assert_eq!(records[3]["interval_ns"].as_u64().unwrap(), interval);
        assert_eq!(
            report["summary"]["total_interval_ns"].as_u64().unwrap(),
            interval
        );
        assert_eq!(hooks.renderer.submitted.len(), 2);
    }

    #[test]
    fn enabled_observer_excludes_synchronous_capture_readback_from_intervals() {
        let mut hooks = hooks();
        let output = PerformanceOutput::start(&hooks);
        record_ready_frame(&mut hooks);
        assert_eq!(hooks.begin_frame(160., 90.).unwrap(), FrameStart::Ready);
        facade::capture_png(None, "synthetic-readback-not-written.png");
        hooks.end_frame().unwrap();
        assert_eq!(hooks.begin_frame(160., 90.).unwrap(), FrameStart::Ready);
        performance::request_stop();
        hooks.end_frame().unwrap();

        let report = output.read();
        assert_eq!(report["status"]["state"], "complete");
        assert_eq!(report["successful_present_count"], 3);
        assert_eq!(report["summary"]["interval_count"], 1);
        let records = report["records"].as_array().unwrap();
        assert_eq!(records.len(), 4);
        assert_eq!(records[1]["kind"], "boundary");
        assert_eq!(records[1]["reason"], "capture_readback");
        let presents = retained_presents(&report);
        assert_eq!(presents.len(), 3);
        assert!(presents[0]["interval_ns"].is_null());
        assert!(presents[1]["interval_ns"].is_null());
        let interval =
            presents[2]["at_ns"].as_u64().unwrap() - presents[1]["at_ns"].as_u64().unwrap();
        assert_eq!(presents[2]["interval_ns"].as_u64().unwrap(), interval);
        assert_eq!(
            report["summary"]["total_interval_ns"].as_u64().unwrap(),
            interval
        );
        assert!(matches!(
            hooks.renderer.submitted[1].commands.last(),
            Some(Command::Capture { .. })
        ));
    }
}
