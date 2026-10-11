//! Optional GPU diagnostics owned by the same bounded CPU capture lifecycle.
//! No hook here polls or waits for GPU completion. Primary frame status is unchanged.
use crate::render::gpu_timing::{self, Availability, BeginFrame, FrameKey, GpuSample,
    GpuTimer, SampleTicket, SubmissionValidation};
use serde_json::{json, Value};
use std::{cell::RefCell, fs::OpenOptions, io::{BufWriter, Write}, path::{Path, PathBuf}};

pub const SCHEMA: &str = "rust_duty_frame_gpu_timing_v1";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct Registration(u64);

#[derive(Default)]
struct State {
    next_registration: u64,
    next_session: u64,
    registration: Option<Registration>,
    device: Option<(wgpu::Device, wgpu::Queue, bool)>,
    active: Option<Active>,
}
struct Active {
    data: CaptureData,
    timer: Option<GpuTimer>,
    availability: Value,
    adapter_supports_features: bool,
    device_features_enabled: bool,
}
#[derive(Debug)]
struct Attempt {
    key: FrameKey,
    record_index: Option<usize>,
    sample: Option<GpuSample>,
}
#[derive(Debug)]
struct CaptureData {
    session: u64,
    max_attempts: usize,
    attempts: Vec<Attempt>,
    error: Option<String>,
}
impl CaptureData {
    fn new(session: u64, max_attempts: usize) -> Self {
        let mut attempts = Vec::new();
        let error = attempts.try_reserve_exact(max_attempts).err()
            .map(|_| "GPU diagnostic attempt allocation failed".to_owned());
        Self { session, max_attempts, attempts, error }
    }
    fn invalidate(&mut self, error: impl Into<String>) {
        self.error.get_or_insert_with(|| error.into().chars().take(4096).collect());
    }
    fn begin_attempt(&mut self) -> Option<FrameKey> {
        if self.error.is_some() {
            return None;
        }
        if self.attempts.len() >= self.max_attempts {
            self.invalidate("GPU diagnostic attempt limit reached");
            return None;
        }
        let key = FrameKey { session: self.session, attempt: self.attempts.len() as u64 };
        self.attempts.push(Attempt { key, record_index: None, sample: None });
        Some(key)
    }
    fn attempt_mut(&mut self, key: FrameKey) -> Option<&mut Attempt> {
        if key.session != self.session || key.attempt >= self.attempts.len() as u64 {
            self.invalidate("GPU diagnostic result has an unknown session or attempt");
            return None;
        }
        self.attempts.get_mut(key.attempt as usize)
    }
    fn join(&mut self, key: FrameKey, record_index: usize) {
        let Some(attempt) = self.attempt_mut(key) else { return; };
        if attempt.record_index.is_some() {
            self.invalidate("GPU diagnostic attempt has duplicate CPU joins");
        } else {
            attempt.record_index = Some(record_index);
        }
    }
    fn sample(&mut self, sample: GpuSample) {
        let Some(attempt) = self.attempt_mut(sample.frame) else { return; };
        if attempt.sample.is_some() {
            self.invalidate("GPU diagnostic attempt has duplicate results");
        } else {
            attempt.sample = Some(sample);
        }
    }
    fn validate_joins(&mut self, record_count: usize) {
        let mut previous = None;
        for attempt in &self.attempts {
            let Some(index) = attempt.record_index else {
                self.invalidate("GPU diagnostic attempt has no retained CPU terminal record");
                return;
            };
            if index >= record_count || previous.is_some_and(|old| index <= old) {
                self.invalidate("GPU diagnostic CPU record joins are invalid or unordered");
                return;
            }
            previous = Some(index);
        }
    }
    fn rows(&self) -> Vec<Value> {
        self.attempts.iter().map(|attempt| {
            let sample = attempt.sample.as_ref();
            json!({"session":attempt.key.session,"attempt":attempt.key.attempt,
                "record_index":attempt.record_index,
                "status":sample.map_or("not_submitted", |sample| sample.status.label()),
                "start_ticks":sample.and_then(|sample| sample.start_ticks),
                "end_ticks":sample.and_then(|sample| sample.end_ticks),
                "timestamp_period_ns":sample.and_then(|sample| sample.timestamp_period_ns),
                "elapsed_ns":sample.and_then(|sample| sample.elapsed_ns)})
        }).collect()
    }
}
impl Active {
    fn finish_timer(&mut self) {
        if let Some(mut timer) = self.timer.take() {
            for sample in timer.finish_nonblocking() {
                self.data.sample(sample);
            }
        }
    }
}
thread_local! { static STATE: RefCell<State> = RefCell::new(State::default()); }

