//! Bounded, opt-in CPU wall-clock present-return interval evidence.
//!
//! The caller supplies nanoseconds from one monotonic clock and calls this only
//! after a *successful* present returns. These are neither GPU execution times,
//! display/scan-out cadence, nor simulation deltas. A long eligible interval is
//! retained unchanged. Only explicitly recorded exclusions break the chain.
//!
//! This observer makes no hardware or performance-pass determination. Runtime
//! identity must come from the actual runtime; operator claims have a separate
//! namespace. Window changes are retained as timestamped segment boundaries.
use serde_json::{json, Value};
use std::fmt;
use std::fs::OpenOptions;
use std::io::{self, BufWriter, Write};
use std::path::Path;

const MAX_RECORDS: usize = 250_000;
const MAX_METADATA_BYTES: usize = 256 * 1024;
pub const MEASUREMENT: &str = "cpu_wall_clock_successful_present_return_interval_ns";
pub const CPU_STAGE_MEASUREMENT: &str = "cpu_wall_clock_paired_frame_stage_ns";
pub const CPU_STAGE_INTERPRETATION: &str = "Disjoint paired CPU wall-clock spans within one frame attempt, not GPU execution times. Missing spans are unavailable, not zero. Stages do not cover the whole present-return interval; no residual GPU time is inferred. Successful present-return intervals remain the primary end-to-end measurement.";

/// Ordered, non-overlapping CPU spans. Renderer submission includes encoding,
/// queue submission, validation and any requested diagnostic readback, but ends
/// before the present call. No GPU completion fence is added by these hooks.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum CpuFrameStage {
    SurfaceAcquire,
    GameRecording,
    RendererSubmit,
    PresentCall,
}
impl CpuFrameStage {
    pub const ALL: [Self; 4] = [
        Self::SurfaceAcquire,
        Self::GameRecording,
        Self::RendererSubmit,
        Self::PresentCall,
    ];
    pub fn label(self) -> &'static str {
        match self {
            Self::SurfaceAcquire => "surface_acquire",
            Self::GameRecording => "game_recording",
            Self::RendererSubmit => "renderer_submit",
            Self::PresentCall => "present_call",
        }
    }
    pub(crate) fn index(self) -> usize {
        self as usize
    }
}

#[derive(Clone, Copy, Debug)]
pub(crate) struct CpuWallSpan {
    pub started_at_ns: u64,
    pub ended_at_ns: u64,
}

