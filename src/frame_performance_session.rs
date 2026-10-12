//! Opt-in application bridge for CPU wall-clock present-return evidence.
//!
//! The thread-local session is empty by default. Disabled hooks neither sample a
//! clock nor allocate a timing buffer nor touch the filesystem. Enable only
//! after obtaining runtime identity from the renderer that is actually in use.
//! F8 simulation telemetry is a separate facility and is not used here.
use crate::frame_cpu_substages::{CpuSubstage, CpuSubstages};
use crate::frame_encode_detail::{CpuEncodeCapture, CpuEncodeDetails};
pub use crate::frame_encode_detail::{EncodeCounter, EncodePhase};
use crate::frame_performance::{
    BoundaryReason, CaptureError, CaptureLimits, CaptureStatus, CpuFrameStage, CpuFrameStages,
    CpuWallSpan, Eligibility, FramePerformanceObserver, FramePerformanceReport, RunIdentity,
    WindowContext, WriteError,
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

/// Latest completed export for the in-game recording controls. Capture
/// completeness and export failure remain separate, so UI cannot call a failed
/// file write a successful export. Only one pending notice is retained.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CompletionNotice {
    pub output_path: PathBuf,
    pub status: CaptureStatus,
    pub export_error: Option<String>,
}

/// Independent optional diagnostic export, never a replacement for frame status.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CpuSubstageExportNotice {
    pub output_path: PathBuf,
    pub error: Option<String>,
}
pub fn take_cpu_substage_export_notice() -> Option<CpuSubstageExportNotice> {
    LAST_CPU_SUBSTAGE_NOTICE.with(|notice| notice.borrow_mut().take())
}

/// Encode diagnostics export independently; failure does not alter primary status.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CpuEncodeDetailExportNotice {
    pub output_path: PathBuf,
    pub error: Option<String>,
}
pub fn take_cpu_encode_detail_export_notice() -> Option<CpuEncodeDetailExportNotice> {
    LAST_CPU_ENCODE_DETAIL_NOTICE.with(|notice| notice.borrow_mut().take())
}

#[cfg(feature = "wgpu-runtime")]
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GpuTimingExportNotice {
    pub output_path: PathBuf,
    pub accounting_complete: bool,
    pub export_error: Option<String>,
}
#[cfg(feature = "wgpu-runtime")]
pub fn take_gpu_timing_export_notice() -> Option<GpuTimingExportNotice> {
    LAST_GPU_TIMING_NOTICE.with(|notice| notice.borrow_mut().take())
}

/// Consume the latest completion once. Disabled polling reads no clocks/files.
pub fn take_completion_notice() -> Option<CompletionNotice> {
    LAST_COMPLETION_NOTICE.with(|notice| notice.borrow_mut().take())
}

