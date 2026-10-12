//! Synthetic monotonic-clock contracts for the actual application session.
//! These are lifecycle evidence, not hardware or FPS measurements.
use serde_json::{json, Value};
use std::cell::Cell;
use std::path::PathBuf;
use std::rc::Rc;
use std::sync::atomic::{AtomicU64, Ordering};
use vector_range::frame_performance::{
    BoundaryReason, CaptureError, CaptureLimits, CaptureStatus, CpuFrameStage, Eligibility,
    RecordKind, RunIdentity, RuntimeIdentity, WindowContext, WindowMode, WriteStage,
};
use vector_range::frame_performance_session::{
    MonotonicClock, PerformanceSession, SessionCompletion, SessionStartError,
};

#[derive(Clone, Default)]
struct FakeClock {
    now: Rc<Cell<u64>>,
    reads: Rc<Cell<usize>>,
}
impl FakeClock {
    fn set(&self, at_ns: u64) {
        self.now.set(at_ns);
    }
}
impl MonotonicClock for FakeClock {
    fn now_ns(&mut self) -> u64 {
        self.reads.set(self.reads.get() + 1);
        self.now.get()
    }
}

struct OutputPath(PathBuf);
impl OutputPath {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        Self(std::env::temp_dir().join(format!(
            "rust-duty-session-{}-{}.json",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        )))
    }
    fn read(&self) -> Value {
        serde_json::from_slice(&std::fs::read(&self.0).unwrap()).unwrap()
    }
}
impl Drop for OutputPath {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}
fn window() -> WindowContext {
    WindowContext {
        physical_width: 1920,
        physical_height: 1080,
        scale_factor: 1.5,
        mode: WindowMode::Windowed,
    }
}
fn identity() -> RunIdentity {
    RunIdentity {
        runtime: RuntimeIdentity {
            actual_backend: Some("synthetic contract fixture".into()),
            actual_adapter: Value::Null,
            build: json!({"test_fixture":true}),
            initial_window: window(),
            scene: Value::Null,
        },
        operator_supplied: json!({"hardware_claim":"not authenticated"}),
    }
}
fn started() -> (PerformanceSession<FakeClock>, FakeClock, OutputPath) {
    let clock = FakeClock::default();
    let output = OutputPath::new();
    let mut session = PerformanceSession::new(clock.clone());
    session
        .start(identity(), output.0.clone(), CaptureLimits::default())
        .unwrap();
    (session, clock, output)
}
fn present(session: &mut PerformanceSession<FakeClock>, clock: &FakeClock, at: u64) {
    clock.set(at);
    assert!(session.present_success().is_none());
}
fn stop(
    session: &mut PerformanceSession<FakeClock>,
    clock: &FakeClock,
    request: u64,
    final_present: u64,
) -> SessionCompletion {
    clock.set(request);
    session.request_stop();
    clock.set(final_present);
    session.present_success().unwrap()
}

#[test]
fn disabled_hooks_do_not_read_a_clock_or_create_output() {
    let clock = FakeClock::default();
    let mut session = PerformanceSession::new(clock.clone());
    let output = OutputPath::new();
    assert!(!session.is_active());
    assert!(!session.is_stop_requested());
    session.request_stop();
    session.begin_cpu_frame(1920, 1080);
    for stage in CpuFrameStage::ALL {
        session.begin_cpu_stage(stage);
        session.end_cpu_stage(stage);
    }
    assert!(session.set_eligibility(Eligibility::Eligible).is_none());
    assert!(session.update_window_context(window()).is_none());
    assert!(session.boundary(BoundaryReason::Resize).is_none());
    assert!(session.present_success().is_none());
    assert!(session.present_skipped().is_none());
    assert!(session.present_failure().is_none());
    assert!(session.shutdown().is_none());
    assert_eq!(clock.reads.get(), 0);
    assert!(!output.0.exists());
}