/// Register only an explicitly enabled, successfully initialized windowed renderer.
/// Device/queue clones keep shutdown diagnostics safe if the window is dropped first.
pub(crate) fn register(device: &wgpu::Device, queue: &wgpu::Queue,
    adapter_supports_features: bool) -> Option<Registration> {
    STATE.with(|state| {
        let mut state = state.borrow_mut();
        if let Some(active) = &mut state.active {
            active.finish_timer();
            active.data.invalidate("GPU renderer replaced during an active capture");
        }
        state.next_registration = state.next_registration.checked_add(1)?;
        let registration = Registration(state.next_registration);
        state.registration = Some(registration);
        state.device = Some((device.clone(), queue.clone(), adapter_supports_features));
        Some(registration)
    })
}
pub(crate) fn unregister(registration: Registration) {
    // A renderer held in another thread-local may drop after this state has
    // already been destroyed during thread shutdown.
    let _ = STATE.try_with(|state| {
        let mut state = state.borrow_mut();
        if state.registration != Some(registration) { return; }
        if let Some(active) = &mut state.active {
            active.finish_timer();
            active.data.invalidate("GPU renderer released before capture completion");
        }
        state.device = None;
        state.registration = None;
    });
}

fn availability_json(value: Availability) -> Value {
    match value {
        Availability::Disabled => json!({"state":"disabled"}),
        Availability::DeviceFeaturesNotEnabled { .. } => json!({"state":"device_features_not_enabled"}),
        Availability::InvalidTimestampPeriod => json!({"state":"invalid_timestamp_period"}),
        Availability::Available { timestamp_period_ns } => json!({"state":"available","timestamp_period_ns":timestamp_period_ns}),
    }
}

/// Called once after the primary observer accepts a new capture. Default-off
/// sessions return before allocations, clocks, GPU resources or filesystem work.
pub(crate) fn start_session(max_attempts: usize) -> Option<u64> {
    STATE.with(|state| {
        let mut state = state.borrow_mut();
        let (device, queue, adapter_supports_features) = state.device.as_ref()?.clone();
        if state.active.is_some() { return None; }
        state.next_session = state.next_session.checked_add(1)?;
        let session = state.next_session;
        let mut data = CaptureData::new(session, max_attempts);
        let device_features_enabled = device.features().contains(gpu_timing::required_features());
        let (timer, availability) = if data.error.is_none() {
            let scope = device.push_error_scope(wgpu::ErrorFilter::Validation);
            let mut timer = GpuTimer::new(&device, &queue, true);
            let availability = availability_json(timer.availability());
            // wgpu 30 native error-scope pop is CPU validation handling, not a
            // GPU fence. This does not poll/drain the device or wait for work.
            if let Some(error) = pollster::block_on(scope.pop()) {
                data.invalidate(format!("GPU diagnostic initialization validation: {error}"));
                let _ = timer.finish_nonblocking();
                (None, json!({"state":"initialization_failed"}))
            } else {
                (Some(timer), availability)
            }
        } else {
            (None, json!({"state":"allocation_failed"}))
        };
        state.active = Some(Active { data, timer, availability,
            adapter_supports_features, device_features_enabled });
        Some(session)
    })
}
pub(crate) fn begin_attempt(session: u64) -> Option<FrameKey> {
    STATE.with(|state| {
        let mut state = state.borrow_mut();
        let active = state.active.as_mut()?;
        if active.data.session != session { return None; }
        active.data.begin_attempt()
    })
}
pub(crate) fn join_cpu_record(key: FrameKey, index: usize) {
    STATE.with(|state| {
        if let Some(active) = &mut state.borrow_mut().active {
            active.data.join(key, index);
        }
    });
}

/// Guard releases any encoder abandoned through an ordinary Rust error path.
/// After real submission it must never abandon or reuse the readback early.
pub(crate) struct GpuAttempt {
    key: FrameKey,
    ticket: Option<SampleTicket>,
    submitted: bool,
}
pub(crate) fn begin_gpu_frame(registration: Registration, key: FrameKey, encoder: &mut wgpu::CommandEncoder) -> Option<GpuAttempt> {
    STATE.with(|state| {
        let mut state = state.borrow_mut();
        if !owns_attempt(&state, registration, key) { return None; }
        let active = state.active.as_mut()?;
        let result = active.timer.as_mut()?.begin_frame(key, encoder);
        match result {
            BeginFrame::Recording(ticket) => Some(GpuAttempt { key, ticket: Some(ticket), submitted: false }),
            BeginFrame::Unavailable(sample) => { active.data.sample(sample); None }
        }
    })
}
fn owns_attempt(state: &State, registration: Registration, key: FrameKey) -> bool {
    state.registration == Some(registration)
        && state.active.as_ref().is_some_and(|active| active.data.session == key.session)
}

