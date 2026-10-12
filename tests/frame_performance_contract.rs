//! Deterministic tests of the real observer with injected monotonic timestamps.
//! No GPU, window, private assets, clock sleeps, or performance pass budget.
#[path = "../src/frame_performance.rs"]
mod frame_performance;

use frame_performance::*;
use serde_json::json;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};

fn window() -> WindowContext {
    WindowContext {
        physical_width: 1920,
        physical_height: 1080,
        scale_factor: 1.25,
        mode: WindowMode::Windowed,
    }
}
fn identity() -> RunIdentity {
    RunIdentity {
        runtime: RuntimeIdentity {
            actual_backend: Some("Dx12".into()),
            actual_adapter: json!({"name":"original synthetic test adapter","device_type":"unknown"}),
            build: json!({"commit":"synthetic-fixture","label":"unit-test-only"}),
            initial_window: window(),
            scene: json!({"name":"synthetic test","settings":{"vsync":true}}),
        },
        operator_supplied: json!({"machine_label":"operator claim, not verified hardware evidence"}),
    }
}
fn observer() -> FramePerformanceObserver {
    FramePerformanceObserver::start(identity(), 100, CaptureLimits::default()).unwrap()
}
fn complete_report() -> FramePerformanceReport {
    let mut observer = observer();
    observer
        .record_present_return(100, Eligibility::Eligible)
        .unwrap();
    observer
        .record_present_return(200, Eligibility::Eligible)
        .unwrap();
    observer.stop(210)
}
fn scratch_path(label: &str) -> PathBuf {
    static ID: AtomicU64 = AtomicU64::new(0);
    std::env::temp_dir().join(format!(
        "rust-duty-frame-perf-{}-{}-{label}",
        std::process::id(),
        ID.fetch_add(1, Ordering::Relaxed)
    ))
}

#[test]
fn successful_presents_are_separate_from_intervals_and_stop_is_not_a_present() {
    let mut observer = observer();
    observer
        .record_present_return(110, Eligibility::Eligible)
        .unwrap();
    observer
        .record_present_return(210, Eligibility::Eligible)
        .unwrap();
    observer
        .record_present_return(410, Eligibility::Eligible)
        .unwrap();
    let report = observer.stop(1_000_000);
    assert!(report.status.is_complete());
    assert_eq!(report.successful_present_count, 3);
    assert_eq!(report.summary.interval_count, 2);
    assert_eq!(report.summary.total_interval_ns, 300);
    assert_eq!(report.summary.min_ns, Some(100));
    assert_eq!(report.summary.max_ns, Some(200));
    assert_eq!(
        report.raw_records()[0].kind,
        RecordKind::PresentReturn {
            eligibility: Eligibility::Eligible,
            interval_ns: None
        }
    );
    assert_eq!(report.stopped_at_ns, Some(1_000_000));
}

#[test]
fn exact_nearest_rank_percentiles_use_sorted_retained_values_without_interpolation() {
    let mut observer = observer();
    let mut at = 100;
    observer
        .record_present_return(at, Eligibility::Eligible)
        .unwrap();
    for delta in (1..=100).rev() {
        at += delta;
        observer
            .record_present_return(at, Eligibility::Eligible)
            .unwrap();
    }
    let report = observer.stop(at);
    assert_eq!(report.summary.interval_count, 100);
    assert_eq!(report.summary.p50_ns, Some(50));
    assert_eq!(report.summary.p95_ns, Some(95));
    assert_eq!(report.summary.p99_ns, Some(99));
    assert_eq!(report.summary.total_interval_ns, 5050);
    // Raw order survives sorting for the summary.
    assert_eq!(
        report.raw_records()[1].kind,
        RecordKind::PresentReturn {
            eligibility: Eligibility::Eligible,
            interval_ns: Some(100)
        }
    );
}

#[test]
fn nearest_rank_handles_small_and_odd_sample_sets() {
    for (deltas, p50, p95, p99) in [
        (vec![9], 9, 9, 9),
        (vec![40, 10, 30, 20], 20, 40, 40),
        (vec![100, 1, 7], 7, 100, 100),
    ] {
        let mut observer = observer();
        let mut at = 100;
        observer
            .record_present_return(at, Eligibility::Eligible)
            .unwrap();
        for delta in deltas {
            at += delta;
            observer
                .record_present_return(at, Eligibility::Eligible)
                .unwrap();
        }
        let report = observer.stop(at);
        assert_eq!(
            (
                report.summary.p50_ns,
                report.summary.p95_ns,
                report.summary.p99_ns
            ),
            (Some(p50), Some(p95), Some(p99))
        );
    }
}