#[test]
fn stop_waits_for_and_includes_the_final_successful_present() {
    let (mut session, clock, output) = started();
    assert!(!output.0.exists());
    present(&mut session, &clock, 10);
    present(&mut session, &clock, 15);
    clock.set(20);
    session.request_stop();
    assert!(session.is_active());
    assert!(session.is_stop_requested());
    assert!(!output.0.exists());
    let reads = clock.reads.get();
    clock.set(21);
    session.request_stop();
    assert_eq!(clock.reads.get(), reads, "first request time is retained");
    clock.set(25);
    let done = session.present_success().unwrap();
    assert_eq!(done.report.successful_present_count, 3);
    assert_eq!(done.report.summary.interval_count, 2);
    assert_eq!(done.report.summary.total_interval_ns, 15);
    assert_eq!(done.report.stop_requested_ns, 20);
    assert_eq!(done.report.stopped_at_ns, Some(25));
    assert_eq!(done.export.unwrap(), CaptureStatus::Complete);
    assert!(!session.is_active());
    let reads = clock.reads.get();
    assert!(session.shutdown().is_none());
    assert!(session.present_success().is_none());
    assert_eq!(clock.reads.get(), reads);
    assert_eq!(output.read()["successful_present_count"], 3);
    assert_eq!(
        output.read()["identity"]["hardware_classification"],
        "unknown"
    );
}

#[test]
fn paused_eligibility_persists_across_presents_and_transient_boundaries() {
    let (mut session, clock, _output) = started();
    present(&mut session, &clock, 10);
    present(&mut session, &clock, 20);
    clock.set(25);
    assert!(session
        .set_eligibility(Eligibility::Ineligible(BoundaryReason::Paused))
        .is_none());
    present(&mut session, &clock, 100);
    present(&mut session, &clock, 200);
    clock.set(205);
    assert!(session.boundary(BoundaryReason::CaptureReadback).is_none());
    present(&mut session, &clock, 210);
    clock.set(220);
    assert!(session.set_eligibility(Eligibility::Eligible).is_none());
    present(&mut session, &clock, 230);
    present(&mut session, &clock, 240);
    let done = stop(&mut session, &clock, 245, 250);
    assert_eq!(done.report.successful_present_count, 8);
    assert_eq!(done.report.ineligible_present_count, 3);
    assert_eq!(done.report.summary.interval_count, 3);
    assert_eq!(done.report.summary.total_interval_ns, 30);
    assert_eq!(done.report.summary.max_ns, Some(10));
    assert!(done.report.raw_records().iter().any(|record| matches!(
        record.kind,
        RecordKind::Boundary {
            reason: BoundaryReason::Resumed
        }
    )));
}

#[test]
fn focus_period_with_no_presents_still_breaks_the_interval_chain() {
    let (mut session, clock, _output) = started();
    present(&mut session, &clock, 10);
    clock.set(20);
    session.set_eligibility(Eligibility::Ineligible(BoundaryReason::FocusLost));
    clock.set(1000);
    session.set_eligibility(Eligibility::Eligible);
    present(&mut session, &clock, 1010);
    let done = stop(&mut session, &clock, 1015, 1020);
    assert_eq!(done.report.summary.interval_count, 1);
    assert_eq!(done.report.summary.total_interval_ns, 10);
    assert!(done.report.raw_records().iter().any(|record| matches!(
        record.kind,
        RecordKind::Boundary {
            reason: BoundaryReason::FocusRegained
        }
    )));
}

#[test]
fn active_surface_retries_preserve_the_full_long_successful_present_gap() {
    let (mut session, clock, _output) = started();
    present(&mut session, &clock, 10);
    clock.set(20);
    assert!(session.present_skipped().is_none());
    assert!(session.is_active());
    clock.set(1000);
    assert!(session.present_skipped().is_none());
    present(&mut session, &clock, 10_010);
    let done = stop(&mut session, &clock, 10_015, 10_020);
    assert_eq!(done.report.successful_present_count, 3);
    assert_eq!(done.report.skipped_frame_count, 2);
    assert_eq!(done.report.summary.interval_count, 2);
    assert_eq!(done.report.summary.total_interval_ns, 10_010);
    assert_eq!(done.report.summary.max_ns, Some(10_000));
    assert_eq!(done.report.status, CaptureStatus::Complete);
}