/// Consistent application diagnostics: writing partial evidence successfully is
/// not described as a complete run, and a failed export names its stage/path.
pub fn log_completion(completion: Option<SessionCompletion>) {
    let Some(completion) = completion else {
        return;
    };
    LAST_COMPLETION_NOTICE.with(|notice| {
        *notice.borrow_mut() = Some(CompletionNotice {
            output_path: completion.output_path.clone(),
            status: completion.report.status,
            export_error: completion.export.as_ref().err().map(ToString::to_string),
        });
    });
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
    cpu_frame: Option<PendingCpuFrame>,
    encode_capture: CpuEncodeCapture,
    #[cfg(feature = "wgpu-runtime")]
    gpu_capture: Option<u64>,
    #[cfg(feature = "wgpu-runtime")]
    gpu_attempt: Option<crate::render::gpu_timing::FrameKey>,
}
struct PendingCpuFrame {
    frame: CpuFrameStages,
    open_stage: Option<(CpuFrameStage, u64)>,
    last_stage: Option<CpuFrameStage>,
    encode_details: CpuEncodeDetails,
}
impl ActiveCapture {
    fn retain_cpu_frame(&mut self, at_ns: u64) {
        if let Some(mut frame) = self.cpu_frame.take() {
            frame
                .encode_details
                .validate_substages(&frame.frame.substages);
            frame.encode_details.validate_bounds(
                frame.frame.started_at_ns,
                at_ns,
                frame.frame.spans[CpuFrameStage::RendererSubmit.index()],
            );
            self.encode_capture.retain(frame.encode_details);
            // Only matched begin/end pairs have spans. An interrupted stage is
            // unavailable; never synthesize its end from a failure or stop.
            self.observer.record_cpu_frame_stages(frame.frame, at_ns);
            #[cfg(feature = "wgpu-runtime")]
            if let Some(key) = self.gpu_attempt.take() {
                if let Some(index) = self.observer.last_record_index() {
                    crate::frame_gpu_capture::join_cpu_record(key, index);
                }
            }
        }
    }
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
            cpu_frame: None,
            encode_capture: CpuEncodeCapture::new(limits.max_records),
            #[cfg(feature = "wgpu-runtime")]
            gpu_capture: crate::frame_gpu_capture::start_session(limits.max_records),
            #[cfg(feature = "wgpu-runtime")]
            gpu_attempt: None,
        });
        Ok(())
    }

    /// Begin a frame attempt using the renderer's physical target dimensions.
    /// A capture enabled midway through an application frame starts timing on
    /// the next attempt, so it never invents the earlier acquisition/CPU work.
    pub fn begin_cpu_frame(&mut self, physical_width: u32, physical_height: u32) {
        let Some(active) = &mut self.active else {
            return;
        };
        let at_ns = self.clock.now_ns();
        active.cpu_frame = None;
        #[cfg(feature = "wgpu-runtime")]
        {
            active.gpu_attempt = None;
        }
        if !active.observe_clock(at_ns) || active.observer.enable_cpu_frame_stages(at_ns).is_err() {
            return;
        }
        active.encode_capture.begin_attempt();
        active.cpu_frame = Some(PendingCpuFrame {
            frame: CpuFrameStages {
                started_at_ns: at_ns,
                physical_width,
                physical_height,
                spans: [None; 4],
                substages: CpuSubstages::default(),
            },
            open_stage: None,
            last_stage: None,
            encode_details: CpuEncodeDetails::default(),
        });
        #[cfg(feature = "wgpu-runtime")]
        {
            active.gpu_attempt = active
                .gpu_capture
                .and_then(crate::frame_gpu_capture::begin_attempt);
        }
    }

    #[cfg(feature = "wgpu-runtime")]
    pub(crate) fn gpu_frame_key(&self) -> Option<crate::render::gpu_timing::FrameKey> {
        self.active.as_ref()?.gpu_attempt
    }

    pub fn begin_cpu_substage(&mut self, stage: CpuSubstage) {
        self.cpu_substage(stage, true);
    }
    pub fn end_cpu_substage(&mut self, stage: CpuSubstage) {
        self.cpu_substage(stage, false);
    }
    fn cpu_substage(&mut self, stage: CpuSubstage, begin: bool) {
        let Some(active) = &mut self.active else {
            return;
        };
        let Some(frame) = &mut active.cpu_frame else {
            return;
        };
        if frame.open_stage.map(|(parent, _)| parent.label()) != Some(stage.parent()) {
            frame.frame.substages.invalidate("substage_parent_mismatch");
            return;
        }
        let at_ns = self.clock.now_ns();
        // Optional diagnostics must never advance or invalidate the primary
        // observer's clock witness. Their errors stay in their own sidecar.
        let frame = active.cpu_frame.as_mut().unwrap();
        let (_, parent_start) = frame.open_stage.unwrap();
        let details = &mut frame.frame.substages;
        if at_ns < parent_start {
            details.invalidate("non_monotonic_substage");
            return;
        }
        if begin {
            details.begin(stage, at_ns);
        } else {
            details.end(stage, at_ns);
        }
        if stage == CpuSubstage::EncodeSubmit {
            if begin {
                frame.encode_details.begin_parent(at_ns);
            } else {
                frame.encode_details.end_parent(at_ns);
            }
        }
    }

    pub fn begin_encode_phase(&mut self, phase: EncodePhase) {
        self.encode_phase(phase, true);
    }
    pub fn end_encode_phase(&mut self, phase: EncodePhase) {
        self.encode_phase(phase, false);
    }
    fn encode_phase(&mut self, phase: EncodePhase, begin: bool) {
        let Some(active) = &mut self.active else {
            return;
        };
        let Some(frame) = &mut active.cpu_frame else {
            return;
        };
        if frame.open_stage.map(|(stage, _)| stage) != Some(CpuFrameStage::RendererSubmit) {
            frame.encode_details.invalidate("encode_renderer_parent_mismatch");
            return;
        }
        // Nested clocks are diagnostic-only: never advance the primary clock
        // witness or open another CpuSubstages span inside EncodeSubmit.
        let at_ns = self.clock.now_ns();
        if begin {
            frame.encode_details.begin(phase, at_ns);
        } else {
            frame.encode_details.end(phase, at_ns);
        }
    }

    /// True only after the first phase started in this capture's encode call.
    pub fn encode_details_active(&self) -> bool {
        self.active
            .as_ref()
            .and_then(|active| active.cpu_frame.as_ref())
            .is_some_and(|frame| frame.encode_details.is_active())
    }

    pub fn add_encode_counter(&mut self, counter: EncodeCounter, amount: u64) {
        if let Some(frame) = self
            .active
            .as_mut()
            .and_then(|active| active.cpu_frame.as_mut())
        {
            frame.encode_details.add_counter(counter, amount);
        }
    }

    /// Call only after the encode operation succeeds. A paired error-returning
    /// closure is still timed, but cannot become complete without this marker.
    pub fn complete_encode_details(&mut self) {
        if let Some(frame) = self
            .active
            .as_mut()
            .and_then(|active| active.cpu_frame.as_mut())
        {
            frame.encode_details.complete();
        }
    }

    pub fn begin_cpu_stage(&mut self, stage: CpuFrameStage) {
        let Some(active) = &mut self.active else {
            return;
        };
        let Some(frame) = &active.cpu_frame else {
            return;
        };
        // Misordered/overlapping hooks invalidate this attempt's diagnostics,
        // not the existing successful-present measurement or its anchor.
        if frame.open_stage.is_some() || frame.last_stage.is_some_and(|last| stage <= last) {
            active.cpu_frame = None;
            return;
        }
        let at_ns = self.clock.now_ns();
        if active.observe_clock(at_ns) {
            let frame = active.cpu_frame.as_mut().unwrap();
            frame.open_stage = Some((stage, at_ns));
            frame.last_stage = Some(stage);
        }
    }

    pub fn end_cpu_stage(&mut self, stage: CpuFrameStage) {
        let Some(active) = &mut self.active else {
            return;
        };
        let Some(frame) = &active.cpu_frame else {
            return;
        };
        let Some((opened_stage, started_at_ns)) = frame.open_stage else {
            return;
        };
        if stage != opened_stage {
            active.cpu_frame = None;
            return;
        }
        let at_ns = self.clock.now_ns();
        if active.observe_clock(at_ns) {
            let frame = active.cpu_frame.as_mut().unwrap();
            frame.frame.spans[stage.index()] = Some(CpuWallSpan {
                started_at_ns,
                ended_at_ns: at_ns,
            });
            frame.open_stage = None;
        }
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
        if !failed {
            active.retain_cpu_frame(at_ns);
        }
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
        if !failed {
            active.retain_cpu_frame(at_ns);
        }
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
        if active.observer.boundary(at_ns, reason).is_ok() {
            active.retain_cpu_frame(at_ns);
        }
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
        #[cfg(feature = "wgpu-runtime")]
        let gpu_report = active.gpu_capture.map(|session| {
            crate::frame_gpu_capture::finish_session(session, report.raw_records().len())
                .ok_or_else(|| "GPU timing capture lost its session state".to_owned())
        });
        let export = report.write_new(&active.output_path);
        #[cfg(feature = "wgpu-runtime")]
        {
            let gpu_notice = gpu_report.map(|result| {
                let path = active.output_path.with_extension("gpu-timing.json");
                let complete = result.as_ref().is_ok_and(|report| report.accounting_complete());
                let result = if export.is_ok() {
                    result.and_then(|report| report.write_new(&active.output_path))
                } else {
                    Err("Primary frame export failed; no GPU sidecar was written".to_owned())
                };
                match &result {
                    Ok(path) => eprintln!("GPU timing evidence saved to {} (accounting complete={complete}; GPU/display performance unclassified)", path.display()),
                    Err(error) => eprintln!("GPU timing export failed: {error}"),
                }
                GpuTimingExportNotice { output_path: path, accounting_complete: complete,
                    export_error: result.err() }
            });
            LAST_GPU_TIMING_NOTICE.with(|notice| *notice.borrow_mut() = gpu_notice);
        }
        // Diagnostic file I/O and hashing occur only after the final present
        // and successful primary write; no extra GPU wait or poll is added.
        let detail_notice = if export.is_ok() {
            match report.write_cpu_substages_new(&active.output_path) {
                Ok(Some(path)) => {
                    eprintln!("CPU substage evidence saved to {}", path.display());
                    Some(CpuSubstageExportNotice {
                        output_path: path,
                        error: None,
                    })
                }
                Ok(None) => None,
                Err(error) => {
                    eprintln!("CPU substage export failed: {error}");
                    Some(CpuSubstageExportNotice {
                        output_path: active.output_path.with_extension("cpu-substages.json"),
                        error: Some(error),
                    })
                }
            }
        } else {
            None
        };
        LAST_CPU_SUBSTAGE_NOTICE.with(|notice| *notice.borrow_mut() = detail_notice);
        let encode_notice = if export.is_ok() {
            match active.encode_capture.write_new(&active.output_path) {
                Ok(Some(path)) => {
                    eprintln!("CPU encode-detail evidence saved to {}", path.display());
                    Some(CpuEncodeDetailExportNotice {
                        output_path: path,
                        error: None,
                    })
                }
                Ok(None) => None,
                Err(error) => {
                    eprintln!("CPU encode-detail export failed: {error}");
                    Some(CpuEncodeDetailExportNotice {
                        output_path: active.output_path.with_extension("cpu-encode-detail.json"),
                        error: Some(error),
                    })
                }
            }
        } else {
            None
        };
        LAST_CPU_ENCODE_DETAIL_NOTICE.with(|notice| *notice.borrow_mut() = encode_notice);
        Some(SessionCompletion {
            report,
            output_path: active.output_path,
            export,
        })
    }
}