#[test]
fn a_long_hitch_is_retained_even_beyond_simulation_clamp_and_has_no_pass_threshold() {
    let mut observer = observer();
    observer
        .record_present_return(100, Eligibility::Eligible)
        .unwrap();
    observer
        .record_present_return(5_000_000_100, Eligibility::Eligible)
        .unwrap();
    let report = observer.stop(5_000_000_100);
    assert_eq!(report.summary.p99_ns, Some(5_000_000_000));
    assert!(report.status.is_complete());
    let encoded = report.to_json();
    assert_eq!(encoded["measurement"], MEASUREMENT);
    assert!(encoded.get("performance_pass").is_none());
    assert!(encoded["interpretation"]
        .as_str()
        .unwrap()
        .contains("not GPU time"));
}

#[test]
fn exclusions_are_per_present_and_do_not_bridge_back_into_eligible_gameplay() {
    let mut observer = observer();
    observer
        .record_present_return(100, Eligibility::Eligible)
        .unwrap();
    observer
        .record_present_return(120, Eligibility::Eligible)
        .unwrap();
    observer
        .record_present_return(500, Eligibility::Ineligible(BoundaryReason::Paused))
        .unwrap();
    observer
        .record_present_return(700, Eligibility::Ineligible(BoundaryReason::Paused))
        .unwrap();
    observer
        .record_present_return(1_000, Eligibility::Eligible)
        .unwrap();
    observer
        .record_present_return(1_030, Eligibility::Eligible)
        .unwrap();
    let report = observer.stop(1_100);
    assert_eq!(report.successful_present_count, 6);
    assert_eq!(report.ineligible_present_count, 2);
    assert_eq!(report.summary.interval_count, 2);
    assert_eq!(report.summary.total_interval_ns, 50);
    assert_eq!(
        report.to_json()["records"][2]["ineligible_reason"],
        "paused"
    );
}

#[test]
fn every_explicit_boundary_breaks_the_chain_without_claiming_a_present() {
    for reason in [
        BoundaryReason::FocusLost,
        BoundaryReason::FocusRegained,
        BoundaryReason::Paused,
        BoundaryReason::Resumed,
        BoundaryReason::Resize,
        BoundaryReason::Minimized,
        BoundaryReason::SurfaceSkipped,
        BoundaryReason::SurfaceError,
        BoundaryReason::CaptureReadback,
        BoundaryReason::DiagnosticCapture,
        BoundaryReason::RendererChanged,
        BoundaryReason::SceneChanged,
        BoundaryReason::CallerExcluded,
        BoundaryReason::Shutdown,
    ] {
        let mut observer = observer();
        observer
            .record_present_return(100, Eligibility::Eligible)
            .unwrap();
        observer.boundary(200, reason).unwrap();
        observer
            .record_present_return(1_000, Eligibility::Eligible)
            .unwrap();
        observer
            .record_present_return(1_010, Eligibility::Eligible)
            .unwrap();
        let report = observer.stop(1_020);
        assert_eq!(report.successful_present_count, 3, "{reason:?}");
        assert_eq!(report.summary.interval_count, 1);
        assert_eq!(report.summary.total_interval_ns, 10);
        assert_eq!(
            report.raw_records()[1].kind,
            RecordKind::Boundary { reason }
        );
    }
}

#[test]
fn context_updates_retain_size_scale_and_mode_and_start_new_segments() {
    for mode in [
        WindowMode::Unknown,
        WindowMode::Windowed,
        WindowMode::Borderless,
        WindowMode::ExclusiveFullscreen,
    ] {
        let mut observer = observer();
        let context = WindowContext {
            physical_width: 0,
            physical_height: 0,
            scale_factor: 2.0,
            mode,
        };
        observer
            .record_present_return(100, Eligibility::Eligible)
            .unwrap();
        observer.update_window_context(200, context).unwrap();
        observer.boundary(300, BoundaryReason::Minimized).unwrap();
        observer.update_window_context(400, window()).unwrap();
        observer
            .record_present_return(500, Eligibility::Eligible)
            .unwrap();
        observer
            .record_present_return(600, Eligibility::Eligible)
            .unwrap();
        let report = observer.stop(700);
        assert_eq!(
            report.raw_records()[1].kind,
            RecordKind::WindowContext { context }
        );
        assert_eq!(report.summary.interval_count, 1);
        assert_eq!(report.summary.p99_ns, Some(100));
        assert_eq!(report.identity.runtime.initial_window, window());
        assert_eq!(
            report.to_json()["records"][1]["context"]["scale_factor"],
            2.0
        );
    }
}

