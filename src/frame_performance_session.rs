//! Opt-in application bridge for CPU wall-clock present-return evidence.
//!
//! The thread-local session is empty by default. Disabled hooks neither sample a
//! clock nor allocate a timing buffer nor touch the filesystem. Enable only
//! after obtaining runtime identity from the renderer that is actually in use.
//! F8 simulation telemetry is a separate facility and is not used here.
use crate::frame_performance::{
    BoundaryReason, CaptureError, CaptureLimits, CaptureStatus, Eligibility,
    FramePerformanceObserver, FramePerformanceReport, RunIdentity, WindowContext, WriteError,
};
use std::cell::RefCell;
use std::fmt;
use std::path::PathBuf;
use std::time::Instant;

/// Supply a single monotonic nanosecond timeline. This seam makes tests use the
/// real session state machine without reading simulation time or sleeping.
pub trait MonotonicClock {
    fn now_ns(&mut self) -> u64;
}

/// Its epoch is created only by the first explicitly enabled capture.
pub struct InstantClock {
    epoch: Option<Instant>,
}
impl InstantClock {
    pub const fn new() -> Self {
        Self { epoch: None }
    }
}
impl Default for InstantClock {
    fn default() -> Self {
        Self::new()
    }
}
impl MonotonicClock for InstantClock {
    fn now_ns(&mut self) -> u64 {
        let now = Instant::now();
        let epoch = *self.epoch.get_or_insert(now);
        // A u64 nanosecond timeline spans more than 584 years. Saturating at
        // its end is monotonic and avoids a wrapping clock on an ancient run.
        now.duration_since(epoch).as_nanos().min(u64::MAX as u128) as u64
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SessionStartError {
    AlreadyActive,
    Observer(CaptureError),
}
impl fmt::Display for SessionStartError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::AlreadyActive => f.write_str("a frame-performance capture is already active"),
            Self::Observer(error) => error.fmt(f),
        }
    }
}
impl std::error::Error for SessionStartError {}

/// Returned once, when a capture leaves the active state. An export failure is
/// explicit and retains the report for inspection; it is never a success claim.
#[derive(Debug)]
pub struct SessionCompletion {
    pub report: FramePerformanceReport,
    pub output_path: PathBuf,
    pub export: Result<CaptureStatus, WriteError>,
}

/// Consistent application diagnostics: writing partial evidence successfully is
/// not described as a complete run, and a failed export names its stage/path.
pub fn log_completion(completion: Option<SessionCompletion>) {
    let Some(completion) = completion else {
        return;
    };
    match completion.export {
        Ok(CaptureStatus::Complete) => eprintln!(
            "frame-performance evidence saved to {} ({} eligible CPU present-return intervals; hardware unclassified)",
            completion.output_path.display(),
            completion.report.summary.interval_count
        ),
        Ok(CaptureStatus::Incomplete(error)) => eprintln!(
            "incomplete frame-performance evidence saved to {}: {error}",
            completion.output_path.display()
        ),
        Err(error) => eprintln!(
            "frame-performance export failed for {}: {error}",
            completion.output_path.display()
        ),
    }
}

struct ActiveCapture {
    observer: FramePerformanceObserver,
    output_path: PathBuf,
    eligibility: Eligibility,
    window: WindowContext,
    stop_requested_ns: Option<u64>,
    // Stop requests observe time without adding a present or breaking the
    // interval chain. Keep their clock witness separate from retained records.
    last_clock_ns: u64,
    clock_failure: Option<(u64, CaptureError)>,
}
impl ActiveCapture {
    fn observe_clock(&mut self, at_ns: u64) -> bool {
        if self.clock_failure.is_some() {
            return false;
        }
        if at_ns < self.last_clock_ns {
            self.clock_failure = Some((
                at_ns,
                CaptureError::NonMonotonicTimestamp {
                    previous_ns: self.last_clock_ns,
                    received_ns: at_ns,
                },
            ));
            return false;
        }
        self.last_clock_ns = at_ns;
        true
    }
}

/// The same session implementation is used by runtime TLS and synthetic-clock
/// contract tests. No renderer, GPU, simulation clock or global output is needed.
pub struct PerformanceSession<C> {
    clock: C,
    active: Option<ActiveCapture>,
}
impl<C: MonotonicClock> PerformanceSession<C> {
    pub const fn new(clock: C) -> Self {
        Self {
            clock,
            active: None,
        }
    }

    pub fn is_active(&self) -> bool {
        self.active.is_some()
    }