#[test]
fn pending_stop_then_skip_exports_incomplete_without_synthesizing_a_present() {
    let (mut session, clock, output) = started();
    present(&mut session, &clock, 10);
    present(&mut session, &clock, 20);
    clock.set(25);
    session.request_stop();
    clock.set(30);
    let done = session.present_skipped().unwrap();
    assert_eq!(done.report.successful_present_count, 2);
    assert_eq!(done.report.summary.total_interval_ns, 10);
    assert_eq!(done.report.stop_requested_ns, 25);
    assert_eq!(done.report.incomplete_at_ns, Some(30));
    assert_eq!(
        done.export.unwrap(),
        CaptureStatus::Incomplete(CaptureError::FinalPresentMissing)
    );
    assert_eq!(output.read()["status"]["state"], "incomplete");
    assert_eq!(output.read()["records"][2]["reason"], "surface_skipped");
}

#[test]
fn failed_final_present_is_exported_as_failure_not_a_successful_sample() {
    let (mut session, clock, output) = started();
    present(&mut session, &clock, 10);
    present(&mut session, &clock, 20);
    clock.set(25);
    session.request_stop();
    clock.set(30);
    let done = session.present_failure().unwrap();
    assert_eq!(done.report.successful_present_count, 2);
    assert_eq!(done.report.summary.interval_count, 1);
    assert_eq!(
        done.export.unwrap(),
        CaptureStatus::Incomplete(CaptureError::PresentFailed)
    );
    assert_eq!(output.read()["records"][2]["reason"], "surface_error");
    assert!(!session.is_active());
}

#[test]
fn shutdown_exports_honest_incomplete_evidence_even_with_prior_good_intervals() {
    let (mut session, clock, output) = started();
    present(&mut session, &clock, 10);
    present(&mut session, &clock, 20);
    clock.set(30);
    let done = session.shutdown().unwrap();
    assert_eq!(done.report.successful_present_count, 2);
    assert_eq!(done.report.summary.total_interval_ns, 10);
    assert_eq!(
        done.report.status,
        CaptureStatus::Incomplete(CaptureError::FinalPresentMissing)
    );
    assert_eq!(output.read()["records"][2]["reason"], "shutdown");
    assert!(session.shutdown().is_none());
}

#[test]
fn first_frame_failure_is_more_specific_than_empty_capture() {
    let (mut session, clock, _output) = started();
    clock.set(10);
    let done = session.present_failure().unwrap();
    assert_eq!(done.report.successful_present_count, 0);
    assert_eq!(done.report.summary.interval_count, 0);
    assert_eq!(
        done.report.status,
        CaptureStatus::Incomplete(CaptureError::PresentFailed)
    );
}

#[test]
fn export_failure_is_returned_and_existing_output_is_never_overwritten() {
    let (mut session, clock, output) = started();
    std::fs::write(&output.0, "keep existing evidence").unwrap();
    present(&mut session, &clock, 10);
    let done = stop(&mut session, &clock, 15, 20);
    assert_eq!(done.report.status, CaptureStatus::Complete);
    let error = done.export.unwrap_err();
    assert_eq!(error.stage, WriteStage::Create);
    assert!(!error.partial_file_possible);
    assert_eq!(
        std::fs::read_to_string(&output.0).unwrap(),
        "keep existing evidence"
    );
    assert!(!session.is_active());
}

#[test]
fn changed_window_context_is_retained_once_and_breaks_the_interval_chain() {
    let (mut session, clock, _output) = started();
    present(&mut session, &clock, 10);
    let reads = clock.reads.get();
    session.update_window_context(window());
    assert_eq!(clock.reads.get(), reads);
    clock.set(20);
    let changed = WindowContext {
        physical_width: 2560,
        physical_height: 1440,
        scale_factor: 2.0,
        mode: WindowMode::Borderless,
    };
    assert!(session.update_window_context(changed).is_none());
    let reads = clock.reads.get();
    assert!(session.update_window_context(changed).is_none());
    assert_eq!(clock.reads.get(), reads);
    present(&mut session, &clock, 100);
    let done = stop(&mut session, &clock, 105, 110);
    assert_eq!(done.report.identity.runtime.initial_window, window());
    let contexts: Vec<_> = done
        .report
        .raw_records()
        .iter()
        .filter_map(|record| match record.kind {
            RecordKind::WindowContext { context } => Some(context),
            _ => None,
        })
        .collect();
    assert_eq!(contexts, [changed]);
    assert_eq!(done.report.summary.total_interval_ns, 10);
}