impl GpuAttempt {
    fn with_timer(&self, call: impl FnOnce(&mut GpuTimer, &SampleTicket) -> Result<(), &'static str>) -> bool {
        let Some(ticket) = &self.ticket else { return false; };
        STATE.with(|state| {
            let mut state = state.borrow_mut();
            let Some(active) = &mut state.active else { return false; };
            if active.data.session != self.key.session { return false; }
            let Some(timer) = &mut active.timer else { return false; };
            match call(timer, ticket) {
                Ok(()) => true,
                Err(error) => { active.data.invalidate(error); false }
            }
        })
    }
    pub(crate) fn end_encoding(&mut self, encoder: &mut wgpu::CommandEncoder) -> Result<(), String> {
        if self.with_timer(|timer, ticket| timer.end_frame(ticket, encoder)) {
            Ok(())
        } else {
            // The caller must not submit this encoder. Error unwinding drops
            // the encoder and abandons its still-unsubmitted reservation.
            Err("GPU diagnostic encoding lifecycle failed before submission".into())
        }
    }
    pub(crate) fn after_submit(&mut self) {
        self.submitted = true;
        self.with_timer(|timer, ticket| timer.after_submit(ticket));
    }
    pub(crate) fn validate_submission(&self, accepted: bool) {
        let verdict = if accepted { SubmissionValidation::Accepted } else { SubmissionValidation::Rejected };
        self.with_timer(|timer, ticket| timer.record_submission_validation(ticket, verdict));
    }
    fn abandon(&mut self) {
        if self.submitted { return; }
        let Some(ticket) = self.ticket.take() else { return; };
        STATE.with(|state| {
            let mut state = state.borrow_mut();
            let Some(active) = &mut state.active else { return; };
            if active.data.session != self.key.session { return; }
            let Some(timer) = &mut active.timer else { return; };
            match timer.abandon_unsubmitted(&ticket) {
                Ok(sample) => active.data.sample(sample),
                Err(error) => active.data.invalidate(error),
            }
        });
    }
}
impl Drop for GpuAttempt {
    fn drop(&mut self) { self.abandon(); }
}
pub(crate) fn collect_ready(registration: Registration) {
    STATE.with(|state| {
        let mut state = state.borrow_mut();
        if state.registration != Some(registration) { return; }
        let Some(active) = &mut state.active else { return; };
        if let Some(timer) = &mut active.timer {
            for sample in timer.collect_ready() { active.data.sample(sample); }
        }
    });
}

pub(crate) struct GpuCaptureReport(Active);
pub(crate) fn finish_session(session: u64, record_count: usize) -> Option<GpuCaptureReport> {
    STATE.with(|state| {
        let mut state = state.borrow_mut();
        if state.active.as_ref()?.data.session != session { return None; }
        let mut active = state.active.take()?;
        active.finish_timer();
        active.data.validate_joins(record_count);
        Some(GpuCaptureReport(active))
    })
}
impl GpuCaptureReport {
    pub(crate) fn accounting_complete(&self) -> bool { self.0.data.error.is_none() }
    pub(crate) fn write_new(&self, frame_path: &Path) -> Result<PathBuf, String> {
        let hash = rust_duty_launcher::file_hash(frame_path).map_err(|error| error.to_string())?;
        let active = &self.0;
        let value = json!({"schema":SCHEMA,"measurement":gpu_timing::MEASUREMENT,
            "scope":gpu_timing::SCOPE,"frame_report_sha256":hash,
            "accounting_state":if active.data.error.is_some() { "incomplete" } else { "complete" },
            "error":active.data.error,"session":active.data.session,
            "limits":{"max_attempts":active.data.max_attempts,"ring_slots":gpu_timing::SLOT_COUNT},
            "availability":active.availability,
            "feature_negotiation":{"adapter_supports_required_features":active.adapter_supports_features,
                "device_features_enabled":active.device_features_enabled},
            "samples":active.data.rows()});
        let path = frame_path.with_extension("gpu-timing.json");
        let file = OpenOptions::new().write(true).create_new(true).open(&path)
            .map_err(|error| format!("create {}: {error}", path.display()))?;
        let mut writer = BufWriter::new(file);
        let result = (|| -> Result<(), String> {
            serde_json::to_writer_pretty(&mut writer, &value).map_err(|error| error.to_string())?;
            writer.flush().map_err(|error| error.to_string())?;
            writer.get_ref().sync_all().map_err(|error| error.to_string())?;
            Ok(())
        })();
        result.map_err(|error| format!("write {}: {error}; partial file possible", path.display()))?;
        Ok(path)
    }
}