thread_local! {
    static LAST_CPU_ENCODE_DETAIL_NOTICE: RefCell<Option<CpuEncodeDetailExportNotice>> = const { RefCell::new(None) };
    static LAST_CPU_SUBSTAGE_NOTICE: RefCell<Option<CpuSubstageExportNotice>> = const { RefCell::new(None) };
    static LAST_COMPLETION_NOTICE: RefCell<Option<CompletionNotice>> = const { RefCell::new(None) };
    static SESSION: RefCell<PerformanceSession<InstantClock>> = const {
        RefCell::new(PerformanceSession::new(InstantClock::new()))
    };
}
#[cfg(feature = "wgpu-runtime")]
thread_local! {
    static LAST_GPU_TIMING_NOTICE: RefCell<Option<GpuTimingExportNotice>> = const { RefCell::new(None) };
}

#[cfg(feature = "wgpu-runtime")]
pub(crate) fn gpu_frame_key() -> Option<crate::render::gpu_timing::FrameKey> {
    SESSION.with(|session| session.borrow().gpu_frame_key())
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
pub fn begin_cpu_frame(physical_width: u32, physical_height: u32) {
    SESSION.with(|session| {
        session
            .borrow_mut()
            .begin_cpu_frame(physical_width, physical_height)
    });
}
pub fn begin_cpu_stage(stage: CpuFrameStage) {
    SESSION.with(|session| session.borrow_mut().begin_cpu_stage(stage));
}
pub fn end_cpu_stage(stage: CpuFrameStage) {
    SESSION.with(|session| session.borrow_mut().end_cpu_stage(stage));
}
/// Bracket a synchronous CPU call, including an error return. The session is
/// never borrowed across the call. Disabled sessions do not read the clock.
pub fn measure_cpu_stage<T>(stage: CpuFrameStage, call: impl FnOnce() -> T) -> T {
    begin_cpu_stage(stage);
    let result = call();
    end_cpu_stage(stage);
    result
}
/// Nested diagnostics do not open another disjoint parent stage. The existing
/// closure still runs exactly once, including its normal error return.
pub fn measure_cpu_substage<T>(stage: CpuSubstage, call: impl FnOnce() -> T) -> T {
    SESSION.with(|session| session.borrow_mut().begin_cpu_substage(stage));
    let result = call();
    SESSION.with(|session| session.borrow_mut().end_cpu_substage(stage));
    result
}
/// Capture-only nested timing. The closure executes once, outside the TLS
/// borrow, and keeps its return value/error unchanged. Disabled calls read no clock.
pub fn measure_encode_phase<T>(phase: EncodePhase, call: impl FnOnce() -> T) -> T {
    SESSION.with(|session| session.borrow_mut().begin_encode_phase(phase));
    let result = call();
    SESSION.with(|session| session.borrow_mut().end_encode_phase(phase));
    result
}
pub fn encode_details_active() -> bool {
    SESSION.with(|session| session.borrow().encode_details_active())
}
pub fn add_encode_counter(counter: EncodeCounter, amount: u64) {
    SESSION.with(|session| session.borrow_mut().add_encode_counter(counter, amount));
}
pub fn complete_encode_details() {
    SESSION.with(|session| session.borrow_mut().complete_encode_details());
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

#[cfg(all(test, feature = "wgpu-runtime"))]
mod gpu_lifecycle_tests {
    use super::*;
    use crate::frame_gpu_capture as gpu;
    use crate::frame_performance::{RuntimeIdentity, WindowMode};
    use serde_json::{json, Value};
    use std::sync::atomic::{AtomicU64, Ordering};

    struct Clock(u64);
    impl MonotonicClock for Clock {
        fn now_ns(&mut self) -> u64 {
            self.0 += 10;
            self.0
        }
    }
    struct Directory(PathBuf);
    impl Directory {
        fn new() -> Self {
            static ID: AtomicU64 = AtomicU64::new(0);
            let path = std::env::temp_dir().join(format!(
                "rust-duty-gpu-session-{}-{}",
                std::process::id(),
                ID.fetch_add(1, Ordering::Relaxed)
            ));
            std::fs::create_dir(&path).unwrap();
            Self(path)
        }
        fn path(&self, name: &str) -> PathBuf {
            self.0.join(name)
        }
    }
    impl Drop for Directory {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }
    fn identity() -> RunIdentity {
        RunIdentity {
            runtime: RuntimeIdentity {
                actual_backend: Some("synthetic CPU lifecycle fixture".into()),
                actual_adapter: json!({"gpu_timestamps_requested":true,
                    "gpu_timestamp_features_enabled":false}),
                build: Value::Null,
                scene: Value::Null,
                initial_window: WindowContext {
                    physical_width: 960,
                    physical_height: 540,
                    scale_factor: 1.0,
                    mode: WindowMode::Windowed,
                },
            },
            operator_supplied: Value::Null,
        }
    }
    fn start(path: PathBuf, max_records: usize, diagnostics: bool) -> PerformanceSession<Clock> {
        let mut session = PerformanceSession::new(Clock(0));
        session
            .start(
                identity(),
                path,
                CaptureLimits {
                    max_records,
                    ..CaptureLimits::default()
                },
            )
            .unwrap();
        if diagnostics {
            session.active.as_mut().unwrap().gpu_capture =
                Some(gpu::start_synthetic_session(max_records));
        }
        session
    }
    fn read(path: &std::path::Path) -> Value {
        serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap()
    }
    fn normal_stop(session: &mut PerformanceSession<Clock>) -> SessionCompletion {
        session.begin_cpu_frame(960, 540);
        assert!(session.present_success().is_none());
        session.begin_cpu_frame(960, 540);
        session.request_stop();
        session.present_success().unwrap()
    }
    #[test]
    fn gpu_joining_keeps_primary_bytes_and_final_present_unchanged() {
        let directory = Directory::new();
        let plain = directory.path("plain.json");
        let diagnostic = directory.path("diagnostic.json");
        let a = normal_stop(&mut start(plain.clone(), 8, false));
        assert_eq!(a.report.status, CaptureStatus::Complete);
        assert!(!plain.with_extension("gpu-timing.json").exists());
        let b = normal_stop(&mut start(diagnostic.clone(), 8, true));
        assert_eq!(b.report.status, CaptureStatus::Complete);
        assert_eq!(
            std::fs::read(&plain).unwrap(),
            std::fs::read(&diagnostic).unwrap()
        );
        let sidecar = read(&diagnostic.with_extension("gpu-timing.json"));
        assert_eq!(
            sidecar["frame_report_sha256"],
            rust_duty_launcher::file_hash(&diagnostic).unwrap()
        );
        assert_eq!(sidecar["accounting_state"], "complete");
        assert_eq!(sidecar["samples"][0]["record_index"], 0);
        assert_eq!(sidecar["samples"][1]["record_index"], 1);
        assert_eq!(sidecar["samples"][1]["status"], "not_submitted");
        assert!(!gpu::synthetic_session_is_active());
    }
    #[test]
    fn skipped_attempt_has_its_own_join_and_no_fabricated_duration() {
        let directory = Directory::new();
        let path = directory.path("frames.json");
        let mut session = start(path.clone(), 8, true);
        session.begin_cpu_frame(960, 540);
        assert!(session.present_skipped().is_none());
        assert_eq!(
            normal_stop(&mut session).report.status,
            CaptureStatus::Complete
        );
        let sidecar = read(&path.with_extension("gpu-timing.json"));
        assert_eq!(sidecar["samples"].as_array().unwrap().len(), 3);
        for (index, sample) in sidecar["samples"].as_array().unwrap().iter().enumerate() {
            assert_eq!(sample["attempt"], index);
            assert_eq!(sample["record_index"], index);
            assert!(sample["elapsed_ns"].is_null());
        }
    }
    #[test]
    fn shutdown_and_present_failure_close_open_attempts_before_export() {
        let directory = Directory::new();
        for shutdown in [false, true] {
            let path = directory.path(if shutdown {
                "shutdown.json"
            } else {
                "failure.json"
            });
            let mut session = start(path.clone(), 8, true);
            session.begin_cpu_frame(960, 540);
            let result = if shutdown {
                session.shutdown()
            } else {
                session.present_failure()
            }
            .unwrap();
            assert!(matches!(result.report.status, CaptureStatus::Incomplete(_)));
            assert!(result.export.is_ok());
            let sidecar = read(&path.with_extension("gpu-timing.json"));
            assert_eq!(sidecar["accounting_state"], "complete");
            assert_eq!(sidecar["samples"][0]["record_index"], 0);
            assert!(!gpu::synthetic_session_is_active());
        }
    }
    #[test]
    fn boundary_record_limit_retains_unjoined_attempt_as_incomplete() {
        let directory = Directory::new();
        let path = directory.path("limit.json");
        let mut session = start(path.clone(), 2, true);
        session.begin_cpu_frame(960, 540);
        assert!(session.present_success().is_none());
        assert!(session.boundary(BoundaryReason::Resize).is_none());
        session.begin_cpu_frame(960, 540);
        let result = session.boundary(BoundaryReason::Resize).unwrap();
        assert!(matches!(result.report.status, CaptureStatus::Incomplete(_)));
        let sidecar = read(&path.with_extension("gpu-timing.json"));
        assert_eq!(sidecar["accounting_state"], "incomplete");
        assert_eq!(sidecar["samples"][0]["record_index"], 0);
        assert!(sidecar["samples"][1]["record_index"].is_null());
        assert!(!gpu::synthetic_session_is_active());
    }
    #[test]
    fn backward_clock_boundary_keeps_open_attempt_unjoined() {
        let directory = Directory::new();
        let path = directory.path("clock.json");
        let mut session = start(path.clone(), 8, true);
        session.begin_cpu_frame(960, 540);
        session.clock.0 = 0;
        let result = session.boundary(BoundaryReason::Resize).unwrap();
        assert!(matches!(result.report.status, CaptureStatus::Incomplete(_)));
        let sidecar = read(&path.with_extension("gpu-timing.json"));
        assert_eq!(sidecar["accounting_state"], "incomplete");
        assert!(sidecar["samples"][0]["record_index"].is_null());
        assert!(!gpu::synthetic_session_is_active());
    }
    #[test]
    fn export_failures_retire_session_without_overwriting_existing_evidence() {
        let directory = Directory::new();
        for fail_primary in [true, false] {
            let path = directory.path(if fail_primary {
                "primary.json"
            } else {
                "sidecar.json"
            });
            let protected = if fail_primary {
                path.clone()
            } else {
                path.with_extension("gpu-timing.json")
            };
            std::fs::write(&protected, b"existing evidence").unwrap();
            let result = normal_stop(&mut start(path.clone(), 8, true));
            assert_eq!(result.export.is_err(), fail_primary);
            assert_eq!(std::fs::read(&protected).unwrap(), b"existing evidence");
            let notice = take_gpu_timing_export_notice().unwrap();
            assert!(notice.export_error.is_some());
            assert!(!gpu::synthetic_session_is_active());
            if fail_primary {
                assert!(!path.with_extension("gpu-timing.json").exists());
            }
        }
    }
}

#[cfg(test)]
mod encode_detail_lifecycle_tests {
    use super::*;
    use crate::frame_performance::{RuntimeIdentity, WindowMode};
    use serde_json::{json, Value};
    use std::sync::atomic::{AtomicU64, Ordering};

    struct Clock {
        now: u64,
        reads: usize,
    }
    impl MonotonicClock for Clock {
        fn now_ns(&mut self) -> u64 {
            self.reads += 1;
            self.now
        }
    }
    struct Directory(PathBuf);
    impl Directory {
        fn new() -> Self {
            static ID: AtomicU64 = AtomicU64::new(0);
            let path = std::env::temp_dir().join(format!(
                "rust-duty-encode-session-{}-{}",
                std::process::id(),
                ID.fetch_add(1, Ordering::Relaxed)
            ));
            std::fs::create_dir(&path).unwrap();
            Self(path)
        }
        fn path(&self, name: &str) -> PathBuf {
            self.0.join(name)
        }
    }
    impl Drop for Directory {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }
    fn start(path: PathBuf, max_records: usize) -> PerformanceSession<Clock> {
        let mut session = PerformanceSession::new(Clock { now: 10, reads: 0 });
        session
            .start(
                RunIdentity {
                    runtime: RuntimeIdentity {
                        actual_backend: Some("synthetic encode lifecycle fixture".into()),
                        actual_adapter: json!({"instance_descriptor": {
                            "schema":"rust-duty-wgpu-instance-descriptor/v1",
                            "wgpu_version":"30.0.1", "flags_bits":0,
                            "debug":false, "validation":false,
                            "gpu_based_validation":false, "validation_indirect_call":false,
                            "application_debug_assertions":false,
                            "environment_overrides_applied":false
                        }}),
                        build: Value::Null,
                        scene: Value::Null,
                        initial_window: WindowContext {
                            physical_width: 960,
                            physical_height: 540,
                            scale_factor: 1.0,
                            mode: WindowMode::Windowed,
                        },
                    },
                    operator_supplied: Value::Null,
                },
                path,
                CaptureLimits {
                    max_records,
                    ..CaptureLimits::default()
                },
            )
            .unwrap();
        session
    }
    fn read(path: &std::path::Path) -> Value {
        serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap()
    }
    fn encode_frame(session: &mut PerformanceSession<Clock>, base: u64, observe: bool) {
        session.clock.now = base;
        session.begin_cpu_frame(960, 540);
        assert!(!session.encode_details_active());
        session.add_encode_counter(EncodeCounter::DrawCalls, 99);
        session.clock.now = base + 10;
        session.begin_cpu_stage(CpuFrameStage::RendererSubmit);
        session.clock.now = base + 20;
        session.begin_cpu_substage(CpuSubstage::EncodeSubmit);
        assert!(!session.encode_details_active());
        if observe {
            for (index, phase) in EncodePhase::ALL.into_iter().enumerate() {
                session.clock.now = base + 21 + index as u64 * 2;
                session.begin_encode_phase(phase);
                assert!(session.encode_details_active());
                session.add_encode_counter(EncodeCounter::DrawCalls, 1);
                session.clock.now += 1;
                session.end_encode_phase(phase);
            }
            session.complete_encode_details();
            assert!(!session.encode_details_active());
        }
        session.clock.now = base + 40;
        session.end_cpu_substage(CpuSubstage::EncodeSubmit);
        session.clock.now = base + 50;
        session.end_cpu_stage(CpuFrameStage::RendererSubmit);
        session.clock.now = base + 60;
    }
    fn normal_stop(session: &mut PerformanceSession<Clock>, observe: bool) -> SessionCompletion {
        encode_frame(session, 20, observe);
        assert!(session.present_success().is_none());
        encode_frame(session, 90, observe);
        session.request_stop();
        session.clock.now += 10;
        session.present_success().unwrap()
    }

    #[test]
    fn encode_sidecar_joins_exact_primary_and_leaves_old_outputs_unchanged() {
        let directory = Directory::new();
        let plain = directory.path("plain.json");
        let observed = directory.path("observed.json");
        assert_eq!(
            normal_stop(&mut start(plain.clone(), 8), false).report.status,
            CaptureStatus::Complete
        );
        assert_eq!(
            normal_stop(&mut start(observed.clone(), 8), true).report.status,
            CaptureStatus::Complete
        );
        assert_eq!(
            std::fs::read(&plain).unwrap(),
            std::fs::read(&observed).unwrap()
        );
        assert_eq!(
            read(&plain.with_extension("cpu-substages.json")),
            read(&observed.with_extension("cpu-substages.json"))
        );
        let primary = read(&observed);
        let sidecar = read(&observed.with_extension("cpu-encode-detail.json"));
        assert_eq!(sidecar["schema"], crate::frame_encode_detail::SCHEMA);
        assert_eq!(sidecar["measurement"], crate::frame_encode_detail::MEASUREMENT);
        assert_eq!(sidecar["frame_status"], primary["status"]);
        assert_eq!(
            sidecar["frame_report_sha256"],
            rust_duty_launcher::file_hash(&observed).unwrap()
        );
        for (index, sample) in sidecar["samples"].as_array().unwrap().iter().enumerate() {
            assert_eq!(sample["record_index"], index);
            assert_eq!(sample["details"]["state"], "complete");
            assert_eq!(sample["details"]["spans"].as_array().unwrap().len(), 5);
            assert_eq!(sample["details"]["counters"]["draw_calls"], 5);
        }
        let absent = read(&plain.with_extension("cpu-encode-detail.json"));
        assert_eq!(
            absent["samples"][0]["details"]["error"],
            "encode_not_observed"
        );
        assert_eq!(
            absent["samples"][0]["details"]["counters"]["draw_calls"],
            0
        );
    }

    #[test]
    fn skipped_unvisited_attempts_join_across_intervening_boundaries() {
        let directory = Directory::new();
        let path = directory.path("frames.json");
        let mut session = start(path.clone(), 8);
        session.clock.now = 11;
        session.begin_cpu_frame(960, 540);
        session.clock.now = 12;
        assert!(session.present_skipped().is_none());
        session.clock.now = 13;
        assert!(session.boundary(BoundaryReason::Resize).is_none());
        normal_stop(&mut session, true);
        let sidecar = read(&path.with_extension("cpu-encode-detail.json"));
        let samples = sidecar["samples"].as_array().unwrap();
        assert_eq!(samples.len(), 3);
        assert_eq!(samples[0]["record_index"], 0);
        assert_eq!(samples[1]["record_index"], 2);
        assert_eq!(samples[2]["record_index"], 3);
        assert_eq!(samples[0]["details"]["state"], "incomplete");
        assert!(samples[0]["details"]["spans"].as_array().unwrap().is_empty());
    }

    #[test]
    fn shutdown_and_failure_keep_observed_partial_counters_and_phase_prefix() {
        let directory = Directory::new();
        for shutdown in [false, true] {
            let path = directory.path(if shutdown {
                "shutdown.json"
            } else {
                "failure.json"
            });
            let mut session = start(path.clone(), 8);
            session.clock.now = 20;
            session.begin_cpu_frame(960, 540);
            session.clock.now = 30;
            session.begin_cpu_stage(CpuFrameStage::RendererSubmit);
            session.clock.now = 40;
            session.begin_cpu_substage(CpuSubstage::EncodeSubmit);
            session.clock.now = 41;
            session.begin_encode_phase(EncodePhase::FramePlan);
            session.add_encode_counter(EncodeCounter::PreparedDraws, 7);
            session.clock.now = 42;
            session.end_encode_phase(EncodePhase::FramePlan);
            session.clock.now = 43;
            session.begin_encode_phase(EncodePhase::GeometryUpload);
            session.clock.now = 50;
            let result = if shutdown {
                session.shutdown()
            } else {
                session.present_failure()
            }
            .unwrap();
            assert!(matches!(result.report.status, CaptureStatus::Incomplete(_)));
            let sidecar = read(&path.with_extension("cpu-encode-detail.json"));
            assert_eq!(sidecar["frame_status"], read(&path)["status"]);
            let details = &sidecar["samples"][0]["details"];
            assert_eq!(details["state"], "incomplete");
            assert_eq!(details["spans"].as_array().unwrap().len(), 1);
            assert_eq!(details["counters"]["prepared_draws"], 7);
        }
    }

    #[test]
    fn disabled_hooks_and_counters_never_read_clock_or_create_capture() {
        let mut session = PerformanceSession::new(Clock { now: 0, reads: 0 });
        for phase in EncodePhase::ALL {
            session.begin_encode_phase(phase);
            session.end_encode_phase(phase);
        }
        session.add_encode_counter(EncodeCounter::TextCharacters, 9);
        session.complete_encode_details();
        assert!(!session.encode_details_active());
        assert_eq!(session.clock.reads, 0);
        assert!(session.active.is_none());
        let calls = std::cell::Cell::new(0);
        let result = measure_encode_phase(EncodePhase::FramePlan, || {
            calls.set(calls.get() + 1);
            Err::<(), _>("original error")
        });
        assert_eq!(result, Err("original error"));
        assert_eq!(calls.get(), 1);
    }

    #[test]
    fn captures_without_cpu_attempts_do_not_write_encode_sidecars() {
        let directory = Directory::new();
        let path = directory.path("frames.json");
        let mut session = start(path.clone(), 8);
        session.clock.now = 20;
        assert!(session.present_success().is_none());
        session.clock.now = 30;
        session.request_stop();
        assert!(session.present_success().unwrap().export.is_ok());
        assert!(!path.with_extension("cpu-encode-detail.json").exists());
    }

    #[test]
    fn record_limit_keeps_only_rows_joined_to_retained_cpu_records() {
        let directory = Directory::new();
        let path = directory.path("frames.json");
        let mut session = start(path.clone(), 2);
        encode_frame(&mut session, 20, true);
        assert!(session.present_success().is_none());
        session.clock.now += 1;
        assert!(session.boundary(BoundaryReason::Resize).is_none());
        encode_frame(&mut session, 90, true);
        let result = session.present_success().unwrap();
        assert!(matches!(result.report.status, CaptureStatus::Incomplete(_)));
        let sidecar = read(&path.with_extension("cpu-encode-detail.json"));
        assert_eq!(sidecar["samples"].as_array().unwrap().len(), 1);
        assert_eq!(sidecar["samples"][0]["record_index"], 0);
    }

    #[test]
    fn full_record_buffer_without_retained_cpu_rows_has_no_encode_sidecar() {
        let directory = Directory::new();
        let path = directory.path("frames.json");
        let mut session = start(path.clone(), 1);
        session.clock.now = 20;
        assert!(session.boundary(BoundaryReason::Resize).is_none());
        encode_frame(&mut session, 30, true);
        let completion = session.present_success().unwrap();
        assert!(matches!(completion.report.status, CaptureStatus::Incomplete(_)));
        assert!(completion.export.is_ok());
        let primary = read(&path);
        assert_eq!(primary["records"].as_array().unwrap().len(), 1);
        assert!(primary.get("cpu_frame_stages").is_none());
        assert!(!path.with_extension("cpu-substages.json").exists());
        assert!(!path.with_extension("cpu-encode-detail.json").exists());
        assert!(take_cpu_encode_detail_export_notice().is_none());
    }

    #[test]
    fn sidecar_and_primary_write_failures_preserve_existing_files() {
        let directory = Directory::new();
        for primary_failure in [false, true] {
            let path = directory.path(if primary_failure {
                "primary.json"
            } else {
                "sidecar.json"
            });
            let protected = if primary_failure {
                path.clone()
            } else {
                path.with_extension("cpu-encode-detail.json")
            };
            std::fs::write(&protected, b"existing evidence").unwrap();
            let completion = normal_stop(&mut start(path.clone(), 8), true);
            assert_eq!(completion.export.is_err(), primary_failure);
            assert_eq!(std::fs::read(&protected).unwrap(), b"existing evidence");
            let notice = take_cpu_encode_detail_export_notice();
            if primary_failure {
                assert!(notice.is_none());
                assert!(!path.with_extension("cpu-encode-detail.json").exists());
            } else {
                assert!(notice.unwrap().error.is_some());
                assert_eq!(completion.report.status, CaptureStatus::Complete);
            }
        }
    }

    #[test]
    fn earlier_substage_error_cannot_fabricate_a_complete_encode_parent() {
        let directory = Directory::new();
        let path = directory.path("frames.json");
        let mut session = start(path.clone(), 8);
        session.clock.now = 20;
        session.begin_cpu_frame(960, 540);
        session.clock.now = 21;
        session.begin_cpu_stage(CpuFrameStage::SurfaceAcquire);
        session.clock.now = 22;
        session.begin_cpu_substage(CpuSubstage::AcquireTexture);
        session.clock.now = 23;
        session.end_cpu_substage(CpuSubstage::AcquireValidation);
        session.clock.now = 24;
        session.end_cpu_stage(CpuFrameStage::SurfaceAcquire);
        session.clock.now = 30;
        session.begin_cpu_stage(CpuFrameStage::RendererSubmit);
        session.clock.now = 40;
        session.begin_cpu_substage(CpuSubstage::EncodeSubmit);
        for (index, phase) in EncodePhase::ALL.into_iter().enumerate() {
            session.clock.now = 41 + index as u64 * 2;
            session.begin_encode_phase(phase);
            session.add_encode_counter(EncodeCounter::DrawCalls, 1);
            session.clock.now += 1;
            session.end_encode_phase(phase);
        }
        session.complete_encode_details();
        session.clock.now = 60;
        session.end_cpu_substage(CpuSubstage::EncodeSubmit);
        session.clock.now = 70;
        session.end_cpu_stage(CpuFrameStage::RendererSubmit);
        session.clock.now = 80;
        assert!(session.present_success().is_none());
        encode_frame(&mut session, 90, true);
        session.request_stop();
        session.clock.now = 160;
        assert_eq!(
            session.present_success().unwrap().report.status,
            CaptureStatus::Complete
        );
        let parent = read(&path.with_extension("cpu-substages.json"));
        assert_eq!(parent["samples"][0]["details"]["state"], "incomplete");
        assert!(parent["samples"][0]["details"]["spans"]
            .as_array()
            .unwrap()
            .is_empty());
        let sidecar = read(&path.with_extension("cpu-encode-detail.json"));
        let details = &sidecar["samples"][0]["details"];
        assert_eq!(details["state"], "incomplete");
        assert_eq!(details["error"], "encode_ancestor_incomplete");
        assert_eq!(details["spans"].as_array().unwrap().len(), 5);
        assert_eq!(details["counters"]["draw_calls"], 5);
        // Missing encode parent is reader-valid only for an incomplete row.
        // Every retained child still lies inside the available renderer/frame.
        for span in details["spans"].as_array().unwrap() {
            assert!(span["started_at_ns"].as_u64().unwrap() >= 30);
            assert!(span["ended_at_ns"].as_u64().unwrap() <= 70);
        }
        assert_eq!(sidecar["samples"][1]["details"]["state"], "complete");
    }

    #[test]
    fn diagnostic_clock_error_does_not_invalidate_primary_capture() {
        let directory = Directory::new();
        let path = directory.path("frames.json");
        let mut session = start(path.clone(), 8);
        encode_frame(&mut session, 20, true);
        assert!(session.present_success().is_none());
        session.clock.now = 90;
        session.begin_cpu_frame(960, 540);
        session.clock.now = 100;
        session.begin_cpu_stage(CpuFrameStage::RendererSubmit);
        session.clock.now = 110;
        session.begin_cpu_substage(CpuSubstage::EncodeSubmit);
        session.clock.now = 111;
        session.begin_encode_phase(EncodePhase::FramePlan);
        session.clock.now = 109;
        session.end_encode_phase(EncodePhase::FramePlan);
        assert!(session.encode_details_active());
        session.add_encode_counter(EncodeCounter::PreparedDraws, 7);
        session.clock.now = 120;
        session.end_cpu_substage(CpuSubstage::EncodeSubmit);
        session.clock.now = 130;
        session.end_cpu_stage(CpuFrameStage::RendererSubmit);
        session.clock.now = 140;
        session.request_stop();
        assert_eq!(
            session.present_success().unwrap().report.status,
            CaptureStatus::Complete
        );
        let sidecar = read(&path.with_extension("cpu-encode-detail.json"));
        assert_eq!(sidecar["samples"][1]["details"]["state"], "incomplete");
        assert_eq!(
            sidecar["samples"][1]["details"]["counters"]["prepared_draws"],
            7
        );
        assert_eq!(
            sidecar["frame_status"],
            json!({"state":"complete","error":null})
        );
    }
}