#[test]
fn observer_limit_auto_exports_incomplete_and_disables_future_clock_reads() {
    let clock = FakeClock::default();
    let output = OutputPath::new();
    let mut session = PerformanceSession::new(clock.clone());
    session
        .start(
            identity(),
            output.0.clone(),
            CaptureLimits {
                max_records: 2,
                ..CaptureLimits::default()
            },
        )
        .unwrap();
    present(&mut session, &clock, 10);
    present(&mut session, &clock, 20);
    clock.set(30);
    let done = session.present_success().unwrap();
    assert_eq!(done.report.successful_present_count, 2);
    assert_eq!(
        done.report.status,
        CaptureStatus::Incomplete(CaptureError::RecordLimitExceeded { max_records: 2 })
    );
    assert!(!session.is_active());
    let reads = clock.reads.get();
    assert!(session.present_failure().is_none());
    assert!(session.shutdown().is_none());
    assert_eq!(clock.reads.get(), reads);
}

#[test]
fn backwards_clock_error_is_not_masked_by_a_final_present_failure() {
    let (mut session, clock, _output) = started();
    present(&mut session, &clock, 20);
    clock.set(10);
    let done = session.present_failure().unwrap();
    assert_eq!(
        done.report.status,
        CaptureStatus::Incomplete(CaptureError::NonMonotonicTimestamp {
            previous_ns: 20,
            received_ns: 10
        })
    );
    assert_eq!(done.report.stopped_at_ns, None);
}

#[test]
fn repeated_start_cannot_replace_an_active_capture_or_sample_its_clock() {
    let (mut session, clock, output) = started();
    let other_output = OutputPath::new();
    let reads = clock.reads.get();
    assert_eq!(
        session.start(identity(), other_output.0.clone(), CaptureLimits::default()),
        Err(SessionStartError::AlreadyActive)
    );
    assert_eq!(clock.reads.get(), reads);
    present(&mut session, &clock, 10);
    let done = stop(&mut session, &clock, 15, 20);
    assert_eq!(done.output_path, output.0);
    assert!(!other_output.0.exists());
}

#[test]
fn invalid_start_keeps_session_disabled_and_does_not_create_output() {
    let clock = FakeClock::default();
    let output = OutputPath::new();
    let mut session = PerformanceSession::new(clock.clone());
    assert_eq!(
        session.start(
            identity(),
            output.0.clone(),
            CaptureLimits {
                max_records: 0,
                ..CaptureLimits::default()
            }
        ),
        Err(SessionStartError::Observer(CaptureError::InvalidLimits))
    );
    assert!(!session.is_active());
    assert!(!output.0.exists());
    let reads = clock.reads.get();
    session.request_stop();
    assert!(session.shutdown().is_none());
    assert_eq!(clock.reads.get(), reads);
}

#[test]
fn completion_notice_is_consumed_once_and_none_does_not_erase_it() {
    use vector_range::frame_performance_session::{log_completion, take_completion_notice};
    assert!(take_completion_notice().is_none());
    let (mut session, clock, output) = started();
    present(&mut session, &clock, 10);
    let completion = stop(&mut session, &clock, 20, 30);
    log_completion(Some(completion));
    log_completion(None);
    let notice = take_completion_notice().unwrap();
    assert_eq!(notice.output_path, output.0);
    assert_eq!(notice.status, CaptureStatus::Complete);
    assert!(notice.export_error.is_none());
    assert!(take_completion_notice().is_none());
}