    pub fn is_stop_requested(&self) -> bool {
        self.active
            .as_ref()
            .is_some_and(|active| active.stop_requested_ns.is_some())
    }

    /// Starting does not create the output file. Export uses exclusive creation
    /// at completion, so existing telemetry or earlier reports stay untouched.
    pub fn start(
        &mut self,
        identity: RunIdentity,
        output_path: PathBuf,
        limits: CaptureLimits,
    ) -> Result<(), SessionStartError> {
        if self.active.is_some() {
            return Err(SessionStartError::AlreadyActive);
        }
        let window = identity.runtime.initial_window;
        let started_at_ns = self.clock.now_ns();
        let observer = FramePerformanceObserver::start(identity, started_at_ns, limits)
            .map_err(SessionStartError::Observer)?;
        self.active = Some(ActiveCapture {
            observer,
            output_path,
            eligibility: Eligibility::Eligible,
            window,
            stop_requested_ns: None,
            last_clock_ns: started_at_ns,
            clock_failure: None,
        });
        Ok(())
    }

    /// Defer export until this application's pending frame has actually
    /// presented. Do not call stop here: it would omit the user's final frame.
    pub fn request_stop(&mut self) {
        if let Some(active) = &mut self.active {
            if active.stop_requested_ns.is_none() {
                let at_ns = self.clock.now_ns();
                active.stop_requested_ns = Some(at_ns);
                active.observe_clock(at_ns);
            }
        }
    }

    /// Eligibility persists across every success until explicitly changed.
    /// Record transitions even when no present occurred while excluded.
    pub fn set_eligibility(&mut self, eligibility: Eligibility) -> Option<SessionCompletion> {
        let active = self.active.as_mut()?;
        if active.eligibility == eligibility {
            return None;
        }
        let reason = match (active.eligibility, eligibility) {
            (_, Eligibility::Ineligible(reason)) => reason,
            (Eligibility::Ineligible(BoundaryReason::FocusLost), Eligibility::Eligible) => {
                BoundaryReason::FocusRegained
            }
            (Eligibility::Ineligible(BoundaryReason::Paused), Eligibility::Eligible) => {
                BoundaryReason::Resumed
            }
            _ => BoundaryReason::CallerExcluded,
        };
        active.eligibility = eligibility;
        self.boundary(reason)
    }

    /// A transient exclusion breaks the interval chain without silently
    /// resetting the persistent pause/focus/diagnostic eligibility state.
    pub fn boundary(&mut self, reason: BoundaryReason) -> Option<SessionCompletion> {
        let active = self.active.as_mut()?;
        let at_ns = self.clock.now_ns();
        if !active.observe_clock(at_ns) {
            return self.finish(at_ns, None);
        }
        if active.observer.boundary(at_ns, reason).is_err() {
            return self.finish(at_ns, None);
        }
        None
    }

    /// Store the observed physical window context. Unchanged contexts are
    /// no-ops, allowing callers to report current state every application frame.
    pub fn update_window_context(&mut self, context: WindowContext) -> Option<SessionCompletion> {
        let active = self.active.as_mut()?;
        if active.window == context {
            return None;
        }
        let at_ns = self.clock.now_ns();
        if !active.observe_clock(at_ns) {
            return self.finish(at_ns, None);
        }
        active.window = context;
        if active
            .observer
            .update_window_context(at_ns, context)
            .is_err()
        {
            return self.finish(at_ns, None);
        }
        None
    }

    /// Invoke immediately after a successful renderer present returns. Only
    /// this method records a successful-present event, including the final one.
    pub fn present_success(&mut self) -> Option<SessionCompletion> {
        let active = self.active.as_mut()?;
        let at_ns = self.clock.now_ns();
        if !active.observe_clock(at_ns) {
            return self.finish(at_ns, None);
        }
        let failed = active
            .observer
            .record_present_return(at_ns, active.eligibility)
            .is_err();
        if failed || active.stop_requested_ns.is_some() {
            return self.finish(at_ns, None);
        }
        None
    }

    /// Submission/acquisition failure is not a successful present, even if a
    /// caller previously requested stop. Retain and export incomplete evidence.
    pub fn present_failure(&mut self) -> Option<SessionCompletion> {
        self.finish_missing_present(BoundaryReason::SurfaceError, CaptureError::PresentFailed)
    }

