//! Opt-in, bounded GPU timestamps for the main ordered frame command buffer.
//!
//! This module never polls the device, waits, submits work, or presents a frame.
//! The integration owner must request `requested_features`, preserve validation,
//! and call `collect_ready` after an existing nonblocking device poll. A sample
//! covers only commands between `begin_frame` and `end_frame`; it excludes other
//! submissions (including lazy render-target initialization), surface acquisition,
//! CPU preparation, DXGI present/scan-out, and its own resolve/readback commands.
//! Timestamp ordering/precision remain backend and driver dependent.
use std::sync::{
    atomic::{AtomicU8, Ordering},
    Arc,
};

pub const SLOT_COUNT: usize = 4;
pub const MEASUREMENT: &str = "frame_command_buffer_gpu_elapsed_ns";
pub const SCOPE: &str = "GPU timestamps around the main ordered frame command buffer; excludes other submissions, CPU work, surface acquisition, present/scan-out and trailing timestamp resolve/readback; backend/driver timestamp ordering and precision apply";
const RESULT_BYTES: u64 = 16;
const CALLBACK_PENDING: u8 = 0;
const CALLBACK_READY: u8 = 1;
const CALLBACK_FAILED: u8 = 2;

/// Request the complete encoder-timestamp feature pair, or neither feature.
/// Unsupported profiling must not make ordinary device creation fail.
pub fn requested_features(enabled: bool, available: wgpu::Features) -> wgpu::Features {
    let required = required_features();
    if enabled && available.contains(required) {
        required
    } else {
        wgpu::Features::empty()
    }
}

pub fn required_features() -> wgpu::Features {
    wgpu::Features::TIMESTAMP_QUERY | wgpu::Features::TIMESTAMP_QUERY_INSIDE_ENCODERS
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Availability {
    Disabled,
    Unsupported { missing_features: wgpu::Features },
    InvalidTimestampPeriod,
    Available { timestamp_period_ns: f64 },
}

fn availability(enabled: bool, enabled_features: wgpu::Features, period_ns: f64) -> Availability {
    if !enabled {
        Availability::Disabled
    } else if !enabled_features.contains(required_features()) {
        Availability::Unsupported {
            missing_features: required_features() - enabled_features,
        }
    } else if !period_ns.is_finite() || period_ns <= 0.0 {
        Availability::InvalidTimestampPeriod
    } else {
        Availability::Available {
            timestamp_period_ns: period_ns,
        }
    }
}

/// Caller-assigned identity, allocated before recording and shared with CPU data.
/// Session identity prevents late GPU results from joining a subsequent session.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct FrameKey {
    pub session: u64,
    pub attempt: u64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SampleStatus {
    Measured,
    Disabled,
    Unsupported,
    InvalidTimestampPeriod,
    RingFull,
    MapFailed,
    InvalidTimestampOrder,
    AbandonedBeforeSubmit,
    PendingAtStop,
    Stopped,
}

impl SampleStatus {
    pub const fn label(self) -> &'static str {
        match self {
            Self::Measured => "measured",
            Self::Disabled => "disabled",
            Self::Unsupported => "unsupported",
            Self::InvalidTimestampPeriod => "invalid_timestamp_period",
            Self::RingFull => "ring_full",
            Self::MapFailed => "map_failed",
            Self::InvalidTimestampOrder => "invalid_timestamp_order",
            Self::AbandonedBeforeSubmit => "abandoned_before_submit",
            Self::PendingAtStop => "pending_at_stop",
            Self::Stopped => "stopped",
        }
    }
}

/// Missing values remain None; no missing/failed sample becomes zero GPU time.
/// This says nothing about whether this attempt successfully presented or was
/// eligible gameplay. Join by FrameKey and retain those independent CPU facts.
#[derive(Clone, Debug, PartialEq)]
pub struct GpuSample {
    pub frame: FrameKey,
    pub status: SampleStatus,
    pub start_ticks: Option<u64>,
    pub end_ticks: Option<u64>,
    pub timestamp_period_ns: Option<f64>,
    pub elapsed_ns: Option<f64>,
}