#[test]
fn latest_completion_preserves_export_error_and_incomplete_capture_status() {
    use vector_range::frame_performance_session::{log_completion, take_completion_notice};
    assert!(take_completion_notice().is_none());
    let (mut first, first_clock, first_output) = started();
    present(&mut first, &first_clock, 10);
    log_completion(Some(stop(&mut first, &first_clock, 20, 30)));

    let (mut failed, failed_clock, failed_output) = started();
    std::fs::write(&failed_output.0, b"existing evidence").unwrap();
    present(&mut failed, &failed_clock, 10);
    log_completion(Some(stop(&mut failed, &failed_clock, 20, 30)));
    let notice = take_completion_notice().unwrap();
    assert_ne!(notice.output_path, first_output.0);
    assert_eq!(notice.output_path, failed_output.0);
    assert_eq!(notice.status, CaptureStatus::Complete);
    assert!(notice
        .export_error
        .as_ref()
        .is_some_and(|error| !error.is_empty()));
    assert_eq!(
        std::fs::read(&failed_output.0).unwrap(),
        b"existing evidence"
    );
    assert!(take_completion_notice().is_none());

    let (mut incomplete, clock, output) = started();
    clock.set(10);
    log_completion(incomplete.present_failure());
    let notice = take_completion_notice().unwrap();
    assert_eq!(notice.output_path, output.0);
    assert_eq!(
        notice.status,
        CaptureStatus::Incomplete(CaptureError::PresentFailed)
    );
    assert!(notice.export_error.is_none());
    assert!(take_completion_notice().is_none());
}

fn cpu_stage(
    session: &mut PerformanceSession<FakeClock>,
    clock: &FakeClock,
    stage: CpuFrameStage,
    start: u64,
    end: u64,
) {
    clock.set(start);
    session.begin_cpu_stage(stage);
    clock.set(end);
    session.end_cpu_stage(stage);
}

#[test]
fn cpu_stages_are_paired_disjoint_and_preserve_final_present_and_export() {
    let (mut session, clock, output) = started();
    present(&mut session, &clock, 10);
    clock.set(12);
    session.begin_cpu_frame(1920, 1080);
    cpu_stage(&mut session, &clock, CpuFrameStage::SurfaceAcquire, 13, 23);
    cpu_stage(&mut session, &clock, CpuFrameStage::GameRecording, 24, 54);
    clock.set(55);
    session.request_stop();
    assert!(!output.0.exists());
    cpu_stage(&mut session, &clock, CpuFrameStage::RendererSubmit, 56, 96);
    cpu_stage(&mut session, &clock, CpuFrameStage::PresentCall, 97, 99);
    clock.set(100);
    let done = session.present_success().unwrap();
    assert_eq!(done.report.summary.total_interval_ns, 90);
    assert_eq!(done.report.stop_requested_ns, 55);
    assert_eq!(done.report.stopped_at_ns, Some(100));
    let report = done.report.to_json();
    assert_eq!(report, output.read());
    let sample = &report["cpu_frame_stages"]["samples"][0];
    assert_eq!(sample["record_index"], 1);
    assert_eq!(sample["started_at_ns"], 12);
    assert_eq!(sample["finished_at_ns"], 100);
    assert_eq!(sample["physical_width"], 1920);
    assert_eq!(sample["physical_height"], 1080);
    let mut previous = 12;
    let mut total = 0;
    for (stage, expected) in CpuFrameStage::ALL.into_iter().zip([10, 30, 40, 2]) {
        let span = &sample["spans"][stage.label()];
        let start = span["started_at_ns"].as_u64().unwrap();
        let end = span["ended_at_ns"].as_u64().unwrap();
        let duration = span["duration_ns"].as_u64().unwrap();
        assert!(previous <= start && start <= end && end <= 100);
        assert_eq!(duration, end - start);
        assert_eq!(duration, expected);
        total += duration;
        previous = end;
    }
    assert!(total < done.report.summary.total_interval_ns);
    assert!(report["cpu_frame_stages"]["interpretation"]
        .as_str()
        .unwrap()
        .contains("not GPU"));
    assert!(sample.get("gpu_time_ns").is_none());
    assert_eq!(done.export.unwrap(), CaptureStatus::Complete);
}