#[test]
fn capacity_exhaustion_is_latched_exportable_and_never_silently_drops_samples() {
    let mut observer = FramePerformanceObserver::start(
        identity(),
        100,
        CaptureLimits {
            max_records: 2,
            ..CaptureLimits::default()
        },
    )
    .unwrap();
    observer
        .record_present_return(100, Eligibility::Eligible)
        .unwrap();
    observer
        .record_present_return(120, Eligibility::Eligible)
        .unwrap();
    let error = CaptureError::RecordLimitExceeded { max_records: 2 };
    assert_eq!(
        observer.record_present_return(140, Eligibility::Eligible),
        Err(error)
    );
    assert_eq!(
        observer.boundary(150, BoundaryReason::SurfaceError),
        Err(error)
    );
    assert_eq!(
        observer.record_present_return(160, Eligibility::Eligible),
        Err(error)
    );
    let report = observer.stop(200);
    assert_eq!(report.status, CaptureStatus::Incomplete(error));
    assert_eq!(report.incomplete_at_ns, Some(140));
    assert_eq!(report.raw_records().len(), 2);
    assert_eq!(report.successful_present_count, 2);
    assert_eq!(report.summary.interval_count, 1);
    assert_eq!(report.to_json()["status"]["state"], "incomplete");
}

#[test]
fn boundaries_and_context_changes_share_the_same_bounded_event_budget() {
    let mut observer = FramePerformanceObserver::start(
        identity(),
        100,
        CaptureLimits {
            max_records: 2,
            ..CaptureLimits::default()
        },
    )
    .unwrap();
    observer
        .boundary(110, BoundaryReason::SurfaceSkipped)
        .unwrap();
    observer.update_window_context(120, window()).unwrap();
    assert_eq!(
        observer.boundary(130, BoundaryReason::SurfaceError),
        Err(CaptureError::RecordLimitExceeded { max_records: 2 })
    );
    let report = observer.stop(140);
    assert_eq!(report.raw_records().len(), 2);
    assert_eq!(report.successful_present_count, 0);
}

#[test]
fn backwards_timestamps_fail_all_event_paths_and_preserve_first_failure() {
    for event in 0..4 {
        let mut observer = observer();
        observer
            .record_present_return(200, Eligibility::Eligible)
            .unwrap();
        let error = CaptureError::NonMonotonicTimestamp {
            previous_ns: 200,
            received_ns: 199,
        };
        let result = match event {
            0 => observer.record_present_return(199, Eligibility::Eligible),
            1 => observer.boundary(199, BoundaryReason::Resize),
            2 => observer.update_window_context(199, window()),
            _ => observer.record_skipped_frame(199, BoundaryReason::SurfaceSkipped),
        };
        assert_eq!(result, Err(error));
        assert_eq!(
            observer.record_present_return(300, Eligibility::Eligible),
            Err(error)
        );
        let report = observer.stop(400);
        assert_eq!(report.status, CaptureStatus::Incomplete(error));
        assert_eq!(report.incomplete_at_ns, Some(199));
        assert_eq!(report.raw_records().len(), 1);
    }
}

#[test]
fn invalid_stop_is_incomplete_instead_of_wrapping_duration() {
    let mut observer = observer();
    observer
        .record_present_return(150, Eligibility::Eligible)
        .unwrap();
    observer
        .record_present_return(200, Eligibility::Eligible)
        .unwrap();
    let report = observer.stop(199);
    assert_eq!(
        report.status,
        CaptureStatus::Incomplete(CaptureError::NonMonotonicTimestamp {
            previous_ns: 200,
            received_ns: 199
        })
    );
    assert_eq!(report.stopped_at_ns, None);
    assert_eq!(report.stop_requested_ns, 199);
    assert_eq!(report.last_observed_ns, 200);
    assert_eq!(report.summary.total_interval_ns, 50);
}