impl GpuSample {
    fn unavailable(frame: FrameKey, status: SampleStatus) -> Self {
        Self {
            frame,
            status,
            start_ticks: None,
            end_ticks: None,
            timestamp_period_ns: None,
            elapsed_ns: None,
        }
    }

    fn from_ticks(frame: FrameKey, start: u64, end: u64, period_ns: f64) -> Self {
        let elapsed_ns = end.checked_sub(start).map(|ticks| ticks as f64 * period_ns);
        Self {
            frame,
            status: if elapsed_ns.is_some() {
                SampleStatus::Measured
            } else {
                SampleStatus::InvalidTimestampOrder
            },
            start_ticks: Some(start),
            end_ticks: Some(end),
            timestamp_period_ns: Some(period_ns),
            elapsed_ns,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Phase {
    Free,
    Recording,
    Encoded,
    Pending,
}

/// Pure lifecycle state; shared by the actual GPU ring and CPU-only tests.
#[derive(Debug)]
struct Lifecycle {
    generation: u64,
    frame: Option<FrameKey>,
    phase: Phase,
}

impl Lifecycle {
    fn new() -> Self {
        Self {
            generation: 0,
            frame: None,
            phase: Phase::Free,
        }
    }

    fn reserve(&mut self, frame: FrameKey) -> Option<u64> {
        if self.phase != Phase::Free {
            return None;
        }
        // Exhaustion never wraps and can therefore never validate a stale ticket.
        self.generation = self.generation.checked_add(1)?;
        self.frame = Some(frame);
        self.phase = Phase::Recording;
        Some(self.generation)
    }

    fn transition(&mut self, generation: u64, from: Phase, to: Phase) -> Result<(), &'static str> {
        if self.generation != generation || self.phase != from {
            return Err("stale timestamp ticket or invalid lifecycle transition");
        }
        self.phase = to;
        Ok(())
    }

    fn release(&mut self) -> FrameKey {
        let frame = self
            .frame
            .take()
            .expect("occupied timestamp slot has a frame");
        self.phase = Phase::Free;
        frame
    }
}

struct Slot {
    queries: wgpu::QuerySet,
    resolve: wgpu::Buffer,
    readback: wgpu::Buffer,
    completion: Arc<AtomicU8>,
    lifecycle: Lifecycle,
}

/// Opaque reservation. Keep it until submission or explicit abandonment.
/// A ticket is valid only for the timer that created it and its current slot use.
#[derive(Debug)]
pub struct SampleTicket {
    owner: Arc<()>,
    slot: usize,
    generation: u64,
}

#[derive(Debug)]
pub enum BeginFrame {
    Recording(SampleTicket),
    Unavailable(GpuSample),
}

pub struct GpuTimer {
    availability: Availability,
    owner: Arc<()>,
    slots: Vec<Slot>,
    stopped: bool,
}

impl GpuTimer {
    /// Create once for an opted-in diagnostic session. No device/surface is
    /// created here. Disabled/unsupported sessions allocate no GPU resources.
    pub fn new(device: &wgpu::Device, queue: &wgpu::Queue, enabled: bool) -> Self {
        let features = device.features();
        let period_ns = if enabled && features.contains(required_features()) {
            f64::from(queue.get_timestamp_period())
        } else {
            0.0
        };
        let availability = availability(enabled, features, period_ns);
        let slots = if matches!(availability, Availability::Available { .. }) {
            (0..SLOT_COUNT)
                .map(|_| Slot {
                    queries: device.create_query_set(&wgpu::QuerySetDescriptor {
                        label: Some("frame GPU elapsed timestamp pair"),
                        ty: wgpu::QueryType::Timestamp,
                        count: 2,
                    }),
                    resolve: device.create_buffer(&wgpu::BufferDescriptor {
                        label: Some("frame GPU elapsed query resolve"),
                        size: RESULT_BYTES,
                        usage: wgpu::BufferUsages::QUERY_RESOLVE | wgpu::BufferUsages::COPY_SRC,
                        mapped_at_creation: false,
                    }),
                    readback: device.create_buffer(&wgpu::BufferDescriptor {
                        label: Some("frame GPU elapsed asynchronous readback"),
                        size: RESULT_BYTES,
                        usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
                        mapped_at_creation: false,
                    }),
                    completion: Arc::new(AtomicU8::new(CALLBACK_PENDING)),
                    lifecycle: Lifecycle::new(),
                })
                .collect()
        } else {
            Vec::new()
        };
        Self {
            availability,
            owner: Arc::new(()),
            slots,
            stopped: false,
        }
    }

    pub fn availability(&self) -> Availability {
        self.availability
    }

    /// Place immediately before the first command to include in the GPU span.
    /// No free slot means no timestamp commands and an explicit unavailable
    /// sample. Gameplay is still submitted normally; this never drops a frame.
    pub fn begin_frame(
        &mut self,
        frame: FrameKey,
        encoder: &mut wgpu::CommandEncoder,
    ) -> BeginFrame {
        let unavailable = if self.stopped {
            Some(SampleStatus::Stopped)
        } else {
            match self.availability {
                Availability::Disabled => Some(SampleStatus::Disabled),
                Availability::Unsupported { .. } => Some(SampleStatus::Unsupported),
                Availability::InvalidTimestampPeriod => Some(SampleStatus::InvalidTimestampPeriod),
                Availability::Available { .. } => None,
            }
        };
        if let Some(status) = unavailable {
            return BeginFrame::Unavailable(GpuSample::unavailable(frame, status));
        }
        for (index, slot) in self.slots.iter_mut().enumerate() {
            if let Some(generation) = slot.lifecycle.reserve(frame) {
                slot.completion.store(CALLBACK_PENDING, Ordering::Relaxed);
                encoder.write_timestamp(&slot.queries, 0);
                return BeginFrame::Recording(SampleTicket {
                    owner: self.owner.clone(),
                    slot: index,
                    generation,
                });
            }
        }
        BeginFrame::Unavailable(GpuSample::unavailable(frame, SampleStatus::RingFull))
    }

    fn slot(&mut self, ticket: &SampleTicket) -> Result<&mut Slot, &'static str> {
        if !Arc::ptr_eq(&self.owner, &ticket.owner) {
            return Err("timestamp ticket belongs to another timer");
        }
        let slot = self
            .slots
            .get_mut(ticket.slot)
            .ok_or("timestamp timer stopped")?;
        if slot.lifecycle.generation != ticket.generation {
            return Err("stale timestamp ticket");
        }
        Ok(slot)
    }

    /// Place after the final included command/pass and before encoder.finish().
    /// End timestamp precedes resolve/copy, so diagnostic readback is excluded.
    pub fn end_frame(
        &mut self,
        ticket: &SampleTicket,
        encoder: &mut wgpu::CommandEncoder,
    ) -> Result<(), &'static str> {
        let slot = self.slot(ticket)?;
        slot.lifecycle
            .transition(ticket.generation, Phase::Recording, Phase::Encoded)?;
        encoder.write_timestamp(&slot.queries, 1);
        // Offset zero meets QUERY_RESOLVE_BUFFER_ALIGNMENT (256). Two queries
        // write exactly two u64 values; no 256-byte buffer length is required.
        encoder.resolve_query_set(&slot.queries, 0..2, &slot.resolve, 0);
        encoder.copy_buffer_to_buffer(&slot.resolve, 0, &slot.readback, 0, RESULT_BYTES);
        Ok(())
    }

