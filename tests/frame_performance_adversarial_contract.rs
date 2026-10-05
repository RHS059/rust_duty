//! Stop-request clock validation through the production public session API.
//! Synthetic time is evidence-integrity coverage, not a native timing result.
use serde_json::Value;
use std::{
    cell::Cell,
    path::PathBuf,
    rc::Rc,
    sync::atomic::{AtomicU64, Ordering},
};
use vector_range::frame_performance::{
    BoundaryReason, CaptureError, CaptureLimits, CaptureStatus, Eligibility, RunIdentity,
    RuntimeIdentity, WindowContext, WindowMode,
};
use vector_range::frame_performance_session::{MonotonicClock, PerformanceSession};

#[derive(Clone)]
struct Clock(Rc<Cell<u64>>);
impl MonotonicClock for Clock {
    fn now_ns(&mut self) -> u64 {
        self.0.get()
    }
}
struct Output(PathBuf);
impl Drop for Output {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}
fn session() -> (PerformanceSession<Clock>, Clock, Output) {
    static NEXT: AtomicU64 = AtomicU64::new(0);
    let output = Output(std::env::temp_dir().join(format!(
        "rust-duty-stop-clock-{}-{}.json",
        std::process::id(),
        NEXT.fetch_add(1, Ordering::Relaxed)
    )));
    let clock = Clock(Rc::new(Cell::new(0)));
    let mut session = PerformanceSession::new(clock.clone());
    session
        .start(
            RunIdentity {
                runtime: RuntimeIdentity {
                    actual_backend: None,
                    actual_adapter: Value::Null,
                    build: Value::Null,
                    initial_window: WindowContext {
                        physical_width: 1,
                        physical_height: 1,
                        scale_factor: 1.,
                        mode: WindowMode::Unknown,
                    },
                    scene: Value::Null,
                },
                operator_supplied: Value::Null,
            },
            output.0.clone(),
            CaptureLimits::default(),
        )
        .unwrap();
    (session, clock, output)
}

#[test]
fn final_present_cannot_precede_its_observed_stop_request() {
    let (mut session, clock, _output) = session();
    clock.0.set(10);
    assert!(session.present_success().is_none());
    clock.0.set(20);
    session.request_stop();
    clock.0.set(15);
    let done = session.present_success().unwrap();
    let expected = CaptureStatus::Incomplete(CaptureError::NonMonotonicTimestamp {
        previous_ns: 20,
        received_ns: 15,
    });
    assert_eq!(done.report.status, expected);
    assert_eq!(done.export.unwrap(), expected);
    assert_eq!(done.report.successful_present_count, 1);
    assert_eq!(done.report.stop_requested_ns, 20);
    assert_eq!(done.report.stopped_at_ns, None);
    assert!(!session.is_active());
}

#[test]
fn intervening_callbacks_cannot_bypass_the_pending_stop_clock_witness() {
    for event in 0..6 {
        let (mut session, clock, _output) = session();
        clock.0.set(10);
        assert!(session.present_success().is_none());
        clock.0.set(20);
        session.request_stop();
        clock.0.set(15);
        let done = match event {
            0 => session.boundary(BoundaryReason::CaptureReadback),
            1 => session.update_window_context(WindowContext {
                physical_width: 2,
                physical_height: 1,
                scale_factor: 1.,
                mode: WindowMode::Windowed,
            }),
            2 => session.set_eligibility(Eligibility::Ineligible(BoundaryReason::Paused)),
            3 => session.present_skipped(),
            4 => session.present_failure(),
            _ => session.shutdown(),
        }
        .unwrap();
        let expected = CaptureStatus::Incomplete(CaptureError::NonMonotonicTimestamp {
            previous_ns: 20,
            received_ns: 15,
        });
        assert_eq!(done.report.status, expected, "callback {event}");
        assert_eq!(done.export.unwrap(), expected);
        assert_eq!(done.report.successful_present_count, 1);
        assert_eq!(done.report.raw_records().len(), 1);
        assert_eq!(done.report.stopped_at_ns, None);
        assert!(!session.is_active());
    }
}

#[test]
fn backwards_stop_request_is_not_erased_by_a_later_valid_final_present() {
    let (mut session, clock, _output) = session();
    clock.0.set(10);
    assert!(session.present_success().is_none());
    clock.0.set(5);
    session.request_stop();
    clock.0.set(20);
    let done = session.present_success().unwrap();
    let expected = CaptureStatus::Incomplete(CaptureError::NonMonotonicTimestamp {
        previous_ns: 10,
        received_ns: 5,
    });
    assert_eq!(done.report.status, expected);
    assert_eq!(done.export.unwrap(), expected);
    assert_eq!(done.report.successful_present_count, 1);
    assert_eq!(done.report.incomplete_at_ns, Some(5));
    assert!(!session.is_active());
}