#[test]
fn equal_monotonic_ticks_and_full_u64_intervals_are_exact() {
    let mut observer =
        FramePerformanceObserver::start(identity(), 0, CaptureLimits::default()).unwrap();
    observer
        .record_present_return(0, Eligibility::Eligible)
        .unwrap();
    observer
        .record_present_return(0, Eligibility::Eligible)
        .unwrap();
    observer
        .record_present_return(u64::MAX, Eligibility::Eligible)
        .unwrap();
    let report = observer.stop(u64::MAX);
    assert!(report.status.is_complete());
    assert_eq!(report.summary.min_ns, Some(0));
    assert_eq!(report.summary.max_ns, Some(u64::MAX));
    assert_eq!(report.summary.total_interval_ns, u64::MAX);
    assert_eq!(
        report.to_json()["summary"]["p99_ns"].as_u64(),
        Some(u64::MAX)
    );
}

#[test]
fn empty_single_present_and_all_excluded_runs_are_explicitly_incomplete() {
    for count in 0..3 {
        let mut observer = observer();
        if count == 1 {
            observer
                .record_present_return(100, Eligibility::Eligible)
                .unwrap();
        }
        if count == 2 {
            observer
                .record_present_return(
                    100,
                    Eligibility::Ineligible(BoundaryReason::DiagnosticCapture),
                )
                .unwrap();
            observer
                .record_present_return(
                    200,
                    Eligibility::Ineligible(BoundaryReason::DiagnosticCapture),
                )
                .unwrap();
        }
        let report = observer.stop(300);
        assert_eq!(
            report.status,
            CaptureStatus::Incomplete(CaptureError::NoEligibleIntervals)
        );
        assert_eq!(report.summary.interval_count, 0);
        assert_eq!(report.summary.p50_ns, None);
        assert_eq!(report.summary.p95_ns, None);
        assert_eq!(report.summary.p99_ns, None);
        assert_eq!(report.summary.total_interval_ns, 0);
    }
}

#[test]
fn invalid_limits_and_oversized_identity_are_rejected_before_observation() {
    for limits in [
        CaptureLimits {
            max_records: 0,
            ..CaptureLimits::default()
        },
        CaptureLimits {
            max_records: usize::MAX,
            ..CaptureLimits::default()
        },
        CaptureLimits {
            max_metadata_bytes: 0,
            ..CaptureLimits::default()
        },
        CaptureLimits {
            max_metadata_bytes: usize::MAX,
            ..CaptureLimits::default()
        },
    ] {
        assert!(matches!(
            FramePerformanceObserver::start(identity(), 100, limits),
            Err(CaptureError::InvalidLimits)
        ));
    }
    let mut oversized = identity();
    oversized.operator_supplied = json!({"note":"x".repeat(70_000)});
    assert!(matches!(
        FramePerformanceObserver::start(oversized, 100, CaptureLimits::default()),
        Err(CaptureError::MetadataLimitExceeded)
    ));
}

#[test]
fn invalid_scale_factors_are_rejected_at_start_and_latched_during_capture() {
    for scale_factor in [0.0, -1.0, f64::INFINITY, f64::NEG_INFINITY, f64::NAN] {
        let mut invalid = identity();
        invalid.runtime.initial_window.scale_factor = scale_factor;
        assert!(matches!(
            FramePerformanceObserver::start(invalid, 100, CaptureLimits::default()),
            Err(CaptureError::InvalidWindowContext)
        ));
        let mut observer = observer();
        let mut invalid_window = window();
        invalid_window.scale_factor = scale_factor;
        assert_eq!(
            observer.update_window_context(200, invalid_window),
            Err(CaptureError::InvalidWindowContext)
        );
        assert_eq!(
            observer.stop(300).status,
            CaptureStatus::Incomplete(CaptureError::InvalidWindowContext)
        );
    }
}

#[test]
fn actual_runtime_and_operator_claims_stay_separate_and_hardware_remains_unknown() {
    let mut identity = identity();
    identity.operator_supplied =
        json!({"actual_backend":"operator requested Vulkan","hardware_classification":"high_end"});
    let original = identity.clone();
    let observer =
        FramePerformanceObserver::start(identity, 100, CaptureLimits::default()).unwrap();
    let report = observer.stop(200);
    assert_eq!(report.identity, original);
    let json = report.to_json();
    assert_eq!(
        json["identity"]["runtime_observed"]["actual_backend"],
        "Dx12"
    );
    assert_eq!(
        json["identity"]["operator_supplied"]["actual_backend"],
        "operator requested Vulkan"
    );
    assert_eq!(json["identity"]["hardware_classification"], "unknown");
}