    /// Call only after the SAME encoder's normal queue submission. The callback
    /// merely sets an atomic flag and never blocks the submit/polling thread.
    pub fn after_submit(&mut self, ticket: &SampleTicket) -> Result<(), &'static str> {
        let slot = self.slot(ticket)?;
        slot.lifecycle
            .transition(ticket.generation, Phase::Encoded, Phase::Pending)?;
        let completion = slot.completion.clone();
        slot.readback
            .slice(..)
            .map_async(wgpu::MapMode::Read, move |result| {
                completion.store(
                    if result.is_ok() {
                        CALLBACK_READY
                    } else {
                        CALLBACK_FAILED
                    },
                    Ordering::Release,
                );
            });
        Ok(())
    }

    /// An encoding/submission path that abandoned its encoder must release its
    /// ticket. Never use this after submission, including a failed present.
    pub fn abandon_unsubmitted(
        &mut self,
        ticket: &SampleTicket,
    ) -> Result<GpuSample, &'static str> {
        let slot = self.slot(ticket)?;
        if !matches!(slot.lifecycle.phase, Phase::Recording | Phase::Encoded) {
            return Err("only an unsubmitted timestamp reservation can be abandoned");
        }
        Ok(GpuSample::unavailable(
            slot.lifecycle.release(),
            SampleStatus::AbandonedBeforeSubmit,
        ))
    }

    /// Consume already-delivered callbacks, normally after the application's
    /// existing PollType::Poll. This method itself never polls or waits. Result
    /// count is bounded by SLOT_COUNT; results may arrive after later CPU frames.
    pub fn collect_ready(&mut self) -> Vec<GpuSample> {
        let Availability::Available {
            timestamp_period_ns,
        } = self.availability
        else {
            return Vec::new();
        };
        let mut samples = Vec::new();
        for slot in &mut self.slots {
            if slot.lifecycle.phase != Phase::Pending {
                continue;
            }
            let completion = slot.completion.load(Ordering::Acquire);
            if completion == CALLBACK_PENDING {
                continue;
            }
            let frame = slot.lifecycle.frame.expect("pending timestamp has a frame");
            let sample = if completion == CALLBACK_READY {
                match slot.readback.slice(..).get_mapped_range() {
                    Ok(mapped) => {
                        let start = u64::from_le_bytes(mapped[0..8].try_into().unwrap());
                        let end = u64::from_le_bytes(mapped[8..16].try_into().unwrap());
                        GpuSample::from_ticks(frame, start, end, timestamp_period_ns)
                    }
                    Err(_) => GpuSample::unavailable(frame, SampleStatus::MapFailed),
                }
            } else {
                GpuSample::unavailable(frame, SampleStatus::MapFailed)
            };
            // The mapped view above has been dropped before unmapping or reuse.
            slot.readback.unmap();
            slot.lifecycle.release();
            samples.push(sample);
        }
        samples
    }

    /// Terminal, nonblocking shutdown. Preserve incomplete samples explicitly;
    /// do not add a drain wait to make a diagnostic look complete. Later callbacks
    /// own their old atomic flags, so they cannot modify a replacement timer.
    pub fn finish_nonblocking(&mut self) -> Vec<GpuSample> {
        let mut samples = self.collect_ready();
        self.stopped = true;
        for mut slot in self.slots.drain(..) {
            let status = match slot.lifecycle.phase {
                Phase::Free => continue,
                Phase::Pending => SampleStatus::PendingAtStop,
                Phase::Recording | Phase::Encoded => SampleStatus::AbandonedBeforeSubmit,
            };
            if slot.lifecycle.phase == Phase::Pending {
                slot.readback.unmap();
            }
            samples.push(GpuSample::unavailable(slot.lifecycle.release(), status));
        }
        samples
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn key(attempt: u64) -> FrameKey {
        FrameKey {
            session: 42,
            attempt,
        }
    }

    #[test]
    fn feature_negotiation_requires_both_bits_and_never_requests_unsupported_bits() {
        let required = required_features();
        for enabled in [false, true] {
            for available in [
                wgpu::Features::empty(),
                wgpu::Features::TIMESTAMP_QUERY,
                wgpu::Features::TIMESTAMP_QUERY_INSIDE_ENCODERS,
                required,
                required | wgpu::Features::INDIRECT_FIRST_INSTANCE,
            ] {
                let requested = requested_features(enabled, available);
                assert!(available.contains(requested));
                assert_eq!(
                    requested,
                    if enabled && available.contains(required) {
                        required
                    } else {
                        wgpu::Features::empty()
                    }
                );
            }
        }
    }

    #[test]
    fn unsupported_disabled_and_invalid_period_are_distinct() {
        assert_eq!(
            availability(false, required_features(), 0.0),
            Availability::Disabled
        );
        assert_eq!(
            availability(true, wgpu::Features::TIMESTAMP_QUERY, 1.0),
            Availability::Unsupported {
                missing_features: wgpu::Features::TIMESTAMP_QUERY_INSIDE_ENCODERS,
            }
        );
        for period in [0.0, -1.0, f64::NAN, f64::INFINITY] {
            assert_eq!(
                availability(true, required_features(), period),
                Availability::InvalidTimestampPeriod
            );
        }
        assert_eq!(
            availability(true, required_features(), 2.5),
            Availability::Available {
                timestamp_period_ns: 2.5
            }
        );
    }

    #[test]
    fn conversion_subtracts_integer_ticks_before_floating_point_scaling() {
        let start = u64::MAX - 100;
        let sample = GpuSample::from_ticks(key(1), start, start + 12, 2.5);
        assert_eq!(sample.status, SampleStatus::Measured);
        assert_eq!(sample.elapsed_ns, Some(30.0));
        assert_eq!(sample.start_ticks, Some(start));
        assert_eq!(sample.end_ticks, Some(start + 12));
    }

    #[test]
    fn reversed_ticks_are_invalid_and_equal_ticks_are_a_real_measured_zero() {
        let reversed = GpuSample::from_ticks(key(1), 10, 9, 1.0);
        assert_eq!(reversed.status, SampleStatus::InvalidTimestampOrder);
        assert_eq!(reversed.elapsed_ns, None);
        assert_eq!(reversed.start_ticks, Some(10));
        let equal = GpuSample::from_ticks(key(2), 10, 10, 1.0);
        assert_eq!(equal.status, SampleStatus::Measured);
        assert_eq!(equal.elapsed_ns, Some(0.0));
    }

    #[test]
    fn unavailable_samples_never_synthesize_timestamps_or_zero_duration() {
        for status in [
            SampleStatus::Disabled,
            SampleStatus::Unsupported,
            SampleStatus::InvalidTimestampPeriod,
            SampleStatus::RingFull,
            SampleStatus::MapFailed,
            SampleStatus::AbandonedBeforeSubmit,
            SampleStatus::PendingAtStop,
            SampleStatus::Stopped,
        ] {
            let sample = GpuSample::unavailable(key(3), status);
            assert_eq!(sample.frame, key(3));
            assert_eq!(sample.status, status);
            assert_eq!(sample.elapsed_ns, None);
            assert_eq!(sample.start_ticks, None);
            assert_eq!(sample.end_ticks, None);
            assert_eq!(sample.timestamp_period_ns, None);
        }
    }

    #[test]
    fn pending_slots_cannot_be_overwritten_and_reuse_invalidates_old_generation() {
        let mut slot = Lifecycle::new();
        let first = slot.reserve(key(1)).unwrap();
        assert!(slot.reserve(key(2)).is_none());
        assert!(slot
            .transition(first, Phase::Encoded, Phase::Pending)
            .is_err());
        slot.transition(first, Phase::Recording, Phase::Encoded)
            .unwrap();
        slot.transition(first, Phase::Encoded, Phase::Pending)
            .unwrap();
        assert!(slot.reserve(key(2)).is_none());
        assert_eq!(slot.release(), key(1));
        let second = slot.reserve(key(2)).unwrap();
        assert_ne!(first, second);
        assert!(slot
            .transition(first, Phase::Recording, Phase::Encoded)
            .is_err());
        assert_eq!(slot.frame, Some(key(2)));
    }

    #[test]
    fn bounded_ring_saturation_preserves_each_original_frame() {
        let mut slots: Vec<_> = (0..SLOT_COUNT).map(|_| Lifecycle::new()).collect();
        for (index, slot) in slots.iter_mut().enumerate() {
            let generation = slot.reserve(key(index as u64)).unwrap();
            slot.transition(generation, Phase::Recording, Phase::Encoded)
                .unwrap();
            slot.transition(generation, Phase::Encoded, Phase::Pending)
                .unwrap();
        }
        assert!(slots.iter_mut().all(|slot| slot.reserve(key(99)).is_none()));
        for (index, slot) in slots.iter_mut().enumerate() {
            assert_eq!(slot.release(), key(index as u64));
        }
    }

    #[test]
    fn generation_exhaustion_never_wraps_into_a_stale_reservation() {
        let mut slot = Lifecycle::new();
        slot.generation = u64::MAX;
        assert!(slot.reserve(key(1)).is_none());
        assert_eq!(slot.phase, Phase::Free);
        assert_eq!(slot.frame, None);
    }
}