/// CPU-only lifecycle seam: no device, encoder, submission or timestamp result.
#[cfg(test)]
pub(crate) fn start_synthetic_session(max_attempts: usize) -> u64 {
    STATE.with(|state| {
        let mut state = state.borrow_mut();
        assert!(state.active.is_none());
        state.next_session += 1;
        let session = state.next_session;
        state.active = Some(Active {
            data: CaptureData::new(session, max_attempts), timer: None,
            availability: json!({"state":"device_features_not_enabled"}),
            adapter_supports_features: false, device_features_enabled: false,
        });
        session
    })
}
#[cfg(test)]
pub(crate) fn synthetic_session_is_active() -> bool {
    STATE.with(|state| state.borrow().active.is_some())
}

#[cfg(test)]
mod tests {
    use super::*;
    use gpu_timing::SampleStatus;
    #[test]
    fn recording_requires_both_current_renderer_registration_and_capture_session() {
        let mut state = State { registration: Some(Registration(2)), ..State::default() };
        state.active = Some(Active {
            data: CaptureData::new(7, 1), timer: None,
            availability: json!({"state":"device_features_not_enabled"}),
            adapter_supports_features: false, device_features_enabled: false,
        });
        let key = FrameKey { session: 7, attempt: 0 };
        assert!(owns_attempt(&state, Registration(2), key));
        assert!(!owns_attempt(&state, Registration(1), key));
        assert!(!owns_attempt(&state, Registration(2), FrameKey { session: 6, attempt: 0 }));
        state.registration = None;
        assert!(!owns_attempt(&state, Registration(2), key));
    }
    fn sample(key: FrameKey) -> GpuSample {
        GpuSample { frame:key, status:SampleStatus::Measured, start_ticks:Some(10),
            end_ticks:Some(20), timestamp_period_ns:Some(2.0), elapsed_ns:Some(20.0) }
    }
    #[test]
    fn callbacks_join_exact_attempts_even_when_completion_order_differs() {
        let mut data = CaptureData::new(7, 3);
        let first = data.begin_attempt().unwrap();
        let second = data.begin_attempt().unwrap();
        data.join(first, 2);
        data.join(second, 4);
        data.sample(sample(second));
        data.sample(sample(first));
        data.validate_joins(5);
        assert!(data.error.is_none());
        assert_eq!(data.rows()[0]["record_index"], 2);
        assert_eq!(data.rows()[1]["record_index"], 4);
    }
    #[test]
    fn skipped_attempts_keep_missing_time_and_do_not_shift_later_joins() {
        let mut data = CaptureData::new(8, 2);
        let skipped = data.begin_attempt().unwrap();
        let presented = data.begin_attempt().unwrap();
        data.join(skipped, 0);
        data.join(presented, 1);
        data.sample(sample(presented));
        data.validate_joins(2);
        let rows = data.rows();
        assert_eq!(rows[0]["status"], "not_submitted");
        assert!(rows[0]["elapsed_ns"].is_null());
        assert_eq!(rows[1]["attempt"], 1);
        assert_eq!(rows[1]["elapsed_ns"], 20.0);
    }
    #[test]
    fn stale_duplicate_and_unjoined_attempts_fail_only_diagnostic_accounting() {
        let mut data = CaptureData::new(9, 1);
        let key = data.begin_attempt().unwrap();
        let mut stale = sample(key);
        stale.frame.session = 8;
        data.sample(stale);
        assert!(data.attempts[0].sample.is_none());
        assert!(data.error.is_some());
        let mut data = CaptureData::new(9, 1);
        let key = data.begin_attempt().unwrap();
        data.sample(sample(key));
        data.sample(sample(key));
        assert!(data.error.is_some());
        let mut data = CaptureData::new(9, 1);
        data.begin_attempt().unwrap();
        data.validate_joins(1);
        assert!(data.error.is_some());
    }
    #[test]
    fn attempt_limit_and_duplicate_cpu_record_never_silently_truncate() {
        let mut data = CaptureData::new(9, 1);
        data.begin_attempt().unwrap();
        assert!(data.begin_attempt().is_none());
        assert_eq!(data.attempts.len(), 1);
        assert!(data.error.is_some());
        let mut data = CaptureData::new(9, 2);
        let first = data.begin_attempt().unwrap();
        let second = data.begin_attempt().unwrap();
        data.join(first, 0);
        data.join(second, 0);
        data.validate_joins(1);
        assert!(data.error.is_some());
    }
}