#[test]
fn unavailable_runtime_identity_is_null_not_fabricated() {
    let mut identity = identity();
    identity.runtime.actual_backend = None;
    identity.runtime.actual_adapter = serde_json::Value::Null;
    identity.runtime.build = serde_json::Value::Null;
    identity.runtime.scene = serde_json::Value::Null;
    let observer =
        FramePerformanceObserver::start(identity, 100, CaptureLimits::default()).unwrap();
    let json = observer.stop(200).to_json();
    assert!(json["identity"]["runtime_observed"]["actual_backend"].is_null());
    assert!(json["identity"]["runtime_observed"]["actual_adapter"].is_null());
    assert_eq!(json["identity"]["hardware_classification"], "unknown");
}

#[test]
fn complete_report_roundtrips_and_never_overwrites_existing_output() {
    let path = scratch_path("report.json");
    let report = complete_report();
    assert_eq!(report.write_new(&path).unwrap(), CaptureStatus::Complete);
    let original = std::fs::read(&path).unwrap();
    let parsed: serde_json::Value = serde_json::from_slice(&original).unwrap();
    assert_eq!(parsed, report.to_json());
    let error = report.write_new(&path).unwrap_err();
    assert_eq!(error.stage, WriteStage::Create);
    assert_eq!(error.source.kind(), std::io::ErrorKind::AlreadyExists);
    assert!(!error.partial_file_possible);
    assert_eq!(std::fs::read(&path).unwrap(), original);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn incomplete_report_write_returns_incomplete_status_and_serializes_failure() {
    let path = scratch_path("incomplete.json");
    let report = observer().stop(100);
    assert_eq!(
        report.write_new(&path).unwrap(),
        CaptureStatus::Incomplete(CaptureError::NoEligibleIntervals)
    );
    let parsed: serde_json::Value = serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    assert_eq!(parsed["status"]["state"], "incomplete");
    assert!(parsed["status"]["error"]
        .as_str()
        .unwrap()
        .contains("no eligible"));
    std::fs::remove_file(path).unwrap();
}

#[test]
fn missing_destination_parent_is_reported_without_claiming_a_saved_file() {
    let parent = scratch_path("missing");
    let path = parent.join("report.json");
    let error = complete_report().write_new(&path).unwrap_err();
    assert_eq!(error.stage, WriteStage::Create);
    assert!(!error.partial_file_possible);
    assert!(!path.exists());
    assert!(error.to_string().contains("failed"));
    assert!(std::error::Error::source(&error).is_some());
}

#[cfg(unix)]
#[test]
fn a_symlink_destination_is_never_followed_or_overwritten() {
    let target = scratch_path("symlink-target");
    let link = scratch_path("symlink-report");
    std::fs::write(&target, b"keep this content").unwrap();
    std::os::unix::fs::symlink(&target, &link).unwrap();
    assert_eq!(
        complete_report().write_new(&link).unwrap_err().stage,
        WriteStage::Create
    );
    assert_eq!(std::fs::read(&target).unwrap(), b"keep this content");
    std::fs::remove_file(link).unwrap();
    std::fs::remove_file(target).unwrap();
}

#[test]
fn session_finalization_failures_have_distinct_honest_descriptions() {
    assert!(CaptureError::PresentFailed
        .to_string()
        .contains("presentation failed"));
    assert!(CaptureError::FinalPresentMissing
        .to_string()
        .contains("before its final"));
}

#[test]
fn stop_before_a_rejected_forward_event_cannot_claim_a_valid_stop_timestamp() {
    let mut observer = FramePerformanceObserver::start(
        identity(),
        100,
        CaptureLimits {
            max_records: 1,
            ..CaptureLimits::default()
        },
    )
    .unwrap();
    observer
        .record_present_return(100, Eligibility::Eligible)
        .unwrap();
    let error = CaptureError::RecordLimitExceeded { max_records: 1 };
    assert_eq!(
        observer.record_present_return(300, Eligibility::Eligible),
        Err(error)
    );
    let report = observer.stop(200);
    assert_eq!(report.status, CaptureStatus::Incomplete(error));
    assert_eq!(report.stopped_at_ns, None);
    assert_eq!(report.incomplete_at_ns, Some(300));
}

#[test]
fn ordinary_surface_skips_preserve_the_entire_long_active_present_return_gap() {
    let mut observer = observer();
    observer
        .record_present_return(100, Eligibility::Eligible)
        .unwrap();
    observer
        .record_skipped_frame(1_000_000_100, BoundaryReason::SurfaceSkipped)
        .unwrap();
    observer
        .record_skipped_frame(2_000_000_100, BoundaryReason::SurfaceSkipped)
        .unwrap();
    observer
        .record_present_return(5_000_000_100, Eligibility::Eligible)
        .unwrap();
    let report = observer.stop(5_000_000_100);
    assert!(report.status.is_complete());
    assert_eq!(report.successful_present_count, 2);
    assert_eq!(report.skipped_frame_count, 2);
    assert_eq!(report.summary.interval_count, 1);
    assert_eq!(report.summary.p99_ns, Some(5_000_000_000));
    assert_eq!(report.summary.total_interval_ns, 5_000_000_000);
    assert_eq!(
        report.raw_records()[1],
        RawRecord {
            at_ns: 1_000_000_100,
            kind: RecordKind::SkippedFrame {
                reason: BoundaryReason::SurfaceSkipped
            }
        }
    );
    let json = report.to_json();
    assert_eq!(json["skipped_frame_count"], 2);
    assert_eq!(json["records"][1]["kind"], "skipped_frame");
    assert_eq!(json["records"][1]["resets_interval_anchor"], false);
}

#[test]
fn skips_do_not_create_a_present_anchor_or_undo_an_explicit_exclusion() {
    let mut observer = observer();
    observer
        .record_skipped_frame(200, BoundaryReason::SurfaceSkipped)
        .unwrap();
    observer
        .record_present_return(300, Eligibility::Eligible)
        .unwrap();
    observer.boundary(400, BoundaryReason::FocusLost).unwrap();
    observer
        .record_skipped_frame(500, BoundaryReason::SurfaceSkipped)
        .unwrap();
    observer
        .boundary(600, BoundaryReason::FocusRegained)
        .unwrap();
    observer
        .record_present_return(700, Eligibility::Eligible)
        .unwrap();
    observer
        .record_present_return(800, Eligibility::Eligible)
        .unwrap();
    let report = observer.stop(900);
    assert!(report.status.is_complete());
    assert_eq!(report.successful_present_count, 3);
    assert_eq!(report.skipped_frame_count, 2);
    assert_eq!(report.summary.interval_count, 1);
    assert_eq!(report.summary.total_interval_ns, 100);
}

#[test]
fn ordinary_skip_events_share_the_bounded_budget_and_latch_overflow() {
    let mut observer = FramePerformanceObserver::start(
        identity(),
        100,
        CaptureLimits {
            max_records: 2,
            ..CaptureLimits::default()
        },
    )
    .unwrap();
    observer
        .record_present_return(100, Eligibility::Eligible)
        .unwrap();
    observer
        .record_skipped_frame(200, BoundaryReason::SurfaceSkipped)
        .unwrap();
    let error = CaptureError::RecordLimitExceeded { max_records: 2 };
    assert_eq!(
        observer.record_skipped_frame(300, BoundaryReason::SurfaceSkipped),
        Err(error)
    );
    let report = observer.stop(400);
    assert_eq!(report.status, CaptureStatus::Incomplete(error));
    assert_eq!(report.successful_present_count, 1);
    assert_eq!(report.skipped_frame_count, 1);
    assert_eq!(report.raw_records().len(), 2);
}

#[test]
fn optional_cpu_stage_extension_keeps_v1_records_counts_and_primary_summary() {
    let mut traced = observer();
    traced.enable_cpu_frame_stages(100).unwrap();
    traced
        .record_present_return(110, Eligibility::Eligible)
        .unwrap();
    traced.record_cpu_frame_stages(
        CpuFrameStages {
            started_at_ns: 100,
            physical_width: 1920,
            physical_height: 1080,
            spans: [
                Some(CpuWallSpan {
                    started_at_ns: 101,
                    ended_at_ns: 109,
                }),
                None,
                None,
                None,
            ],
        },
        110,
    );
    traced
        .record_present_return(120, Eligibility::Eligible)
        .unwrap();
    let mut original = observer();
    original
        .record_present_return(110, Eligibility::Eligible)
        .unwrap();
    original
        .record_present_return(120, Eligibility::Eligible)
        .unwrap();
    let expected = original.stop(130).to_json();
    let mut actual = traced.stop(130).to_json();
    let extension = actual
        .as_object_mut()
        .unwrap()
        .remove("cpu_frame_stages")
        .unwrap();
    assert_eq!(actual, expected);
    assert_eq!(extension["samples"][0]["record_index"], 0);
    assert_eq!(
        extension["samples"][0]["spans"]["surface_acquire"]["duration_ns"],
        8
    );
    assert_eq!(extension["measurement"], CPU_STAGE_MEASUREMENT);
}