#[test]
fn cpu_acquisition_retry_is_retained_without_resetting_the_present_anchor() {
    let (mut session, clock, output) = started();
    present(&mut session, &clock, 10);
    clock.set(11);
    session.begin_cpu_frame(1920, 1080);
    cpu_stage(
        &mut session,
        &clock,
        CpuFrameStage::SurfaceAcquire,
        12,
        1000,
    );
    clock.set(1001);
    assert!(session.present_skipped().is_none());
    clock.set(1002);
    session.begin_cpu_frame(1920, 1080);
    cpu_stage(
        &mut session,
        &clock,
        CpuFrameStage::SurfaceAcquire,
        1003,
        1004,
    );
    let done = stop(&mut session, &clock, 1005, 1010);
    assert_eq!(done.report.summary.total_interval_ns, 1000);
    let report = output.read();
    let samples = report["cpu_frame_stages"]["samples"].as_array().unwrap();
    assert_eq!(samples.len(), 2);
    assert_eq!(samples[0]["record_index"], 1);
    assert_eq!(report["records"][1]["kind"], "skipped_frame");
    assert_eq!(samples[0]["spans"]["surface_acquire"]["duration_ns"], 988);
    assert!(samples[0]["spans"]["present_call"].is_null());
    assert_eq!(samples[1]["spans"]["surface_acquire"]["duration_ns"], 1);
}

#[test]
fn cpu_acquisition_and_submission_failures_keep_completed_spans_without_a_present() {
    for failed_stage in [CpuFrameStage::SurfaceAcquire, CpuFrameStage::RendererSubmit] {
        let (mut session, clock, output) = started();
        present(&mut session, &clock, 10);
        present(&mut session, &clock, 20);
        clock.set(21);
        session.begin_cpu_frame(1920, 1080);
        cpu_stage(&mut session, &clock, failed_stage, 22, 28);
        clock.set(29);
        session.request_stop();
        clock.set(30);
        let done = session.present_failure().unwrap();
        assert_eq!(
            done.report.status,
            CaptureStatus::Incomplete(CaptureError::PresentFailed)
        );
        assert_eq!(done.report.successful_present_count, 2);
        assert_eq!(done.report.summary.total_interval_ns, 10);
        let report = output.read();
        let sample = &report["cpu_frame_stages"]["samples"][0];
        assert_eq!(sample["record_index"], 2);
        assert_eq!(report["records"][2]["reason"], "surface_error");
        assert_eq!(sample["spans"][failed_stage.label()]["duration_ns"], 6);
        assert!(sample["spans"]["present_call"].is_null());
    }
}

#[test]
fn cpu_dimensions_follow_resize_and_paused_stages_stay_ineligible() {
    let (mut session, clock, output) = started();
    present(&mut session, &clock, 10);
    clock.set(11);
    session.set_eligibility(Eligibility::Ineligible(BoundaryReason::Paused));
    clock.set(12);
    session.begin_cpu_frame(1920, 1080);
    cpu_stage(&mut session, &clock, CpuFrameStage::GameRecording, 13, 20);
    present(&mut session, &clock, 21);
    clock.set(22);
    session.update_window_context(WindowContext {
        physical_width: 1280,
        physical_height: 720,
        ..window()
    });
    clock.set(23);
    session.set_eligibility(Eligibility::Eligible);
    clock.set(24);
    session.begin_cpu_frame(1280, 720);
    cpu_stage(&mut session, &clock, CpuFrameStage::SurfaceAcquire, 25, 26);
    present(&mut session, &clock, 30);
    let done = stop(&mut session, &clock, 31, 40);
    assert_eq!(done.report.summary.total_interval_ns, 10);
    assert_eq!(done.report.ineligible_present_count, 1);
    let report = output.read();
    let samples = report["cpu_frame_stages"]["samples"].as_array().unwrap();
    assert_eq!(samples[0]["physical_width"], 1920);
    let index = samples[0]["record_index"].as_u64().unwrap() as usize;
    assert_eq!(report["records"][index]["ineligible_reason"], "paused");
    assert!(report["records"][index]["interval_ns"].is_null());
    assert_eq!(samples[1]["physical_width"], 1280);
    assert_eq!(samples[1]["physical_height"], 720);
}