#[derive(Clone, Debug)]
pub(crate) struct CpuFrameStages {
    pub started_at_ns: u64,
    pub physical_width: u32,
    pub physical_height: u32,
    pub spans: [Option<CpuWallSpan>; 4],
}
#[derive(Debug)]
struct CpuFrameSample {
    record_index: usize,
    finished_at_ns: u64,
    frame: CpuFrameStages,
}
impl CpuFrameSample {
    fn to_json(&self) -> Value {
        let spans: serde_json::Map<String, Value> = CpuFrameStage::ALL
            .into_iter()
            .map(|stage| {
                let span = self.frame.spans[stage.index()].map(|span| {
                    json!({"started_at_ns":span.started_at_ns,"ended_at_ns":span.ended_at_ns,
                        "duration_ns":span.ended_at_ns - span.started_at_ns})
                });
                (stage.label().into(), span.unwrap_or(Value::Null))
            })
            .collect();
        json!({"record_index":self.record_index,"started_at_ns":self.frame.started_at_ns,
            "finished_at_ns":self.finished_at_ns,"physical_width":self.frame.physical_width,
            "physical_height":self.frame.physical_height,"spans":spans})
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct CaptureLimits {
    pub max_records: usize,
    pub max_metadata_bytes: usize,
}
impl Default for CaptureLimits {
    fn default() -> Self {
        Self {
            max_records: 120_000,
            max_metadata_bytes: 64 * 1024,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum WindowMode {
    Unknown,
    Windowed,
    Borderless,
    ExclusiveFullscreen,
}
impl WindowMode {
    fn label(self) -> &'static str {
        match self {
            Self::Unknown => "unknown",
            Self::Windowed => "windowed",
            Self::Borderless => "borderless",
            Self::ExclusiveFullscreen => "exclusive_fullscreen",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct WindowContext {
    pub physical_width: u32,
    pub physical_height: u32,
    pub scale_factor: f64,
    pub mode: WindowMode,
}
impl WindowContext {
    fn valid(self) -> bool {
        self.scale_factor.is_finite() && self.scale_factor > 0.0
    }
    fn to_json(self) -> Value {
        json!({"physical_width":self.physical_width,"physical_height":self.physical_height,
            "scale_factor":self.scale_factor,"mode":self.mode.label()})
    }
}

/// Values here must describe observed runtime state, never a requested backend
/// or an operator's guess. Use JSON null for unavailable adapter/build/scene data.
#[derive(Clone, Debug, PartialEq)]
pub struct RuntimeIdentity {
    pub actual_backend: Option<String>,
    pub actual_adapter: Value,
    pub build: Value,
    pub initial_window: WindowContext,
    pub scene: Value,
}
#[derive(Clone, Debug, PartialEq)]
pub struct RunIdentity {
    pub runtime: RuntimeIdentity,
    pub operator_supplied: Value,
}
impl RunIdentity {
    // Validate the size without cloning arbitrary caller-supplied JSON first.
    fn write_json(&self, writer: &mut impl Write) -> io::Result<()> {
        writer.write_all(br#"{"runtime_observed":{"actual_backend":"#)?;
        serde_json::to_writer(&mut *writer, &self.runtime.actual_backend)
            .map_err(io::Error::other)?;
        writer.write_all(br#", "actual_adapter":"#)?;
        serde_json::to_writer(&mut *writer, &self.runtime.actual_adapter)
            .map_err(io::Error::other)?;
        writer.write_all(br#", "build":"#)?;
        serde_json::to_writer(&mut *writer, &self.runtime.build).map_err(io::Error::other)?;
        writer.write_all(br#", "initial_window":"#)?;
        serde_json::to_writer(&mut *writer, &self.runtime.initial_window.to_json())
            .map_err(io::Error::other)?;
        writer.write_all(br#", "scene":"#)?;
        serde_json::to_writer(&mut *writer, &self.runtime.scene).map_err(io::Error::other)?;
        writer.write_all(br#"}, "operator_supplied":"#)?;
        serde_json::to_writer(&mut *writer, &self.operator_supplied).map_err(io::Error::other)?;
        writer.write_all(br#", "hardware_classification":"unknown", "hardware_classification_basis":"This observer does not authenticate hardware evidence."}"#)
    }
    fn to_json(&self) -> Value {
        json!({
            "runtime_observed": {
                "actual_backend": self.runtime.actual_backend,
                "actual_adapter": self.runtime.actual_adapter,
                "build": self.runtime.build,
                "initial_window": self.runtime.initial_window.to_json(),
                "scene": self.runtime.scene,
            },
            "operator_supplied": self.operator_supplied,
            "hardware_classification": "unknown",
            "hardware_classification_basis": "This observer does not authenticate hardware evidence."
        })
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BoundaryReason {
    FocusLost,
    FocusRegained,
    Paused,
    Resumed,
    Resize,
    Minimized,
    SurfaceSkipped,
    SurfaceError,
    CaptureReadback,
    DiagnosticCapture,
    RendererChanged,
    SceneChanged,
    CallerExcluded,
    Shutdown,
}
impl BoundaryReason {
    pub fn label(self) -> &'static str {
        match self {
            Self::FocusLost => "focus_lost",
            Self::FocusRegained => "focus_regained",
            Self::Paused => "paused",
            Self::Resumed => "resumed",
            Self::Resize => "resize",
            Self::Minimized => "minimized",
            Self::SurfaceSkipped => "surface_skipped",
            Self::SurfaceError => "surface_error",
            Self::CaptureReadback => "capture_readback",
            Self::DiagnosticCapture => "diagnostic_capture",
            Self::RendererChanged => "renderer_changed",
            Self::SceneChanged => "scene_changed",
            Self::CallerExcluded => "caller_excluded",
            Self::Shutdown => "shutdown",
        }
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Eligibility {
    Eligible,
    Ineligible(BoundaryReason),
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum RecordKind {
    PresentReturn {
        eligibility: Eligibility,
        interval_ns: Option<u64>,
    },
    Boundary {
        reason: BoundaryReason,
    },
    SkippedFrame {
        reason: BoundaryReason,
    },
    WindowContext {
        context: WindowContext,
    },
}
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct RawRecord {
    pub at_ns: u64,
    pub kind: RecordKind,
}
impl RawRecord {
    fn to_json(self) -> Value {
        match self.kind {
            RecordKind::PresentReturn {
                eligibility,
                interval_ns,
            } => {
                let reason = match eligibility {
                    Eligibility::Eligible => None,
                    Eligibility::Ineligible(reason) => Some(reason.label()),
                };
                json!({"at_ns":self.at_ns,"kind":"successful_present_return",
                    "eligible":eligibility == Eligibility::Eligible,"ineligible_reason":reason,"interval_ns":interval_ns})
            }
            RecordKind::Boundary { reason } => {
                json!({"at_ns":self.at_ns,"kind":"boundary","reason":reason.label()})
            }
            RecordKind::SkippedFrame { reason } => {
                json!({"at_ns":self.at_ns,"kind":"skipped_frame","reason":reason.label(),"resets_interval_anchor":false})
            }
            RecordKind::WindowContext { context } => {
                json!({"at_ns":self.at_ns,"kind":"window_context","context":context.to_json()})
            }
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CaptureError {
    InvalidLimits,
    InvalidWindowContext,
    MetadataLimitExceeded,
    RecordLimitExceeded { max_records: usize },
    AllocationFailed,
    NonMonotonicTimestamp { previous_ns: u64, received_ns: u64 },
    NoEligibleIntervals,
    PresentFailed,
    FinalPresentMissing,
}
impl fmt::Display for CaptureError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidLimits => write!(f, "capture limits must be nonzero and at most {MAX_RECORDS} records / {MAX_METADATA_BYTES} metadata bytes"),
            Self::InvalidWindowContext => f.write_str("window scale factor must be finite and positive"),
            Self::MetadataLimitExceeded => f.write_str("run identity exceeds the metadata byte limit"),
            Self::RecordLimitExceeded { max_records } => write!(f, "capture reached its {max_records}-record limit; later events were not retained"),
            Self::AllocationFailed => f.write_str("could not reserve the bounded capture buffer"),
            Self::NonMonotonicTimestamp { previous_ns, received_ns } => write!(f, "non-monotonic timestamp: {received_ns} ns follows {previous_ns} ns"),
            Self::NoEligibleIntervals => f.write_str("capture has no eligible present-return intervals"),
            Self::PresentFailed => f.write_str("final requested presentation failed"),
            Self::FinalPresentMissing => f.write_str("capture ended before its final requested presentation returned"),
        }
    }
}
impl std::error::Error for CaptureError {}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CaptureStatus {
    Complete,
    Incomplete(CaptureError),
}
impl CaptureStatus {
    pub fn is_complete(self) -> bool {
        self == Self::Complete
    }
    fn to_json(self) -> Value {
        match self {
            Self::Complete => json!({"state":"complete","error":null}),
            Self::Incomplete(error) => json!({"state":"incomplete","error":error.to_string()}),
        }
    }
}

/// Exactly the retained eligible intervals; missing values mean no such samples.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct IntervalSummary {
    pub interval_count: usize,
    pub total_interval_ns: u64,
    pub min_ns: Option<u64>,
    pub max_ns: Option<u64>,
    pub p50_ns: Option<u64>,
    pub p95_ns: Option<u64>,
    pub p99_ns: Option<u64>,
}
impl IntervalSummary {
    fn from_records(records: &[RawRecord]) -> Self {
        let mut values: Vec<_> = records
            .iter()
            .filter_map(|record| match record.kind {
                RecordKind::PresentReturn { interval_ns, .. } => interval_ns,
                _ => None,
            })
            .collect();
        // Intervals are ordered and non-overlapping within one u64 clock span,
        // so their sum cannot overflow u64, even with multiple excluded segments.
        let total_interval_ns = values.iter().sum();
        values.sort_unstable();
        let nearest_rank = |percentile: usize| {
            if values.is_empty() {
                None
            } else {
                Some(values[(values.len() * percentile).div_ceil(100) - 1])
            }
        };
        Self {
            interval_count: values.len(),
            total_interval_ns,
            min_ns: values.first().copied(),
            max_ns: values.last().copied(),
            p50_ns: nearest_rank(50),
            p95_ns: nearest_rank(95),
            p99_ns: nearest_rank(99),
        }
    }
    fn to_json(&self) -> Value {
        json!({"interval_count":self.interval_count,"total_interval_ns":self.total_interval_ns,
            "min_ns":self.min_ns,"max_ns":self.max_ns,"p50_ns":self.p50_ns,"p95_ns":self.p95_ns,"p99_ns":self.p99_ns,
            "percentile_method":"nearest_rank_ceil_p_times_n_no_interpolation"})
    }
}

pub struct FramePerformanceObserver {
    identity: RunIdentity,
    limits: CaptureLimits,
    start_ns: u64,
    last_observed_ns: u64,
    previous_eligible_present_ns: Option<u64>,
    records: Vec<RawRecord>,
    failure: Option<(u64, CaptureError)>,
    cpu_frame_stages: Vec<CpuFrameSample>,
}
impl FramePerformanceObserver {
    pub fn start(
        identity: RunIdentity,
        start_ns: u64,
        limits: CaptureLimits,
    ) -> Result<Self, CaptureError> {
        if limits.max_records == 0
            || limits.max_records > MAX_RECORDS
            || limits.max_metadata_bytes == 0
            || limits.max_metadata_bytes > MAX_METADATA_BYTES
        {
            return Err(CaptureError::InvalidLimits);
        }
        if !identity.runtime.initial_window.valid() {
            return Err(CaptureError::InvalidWindowContext);
        }
        // Count serialized metadata through a capped writer rather than allocate
        // a potentially enormous serialized copy just to discover its size.
        let mut counter = ByteLimit {
            remaining: limits.max_metadata_bytes,
        };
        if identity.write_json(&mut counter).is_err() {
            return Err(CaptureError::MetadataLimitExceeded);
        }
        let mut records = Vec::new();
        records
            .try_reserve_exact(limits.max_records)
            .map_err(|_| CaptureError::AllocationFailed)?;
        Ok(Self {
            identity,
            limits,
            start_ns,
            last_observed_ns: start_ns,
            previous_eligible_present_ns: None,
            records,
            failure: None,
            cpu_frame_stages: Vec::new(),
        })
    }
    /// Allocate once, only when recording an instrumented frame. At most one
    /// sample belongs to each retained terminal record; this shares its limit.
    pub(crate) fn enable_cpu_frame_stages(&mut self, at_ns: u64) -> Result<(), CaptureError> {
        if self.cpu_frame_stages.capacity() == 0
            && self
                .cpu_frame_stages
                .try_reserve_exact(self.limits.max_records)
                .is_err()
        {
            return self.fail(at_ns, CaptureError::AllocationFailed);
        }
        Ok(())
    }
    pub(crate) fn record_cpu_frame_stages(&mut self, frame: CpuFrameStages, at_ns: u64) {
        // Called only after the terminal event was retained successfully. The
        // separately indexed extension leaves all v1 records and counts intact.
        debug_assert!(!self.records.is_empty());
        debug_assert!(self.cpu_frame_stages.len() < self.limits.max_records);
        self.cpu_frame_stages.push(CpuFrameSample {
            record_index: self.records.len() - 1,
            finished_at_ns: at_ns,
            frame,
        });
    }
    /// Every successful present must pass its current eligibility explicitly.
    /// The first eligible present after start/exclusion is a baseline, not a sample.
    pub fn record_present_return(
        &mut self,
        at_ns: u64,
        eligibility: Eligibility,
    ) -> Result<(), CaptureError> {
        self.check_event(at_ns)?;
        let interval_ns = if eligibility == Eligibility::Eligible {
            self.previous_eligible_present_ns
                .map(|previous| at_ns - previous)
        } else {
            None
        };
        self.records.push(RawRecord {
            at_ns,
            kind: RecordKind::PresentReturn {
                eligibility,
                interval_ns,
            },
        });
        self.previous_eligible_present_ns = if eligibility == Eligibility::Eligible {
            Some(at_ns)
        } else {
            None
        };
        self.last_observed_ns = at_ns;
        Ok(())
    }
    /// Retain an ordinary surface-acquisition retry without resetting the last
    /// eligible present. The next successful present includes the entire active
    /// wall-clock gap, even across many retries. This is not a successful present.
    /// Explicit focus/pause/minimize/resize exclusions must use `boundary` or the
    /// per-present eligibility/context APIs instead.
    pub fn record_skipped_frame(
        &mut self,
        at_ns: u64,
        reason: BoundaryReason,
    ) -> Result<(), CaptureError> {
        self.check_event(at_ns)?;
        self.records.push(RawRecord {
            at_ns,
            kind: RecordKind::SkippedFrame { reason },
        });
        self.last_observed_ns = at_ns;
        Ok(())
    }
    /// An explicit exclusion/discontinuity breaks the interval chain but does
    /// not persistently set eligibility. Ordinary Ready/Skip retries must use
    /// `record_skipped_frame` so they cannot erase an active long frame gap.
    pub fn boundary(&mut self, at_ns: u64, reason: BoundaryReason) -> Result<(), CaptureError> {
        self.check_event(at_ns)?;
        self.records.push(RawRecord {
            at_ns,
            kind: RecordKind::Boundary { reason },
        });
        self.previous_eligible_present_ns = None;
        self.last_observed_ns = at_ns;
        Ok(())
    }
    /// Retain observed window state and begin a new interval segment. Changes to
    /// scene/backend/build require stopping and starting a separately identified run.
    pub fn update_window_context(
        &mut self,
        at_ns: u64,
        context: WindowContext,
    ) -> Result<(), CaptureError> {
        self.check_event(at_ns)?;
        if !context.valid() {
            return self.fail(at_ns, CaptureError::InvalidWindowContext);
        }
        self.records.push(RawRecord {
            at_ns,
            kind: RecordKind::WindowContext { context },
        });
        self.previous_eligible_present_ns = None;
        self.last_observed_ns = at_ns;
        Ok(())
    }
    fn fail(&mut self, at_ns: u64, error: CaptureError) -> Result<(), CaptureError> {
        self.failure = Some((at_ns, error));
        self.previous_eligible_present_ns = None;
        Err(error)
    }
    fn check_event(&mut self, at_ns: u64) -> Result<(), CaptureError> {
        if let Some((_, error)) = self.failure {
            return Err(error);
        }
        if at_ns < self.last_observed_ns {
            return self.fail(
                at_ns,
                CaptureError::NonMonotonicTimestamp {
                    previous_ns: self.last_observed_ns,
                    received_ns: at_ns,
                },
            );
        }
        if self.records.len() == self.limits.max_records {
            return self.fail(
                at_ns,
                CaptureError::RecordLimitExceeded {
                    max_records: self.limits.max_records,
                },
            );
        }
        Ok(())
    }
    /// Consume the observer, preserving incomplete evidence on every failure.
    /// Stop time does not synthesize a present or an interval.
    pub fn stop(mut self, at_ns: u64) -> FramePerformanceReport {
        // A rejected forward event still establishes that the caller observed
        // that clock time. Do not call an earlier stop timestamp valid.
        let latest_ns = self.failure.map_or(self.last_observed_ns, |(at, _)| {
            at.max(self.last_observed_ns)
        });
        let valid_stop = at_ns >= latest_ns;
        if !valid_stop && self.failure.is_none() {
            self.failure = Some((
                at_ns,
                CaptureError::NonMonotonicTimestamp {
                    previous_ns: self.last_observed_ns,
                    received_ns: at_ns,
                },
            ));
        }
        let summary = IntervalSummary::from_records(&self.records);
        if summary.interval_count == 0 && self.failure.is_none() {
            self.failure = Some((at_ns, CaptureError::NoEligibleIntervals));
        }
        let successful_present_count = self
            .records
            .iter()
            .filter(|record| matches!(record.kind, RecordKind::PresentReturn { .. }))
            .count();
        let ineligible_present_count = self
            .records
            .iter()
            .filter(|record| {
                matches!(
                    record.kind,
                    RecordKind::PresentReturn {
                        eligibility: Eligibility::Ineligible(_),
                        ..
                    }
                )
            })
            .count();
        let skipped_frame_count = self
            .records
            .iter()
            .filter(|record| matches!(record.kind, RecordKind::SkippedFrame { .. }))
            .count();
        FramePerformanceReport {
            identity: self.identity,
            limits: self.limits,
            start_ns: self.start_ns,
            stop_requested_ns: at_ns,
            stopped_at_ns: valid_stop.then_some(at_ns),
            last_observed_ns: self.last_observed_ns,
            incomplete_at_ns: self.failure.map(|(at, _)| at),
            status: self.failure.map_or(CaptureStatus::Complete, |(_, error)| {
                CaptureStatus::Incomplete(error)
            }),
            successful_present_count,
            ineligible_present_count,
            skipped_frame_count,
            summary,
            records: self.records,
            cpu_frame_stages: self.cpu_frame_stages,
        }
    }
}
struct ByteLimit {
    remaining: usize,
}
impl Write for ByteLimit {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        self.remaining = self
            .remaining
            .checked_sub(bytes.len())
            .ok_or_else(|| io::Error::other("metadata limit exceeded"))?;
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

#[derive(Debug)]
pub struct FramePerformanceReport {
    pub identity: RunIdentity,
    pub limits: CaptureLimits,
    pub start_ns: u64,
    pub stop_requested_ns: u64,
    pub stopped_at_ns: Option<u64>,
    /// Last successfully retained event time, or start time if none were retained.
    pub last_observed_ns: u64,
    pub incomplete_at_ns: Option<u64>,
    pub status: CaptureStatus,
    /// Count of retained successful-present events, including ineligible ones.
    /// When incomplete, later activity is explicitly unobserved, never inferred.
    pub successful_present_count: usize,
    pub ineligible_present_count: usize,
    /// Retained ordinary retries; these preserve the active present-return gap.
    pub skipped_frame_count: usize,
    pub summary: IntervalSummary,
    records: Vec<RawRecord>,
    cpu_frame_stages: Vec<CpuFrameSample>,
}
impl FramePerformanceReport {
    pub fn raw_records(&self) -> &[RawRecord] {
        &self.records
    }
    pub fn to_json(&self) -> Value {
        let mut report = json!({"schema":"rust_duty_frame_performance_v1","measurement":MEASUREMENT,
            "clock":"caller_injected_monotonic_nanoseconds","interpretation":"CPU wall-clock intervals between successful present returns; not GPU time, display cadence or simulation time.",
            "identity":self.identity.to_json(),"status":self.status.to_json(),
            "start_ns":self.start_ns,"stop_requested_ns":self.stop_requested_ns,"stopped_at_ns":self.stopped_at_ns,
            "last_observed_ns":self.last_observed_ns,"incomplete_at_ns":self.incomplete_at_ns,
            "limits":{"max_records":self.limits.max_records,"max_metadata_bytes":self.limits.max_metadata_bytes},
            "successful_present_count":self.successful_present_count,"ineligible_present_count":self.ineligible_present_count,
            "skipped_frame_count":self.skipped_frame_count,
            "count_scope":"retained events only; incomplete capture does not assert counts for unobserved activity",
            "summary":self.summary.to_json(),"records":self.records.iter().map(|record| record.to_json()).collect::<Vec<_>>()});
        if !self.cpu_frame_stages.is_empty() {
            report["cpu_frame_stages"] = json!({
                "measurement":CPU_STAGE_MEASUREMENT,"interpretation":CPU_STAGE_INTERPRETATION,
                "stage_definitions":{
                    "surface_acquire":"CPU time in the surface acquisition call, including its internal recovery/retry; excludes surface resize/configuration before the call.",
                    "game_recording":"CPU time from acquired-frame recorder setup through application/input work and draw-list preparation, ending before renderer submission.",
                    "renderer_submit":"CPU time preparing resources, encoding and submitting commands, validating, and completing any requested diagnostic readbacks; excludes the present call and post-present error check.",
                    "present_call":"CPU time in queue.present only; return does not establish GPU completion or display scan-out."
                },
                "samples":self.cpu_frame_stages.iter().map(CpuFrameSample::to_json).collect::<Vec<_>>()
            });
        }
        report
    }
    /// Reserve a new path exclusively, then serialize, flush, and sync. Existing
    /// paths (including symlinks) are never overwritten. A failure after creation
    /// may leave a partial file; its error explicitly says so. Partial files must
    /// not be treated as evidence, and are not silently removed or replaced.
    pub fn write_new(&self, path: impl AsRef<Path>) -> Result<CaptureStatus, WriteError> {
        let file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(path)
            .map_err(|source| WriteError {
                stage: WriteStage::Create,
                partial_file_possible: false,
                source,
            })?;
        let mut writer = BufWriter::new(file);
        self.write_payload(&mut writer)?;
        writer.get_ref().sync_all().map_err(|source| WriteError {
            stage: WriteStage::Sync,
            partial_file_possible: true,
            source,
        })?;
        Ok(self.status)
    }
    fn write_payload(&self, writer: &mut impl Write) -> Result<(), WriteError> {
        serde_json::to_writer_pretty(&mut *writer, &self.to_json()).map_err(|source| {
            WriteError {
                stage: WriteStage::Serialize,
                partial_file_possible: true,
                source: io::Error::other(source),
            }
        })?;
        writer
            .write_all(b"\n")
            .and_then(|_| writer.flush())
            .map_err(|source| WriteError {
                stage: WriteStage::Flush,
                partial_file_possible: true,
                source,
            })?;
        Ok(())
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum WriteStage {
    Create,
    Serialize,
    Flush,
    Sync,
}
#[derive(Debug)]
pub struct WriteError {
    pub stage: WriteStage,
    pub partial_file_possible: bool,
    pub source: io::Error,
}
impl fmt::Display for WriteError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "performance report {:?} failed: {}; partial file possible: {}",
            self.stage, self.source, self.partial_file_possible
        )
    }
}
impl std::error::Error for WriteError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        Some(&self.source)
    }
}

#[cfg(test)]
mod write_failure_tests {
    use super::*;

    struct FailingWriter {
        remaining: usize,
        fail_flush: bool,
    }
    impl Write for FailingWriter {
        fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
            if self.remaining == 0 {
                return Err(io::Error::other("injected write failure"));
            }
            let count = bytes.len().min(self.remaining);
            self.remaining -= count;
            Ok(count)
        }
        fn flush(&mut self) -> io::Result<()> {
            if self.fail_flush {
                Err(io::Error::other("injected flush failure"))
            } else {
                Ok(())
            }
        }
    }
    #[test]
    fn serialization_and_flush_failures_never_report_a_saved_capture() {
        let identity = RunIdentity {
            runtime: RuntimeIdentity {
                actual_backend: None,
                actual_adapter: Value::Null,
                build: Value::Null,
                scene: Value::Null,
                initial_window: WindowContext {
                    physical_width: 1,
                    physical_height: 1,
                    scale_factor: 1.0,
                    mode: WindowMode::Unknown,
                },
            },
            operator_supplied: Value::Null,
        };
        let report = FramePerformanceObserver::start(identity, 0, CaptureLimits::default())
            .unwrap()
            .stop(0);
        for (remaining, fail_flush, stage) in [
            (10, false, WriteStage::Serialize),
            (usize::MAX, true, WriteStage::Flush),
        ] {
            let error = report
                .write_payload(&mut FailingWriter {
                    remaining,
                    fail_flush,
                })
                .unwrap_err();
            assert_eq!(error.stage, stage);
            assert!(error.partial_file_possible);
            assert!(error.to_string().contains("failed"));
        }
    }
}
