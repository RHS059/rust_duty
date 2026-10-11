//! Real producer/session contracts with a synthetic clock, not GPU benchmarks.
use serde_json::{json, Value};
use std::{
    cell::Cell,
    path::PathBuf,
    rc::Rc,
    sync::atomic::{AtomicU64, Ordering},
};
use vector_range::frame_cpu_substages::CpuSubstage;
use vector_range::frame_performance::{
    CaptureLimits, CaptureStatus, CpuFrameStage, RunIdentity, RuntimeIdentity, WindowContext,
    WindowMode,
};
use vector_range::frame_performance_session::{
    take_cpu_substage_export_notice, MonotonicClock, PerformanceSession,
};

#[derive(Clone, Default)]
struct Clock {
    time: Rc<Cell<u64>>,
    reads: Rc<Cell<usize>>,
}
impl MonotonicClock for Clock {
    fn now_ns(&mut self) -> u64 {
        self.reads.set(self.reads.get() + 1);
        self.time.get()
    }
}
struct Files(PathBuf);
impl Files {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        Self(std::env::temp_dir().join(format!(
            "rust-duty-cpu-substage-{}-{}.json",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        )))
    }
    fn sidecar(&self) -> PathBuf {
        self.0.with_extension("cpu-substages.json")
    }
    fn primary(&self) -> Vec<u8> {
        std::fs::read(&self.0).unwrap()
    }
    fn details(&self) -> Value {
        serde_json::from_slice(&std::fs::read(self.sidecar()).unwrap()).unwrap()
    }
}
impl Drop for Files {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
        let _ = std::fs::remove_file(self.sidecar());
    }
}
fn identity() -> RunIdentity {
    RunIdentity {
        runtime: RuntimeIdentity {
            actual_backend: Some("synthetic CPU contract".into()),
            actual_adapter: Value::Null,
            build: json!({"fixture":true}),
            scene: Value::Null,
            initial_window: WindowContext {
                physical_width: 1920,
                physical_height: 1080,
                scale_factor: 1.,
                mode: WindowMode::Windowed,
            },
        },
        operator_supplied: Value::Null,
    }
}
fn capture(files: &Files, details: bool, overlap: bool) {
    let clock = Clock::default();
    let mut session = PerformanceSession::new(clock.clone());
    session
        .start(identity(), files.0.clone(), CaptureLimits::default())
        .unwrap();
    clock.time.set(10);
    assert!(session.present_success().is_none());
    clock.time.set(11);
    session.begin_cpu_frame(1920, 1080);
    for (stage, start, finish, child) in [
        (
            CpuFrameStage::SurfaceAcquire,
            12,
            17,
            Some((CpuSubstage::AcquireTexture, CpuSubstage::AcquireValidation)),
        ),
        (CpuFrameStage::GameRecording, 18, 19, None),
        (
            CpuFrameStage::RendererSubmit,
            20,
            25,
            Some((CpuSubstage::EncodeSubmit, CpuSubstage::SubmitValidation)),
        ),
        (CpuFrameStage::PresentCall, 26, 27, None),
    ] {
        clock.time.set(start);
        session.begin_cpu_stage(stage);
        if details {
            if let Some((first, second)) = child {
                clock.time.set(start + 1);
                session.begin_cpu_substage(first);
                if overlap && first == CpuSubstage::EncodeSubmit {
                    session.begin_cpu_substage(first);
                }
                clock.time.set(start + 2);
                session.end_cpu_substage(first);
                clock.time.set(start + 3);
                session.begin_cpu_substage(second);
                clock.time.set(start + 4);
                session.end_cpu_substage(second);
            }
        }
        clock.time.set(finish);
        session.end_cpu_stage(stage);
    }
    clock.time.set(28);
    session.request_stop();
    assert!(!files.0.exists());
    clock.time.set(29);
    let result = session.present_success().unwrap();
    assert_eq!(result.report.status, CaptureStatus::Complete);
    assert_eq!(result.export.unwrap(), CaptureStatus::Complete);
}

#[test]
fn detail_hooks_preserve_primary_bytes_and_bind_sidecar_to_actual_file() {
    let without = Files::new();
    let with = Files::new();
    capture(&without, false, false);
    capture(&with, true, false);
    assert_eq!(without.primary(), with.primary());
    let value = with.details();
    assert_eq!(
        value["frame_report_sha256"],
        rust_duty_launcher::file_hash(&with.0).unwrap()
    );
    assert_eq!(value["samples"][0]["record_index"], 1);
    assert_eq!(
        value["samples"][0]["details"]["spans"]
            .as_array()
            .unwrap()
            .len(),
        4
    );
    assert_eq!(value["samples"][0]["details"]["state"], "complete");
    assert!(take_cpu_substage_export_notice().unwrap().error.is_none());
}