    /// An active surface-acquisition retry is retained without resetting the
    /// successful-present anchor: the eventual long interval is real evidence.
    /// Focus, pause, minimize and resize exclusions use their separate hooks.
    /// When stopping, a skipped final frame makes the capture incomplete.
    pub fn present_skipped(&mut self) -> Option<SessionCompletion> {
        let active = self.active.as_mut()?;
        let at_ns = self.clock.now_ns();
        if !active.observe_clock(at_ns) {
            return self.finish(at_ns, None);
        }
        let failed = active
            .observer
            .record_skipped_frame(at_ns, BoundaryReason::SurfaceSkipped)
            .is_err();
        let stopping = active.stop_requested_ns.is_some();
        if failed || stopping {
            return self.finish(at_ns, stopping.then_some(CaptureError::FinalPresentMissing));
        }
        None
    }

    /// Close a still-active run on runtime shutdown. A normal completed final
    /// present already consumed the session, so this is then a disabled no-op.
    pub fn shutdown(&mut self) -> Option<SessionCompletion> {
        self.finish_missing_present(BoundaryReason::Shutdown, CaptureError::FinalPresentMissing)
    }

    fn finish_missing_present(
        &mut self,
        reason: BoundaryReason,
        error: CaptureError,
    ) -> Option<SessionCompletion> {
        let active = self.active.as_mut()?;
        let at_ns = self.clock.now_ns();
        if !active.observe_clock(at_ns) {
            return self.finish(at_ns, None);
        }
        // Preserve an earlier clock/context/buffer error; the observer latches
        // it when this boundary cannot be retained.
        let _ = active.observer.boundary(at_ns, reason);
        self.finish(at_ns, Some(error))
    }

    fn finish(
        &mut self,
        at_ns: u64,
        final_error: Option<CaptureError>,
    ) -> Option<SessionCompletion> {
        let active = self.active.take()?;
        let mut report = active.observer.stop(at_ns);
        if let Some(requested_at) = active.stop_requested_ns {
            report.stop_requested_ns = requested_at;
        }
        if let Some((failed_at, error)) = active.clock_failure {
            report.status = CaptureStatus::Incomplete(error);
            report.incomplete_at_ns = Some(failed_at);
            if at_ns < active.last_clock_ns {
                report.stopped_at_ns = None;
            }
        }
        if let Some(error) = final_error {
            if matches!(
                report.status,
                CaptureStatus::Complete
                    | CaptureStatus::Incomplete(CaptureError::NoEligibleIntervals)
            ) {
                report.status = CaptureStatus::Incomplete(error);
                report.incomplete_at_ns = Some(at_ns);
            }
        }
        let export = report.write_new(&active.output_path);
        Some(SessionCompletion {
            report,
            output_path: active.output_path,
            export,
        })
    }
}

thread_local! {
    static SESSION: RefCell<PerformanceSession<InstantClock>> = const {
        RefCell::new(PerformanceSession::new(InstantClock::new()))
    };
}

pub fn is_active() -> bool {
    SESSION.with(|session| session.borrow().is_active())
}
pub fn is_stop_requested() -> bool {
    SESSION.with(|session| session.borrow().is_stop_requested())
}
pub fn start(
    identity: RunIdentity,
    output_path: PathBuf,
    limits: CaptureLimits,
) -> Result<(), SessionStartError> {
    SESSION.with(|session| session.borrow_mut().start(identity, output_path, limits))
}
pub fn request_stop() {
    SESSION.with(|session| session.borrow_mut().request_stop());
}
pub fn set_eligibility(eligibility: Eligibility) -> Option<SessionCompletion> {
    SESSION.with(|session| session.borrow_mut().set_eligibility(eligibility))
}
pub fn update_window_context(context: WindowContext) -> Option<SessionCompletion> {
    SESSION.with(|session| session.borrow_mut().update_window_context(context))
}
pub fn boundary(reason: BoundaryReason) -> Option<SessionCompletion> {
    SESSION.with(|session| session.borrow_mut().boundary(reason))
}
pub fn present_success() -> Option<SessionCompletion> {
    SESSION.with(|session| session.borrow_mut().present_success())
}
pub fn present_failure() -> Option<SessionCompletion> {
    SESSION.with(|session| session.borrow_mut().present_failure())
}
pub fn present_skipped() -> Option<SessionCompletion> {
    SESSION.with(|session| session.borrow_mut().present_skipped())
}
pub fn shutdown() -> Option<SessionCompletion> {
    SESSION.with(|session| session.borrow_mut().shutdown())
}