#[test]
fn cpu_unpaired_and_midframe_stages_are_unavailable_and_never_leak_into_next_frame() {
    let (mut session, clock, output) = started();
    // Capturing begins after a frame's recording hook: its end cannot invent a start.
    session.end_cpu_stage(CpuFrameStage::GameRecording);
    present(&mut session, &clock, 10);
    clock.set(11);
    session.begin_cpu_frame(1920, 1080);
    clock.set(12);
    session.begin_cpu_stage(CpuFrameStage::GameRecording);
    present(&mut session, &clock, 20);
    clock.set(21);
    session.begin_cpu_frame(1920, 1080);
    cpu_stage(&mut session, &clock, CpuFrameStage::SurfaceAcquire, 22, 22);
    let done = stop(&mut session, &clock, 23, 30);
    assert_eq!(done.report.summary.total_interval_ns, 20);
    let report = output.read();
    let samples = report["cpu_frame_stages"]["samples"].as_array().unwrap();
    assert_eq!(samples.len(), 2);
    assert!(samples[0]["spans"]["game_recording"].is_null());
    assert!(samples[1]["spans"]["game_recording"].is_null());
    assert_eq!(samples[1]["spans"]["surface_acquire"]["duration_ns"], 0);
}

#[test]
fn cpu_overlapping_or_mismatched_pairs_are_omitted_without_changing_primary_intervals() {
    for mismatch in [false, true] {
        let (mut session, clock, output) = started();
        present(&mut session, &clock, 10);
        clock.set(11);
        session.begin_cpu_frame(1920, 1080);
        session.begin_cpu_stage(CpuFrameStage::SurfaceAcquire);
        if mismatch {
            session.end_cpu_stage(CpuFrameStage::PresentCall);
        } else {
            session.begin_cpu_stage(CpuFrameStage::GameRecording);
        }
        session.end_cpu_stage(CpuFrameStage::SurfaceAcquire);
        let done = stop(&mut session, &clock, 15, 20);
        assert_eq!(done.report.summary.total_interval_ns, 10);
        assert!(output.read().get("cpu_frame_stages").is_none());
    }
}

#[test]
fn cpu_backward_stage_clock_marks_capture_incomplete_without_unsigned_underflow() {
    let (mut session, clock, output) = started();
    present(&mut session, &clock, 10);
    clock.set(11);
    session.begin_cpu_frame(1920, 1080);
    cpu_stage(&mut session, &clock, CpuFrameStage::SurfaceAcquire, 20, 19);
    clock.set(21);
    let done = session.present_success().unwrap();
    assert!(matches!(
        done.report.status,
        CaptureStatus::Incomplete(CaptureError::NonMonotonicTimestamp { .. })
    ));
    assert_eq!(done.report.successful_present_count, 1);
    assert!(output.read().get("cpu_frame_stages").is_none());
}

#[test]
fn cpu_samples_cannot_outlive_the_bounded_record_buffer() {
    let clock = FakeClock::default();
    let output = OutputPath::new();
    let mut session = PerformanceSession::new(clock.clone());
    session
        .start(
            identity(),
            output.0.clone(),
            CaptureLimits {
                max_records: 1,
                ..CaptureLimits::default()
            },
        )
        .unwrap();
    session.begin_cpu_frame(1920, 1080);
    cpu_stage(&mut session, &clock, CpuFrameStage::SurfaceAcquire, 1, 2);
    present(&mut session, &clock, 3);
    clock.set(4);
    session.begin_cpu_frame(1920, 1080);
    cpu_stage(&mut session, &clock, CpuFrameStage::SurfaceAcquire, 5, 6);
    clock.set(7);
    let done = session.present_success().unwrap();
    assert_eq!(
        done.report.status,
        CaptureStatus::Incomplete(CaptureError::RecordLimitExceeded { max_records: 1 })
    );
    let report = output.read();
    assert_eq!(report["records"].as_array().unwrap().len(), 1);
    assert_eq!(
        report["cpu_frame_stages"]["samples"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
}