#[test]
fn malformed_detail_does_not_change_successful_primary_capture() {
    let baseline = Files::new();
    let malformed = Files::new();
    capture(&baseline, false, false);
    capture(&malformed, true, true);
    assert_eq!(baseline.primary(), malformed.primary());
    assert_eq!(
        malformed.details()["samples"][0]["details"]["state"],
        "incomplete"
    );
}

#[test]
fn sidecar_collision_is_reported_without_overwrite_or_primary_failure() {
    let files = Files::new();
    std::fs::write(files.sidecar(), b"owned-existing-evidence").unwrap();
    capture(&files, true, false);
    assert_eq!(
        std::fs::read(files.sidecar()).unwrap(),
        b"owned-existing-evidence"
    );
    let notice = take_cpu_substage_export_notice().unwrap();
    assert!(notice.error.is_some());
    assert_eq!(notice.output_path, files.sidecar());
    let report: Value = serde_json::from_slice(&files.primary()).unwrap();
    assert_eq!(report["status"]["state"], "complete");
}

#[test]
fn disabled_substage_hooks_never_read_clock_or_write_files() {
    let clock = Clock::default();
    let mut session = PerformanceSession::new(clock.clone());
    for stage in [
        CpuSubstage::AcquireTexture,
        CpuSubstage::AcquireValidation,
        CpuSubstage::EncodeSubmit,
        CpuSubstage::SubmitValidation,
    ] {
        session.begin_cpu_substage(stage);
        session.end_cpu_substage(stage);
    }
    assert_eq!(clock.reads.get(), 0);
}

#[test]
fn backwards_optional_child_clock_does_not_poison_primary_clock_witness() {
    let files = Files::new();
    let clock = Clock::default();
    let mut session = PerformanceSession::new(clock.clone());
    session
        .start(identity(), files.0.clone(), CaptureLimits::default())
        .unwrap();
    clock.time.set(10);
    assert!(session.present_success().is_none());
    clock.time.set(11);
    session.begin_cpu_frame(1920, 1080);
    clock.time.set(12);
    session.begin_cpu_stage(CpuFrameStage::SurfaceAcquire);
    clock.time.set(1);
    session.begin_cpu_substage(CpuSubstage::AcquireTexture);
    clock.time.set(2);
    session.end_cpu_substage(CpuSubstage::AcquireTexture);
    clock.time.set(20);
    session.end_cpu_stage(CpuFrameStage::SurfaceAcquire);
    clock.time.set(21);
    session.request_stop();
    clock.time.set(22);
    let result = session.present_success().unwrap();
    assert_eq!(result.report.status, CaptureStatus::Complete);
    assert_eq!(result.report.summary.total_interval_ns, 12);
    assert_eq!(result.export.unwrap(), CaptureStatus::Complete);
    let details = files.details();
    assert_eq!(details["samples"][0]["details"]["state"], "incomplete");
    assert_eq!(
        details["samples"][0]["details"]["error"],
        "non_monotonic_substage"
    );
}

#[test]
fn forward_child_outside_parent_is_incomplete_without_poisoning_primary() {
    let files = Files::new();
    let clock = Clock::default();
    let mut session = PerformanceSession::new(clock.clone());
    session
        .start(identity(), files.0.clone(), CaptureLimits::default())
        .unwrap();
    clock.time.set(10);
    assert!(session.present_success().is_none());
    clock.time.set(11);
    session.begin_cpu_frame(1920, 1080);
    clock.time.set(12);
    session.begin_cpu_stage(CpuFrameStage::SurfaceAcquire);
    clock.time.set(13);
    session.begin_cpu_substage(CpuSubstage::AcquireTexture);
    clock.time.set(100);
    session.end_cpu_substage(CpuSubstage::AcquireTexture);
    clock.time.set(20);
    session.end_cpu_stage(CpuFrameStage::SurfaceAcquire);
    clock.time.set(21);
    session.request_stop();
    clock.time.set(22);
    let result = session.present_success().unwrap();
    assert_eq!(result.report.status, CaptureStatus::Complete);
    assert_eq!(result.report.summary.total_interval_ns, 12);
    let details = files.details();
    assert_eq!(details["samples"][0]["details"]["state"], "incomplete");
    assert_eq!(
        details["samples"][0]["details"]["error"],
        "substage_outside_parent"
    );
    assert_eq!(
        details["samples"][0]["details"]["spans"][0]["ended_at_ns"],
        100
    );
}
