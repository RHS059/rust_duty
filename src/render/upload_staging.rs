//! Bounded CPU-mapped upload sources, independent of destination residency.
//! Queued copies and their completion callbacks own each checkout until submit
//! or cancellation. No buffer is reused because a frame count has elapsed.
#[path = "upload_staging_layout.rs"]
mod layout;
pub use crate::frame_encode_detail::staging_policy as policy;

use std::sync::{
    atomic::{AtomicU8, Ordering},
    Arc,
};

pub const MAX_CHUNKS: usize = 8;
pub const RETAINED_BYTES: u64 = 64 * 1024 * 1024;
const PENDING: u8 = 0;
const MAPPED: u8 = 1;
const FAILED: u8 = 2;
const CANCELLED: u8 = 3;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct StagingStats {
    pub staging_buffer_allocations: u64,
    pub staging_buffer_reuses: u64,
    pub staging_buffer_allocated_bytes: u64,
    pub staging_copy_bytes: u64,
    pub staging_queue_write_calls: u64,
    pub staging_queue_write_bytes: u64,
    pub staging_fallback_arenas: u64,
    /// Gauges sampled at the end of the upload phase, not cumulative counters.
    pub staging_retained_bytes: u64,
    pub staging_pending_buffers: u64,
    pub staging_map_failures: u64,
}

pub struct UploadSlice<'a> {
    pub destination: &'a wgpu::Buffer,
    pub offset: u64,
    pub bytes: &'a [u8],
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Ownership {
    Ready,
    Leased,
    Submitted,
    Retired { submitted: bool },
    Failed,
}

#[derive(Debug, PartialEq, Eq)]
enum Reclaim {
    Keep,
    Ready,
    Release,
    Failed,
}

fn reclaim(ownership: Ownership, completion: Option<u8>, hold_ready: bool) -> Reclaim {
    match (ownership, completion) {
        (Ownership::Retired { submitted: false }, None | Some(CANCELLED | MAPPED))
        | (Ownership::Retired { submitted: true }, Some(MAPPED)) => Reclaim::Release,
        (Ownership::Submitted, Some(MAPPED)) if !hold_ready => Reclaim::Ready,
        (Ownership::Submitted | Ownership::Retired { .. }, Some(FAILED | CANCELLED))
        | (Ownership::Failed, _) => Reclaim::Failed,
        _ => Reclaim::Keep,
    }
}

struct Chunk {
    buffer: wgpu::Buffer,
    capacity: u64,
    ownership: Ownership,
    completion: Option<Arc<AtomicU8>>,
}

/// A distinct token for every checkout prevents an old callback from writing
/// into the state of a later checkout or a newly constructed device/pool.
struct Completion(Arc<AtomicU8>);
impl Completion {
    fn finish(self, result: Result<(), wgpu::BufferAsyncError>) {
        self.record(result.is_ok());
    }

    fn record(&self, succeeded: bool) {
        self.0
            .store(if succeeded { MAPPED } else { FAILED }, Ordering::Release);
    }
}
impl Drop for Completion {
    fn drop(&mut self) {
        // An encoder dropped before submission drops its deferred callback.
        // Cancellation is never interpreted as a successful mapping.
        let _ = self
            .0
            .compare_exchange(PENDING, CANCELLED, Ordering::AcqRel, Ordering::Acquire);
    }
}

struct WrittenRange {
    buffer: wgpu::Buffer,
    start: u64,
    end: u64,
}

pub struct StagingPool {
    device: Option<wgpu::Device>,
    chunks: Vec<Chunk>,
    written: Vec<WrittenRange>,
    active: bool,
    enabled: bool,
    budget: u64,
    max_chunks: usize,
    stats: StagingStats,
    #[cfg(test)]
    hold_ready: bool,
}
impl Default for StagingPool {
    fn default() -> Self {
        Self {
            device: None,
            chunks: Vec::new(),
            written: Vec::new(),
            active: false,
            enabled: policy::STAGING_REUSE_ENABLED,
            budget: RETAINED_BYTES,
            max_chunks: MAX_CHUNKS,
            stats: StagingStats::default(),
            #[cfg(test)]
            hold_ready: false,
        }
    }
}
impl StagingPool {
    #[cfg(all(test, target_os = "windows"))]
    pub fn for_test(enabled: bool, budget: u64, max_chunks: usize) -> Self {
        Self {
            enabled,
            budget,
            max_chunks,
            ..Self::default()
        }
    }

    #[cfg(all(test, target_os = "windows"))]
    pub fn hold_ready_for_test(&mut self, hold: bool) {
        self.hold_ready = hold;
    }

    pub fn begin(&mut self, device: &wgpu::Device) -> Result<(), String> {
        if self.active {
            return Err("staging frame began before submit or clear".into());
        }
        if let Some(bound) = &self.device {
            if bound != device {
                return Err("staging pool belongs to a different device".into());
            }
        } else {
            self.device = Some(device.clone());
        }
        self.stats = StagingStats::default();
        self.written.clear();
        self.collect()?;
        self.active = true;
        Ok(())
    }

    pub fn stats(&self) -> StagingStats {
        StagingStats {
            staging_retained_bytes: self.retained_bytes(),
            staging_pending_buffers: self
                .chunks
                .iter()
                .filter(|chunk| chunk.ownership != Ownership::Ready)
                .count() as u64,
            ..self.stats
        }
    }

    /// Immediately after the one Queue::submit, before validation/readback.
    /// Never overwrite completion: a callback may already have run in submit.
    pub fn submitted(&mut self) {
        for chunk in &mut self.chunks {
            if chunk.ownership == Ownership::Leased {
                chunk.ownership = Ownership::Submitted;
            }
        }
        self.active = false;
        self.written.clear();
    }

    /// The caller first drops abandoned encoders and command buffers. Keep all
    /// pending/retired storage charged until the corresponding token terminates.
    /// This also remains conservative if clear happens before encoder drop.
    pub fn clear(&mut self) {
        for chunk in &mut self.chunks {
            chunk.ownership = match chunk.ownership {
                Ownership::Leased => Ownership::Retired { submitted: false },
                Ownership::Submitted => Ownership::Retired { submitted: true },
                ownership => ownership,
            };
        }
        self.active = false;
        self.written.clear();
    }

    fn retained_bytes(&self) -> u64 {
        self.chunks.iter().map(|chunk| chunk.capacity).sum()
    }

    fn collect(&mut self) -> Result<(), String> {
        let mut failure = false;
        #[cfg(test)]
        let hold_ready = self.hold_ready;
        #[cfg(not(test))]
        let hold_ready = false;
        self.chunks.retain_mut(|chunk| {
            let result = chunk
                .completion
                .as_ref()
                .map(|state| state.load(Ordering::Acquire));
            match reclaim(chunk.ownership, result, hold_ready) {
                Reclaim::Release => false,
                Reclaim::Ready => {
                    chunk.ownership = Ownership::Ready;
                    chunk.completion = None;
                    true
                }
                Reclaim::Failed => {
                    if chunk.ownership != Ownership::Failed {
                        self.stats.staging_map_failures += 1;
                    }
                    chunk.ownership = Ownership::Failed;
                    failure = true;
                    true
                }
                Reclaim::Keep => true,
            }
        });
        if failure {
            Err("staging buffer remap failed or submitted mapping was cancelled".into())
        } else {
            Ok(())
        }
    }

    /// Each group has one route. Track fallback ranges too: queue writes run
    /// before explicit copies, so mixing overlapping ranges would reverse order.
    pub fn upload(
        &mut self,
        queue: &wgpu::Queue,
        encoder: &mut wgpu::CommandEncoder,
        writes: &[UploadSlice<'_>],
    ) -> Result<(), String> {
        if !self.active {
            return Err("staging upload requires begin_frame_with_device".into());
        }
        if writes.len() > 3 {
            return Err("staging upload group exceeds three slices".into());
        }
        let mut ranges = Vec::with_capacity(writes.len());
        for write in writes {
            if write.bytes.is_empty() {
                continue;
            }
            let size = (write.bytes.len() as u64)
                .checked_add(3)
                .map(|n| n & !3)
                .ok_or("staging copy size overflow")?;
            let end = write
                .offset
                .checked_add(size)
                .ok_or("staging destination extent overflow")?;
            if !write.offset.is_multiple_of(wgpu::COPY_BUFFER_ALIGNMENT)
                || end > write.destination.size()
                || !write
                    .destination
                    .usage()
                    .contains(wgpu::BufferUsages::COPY_DST)
            {
                return Err("invalid staging destination alignment, bounds or usage".into());
            }
            let overlaps = |prior: &WrittenRange| {
                prior.buffer == *write.destination && prior.start < end && write.offset < prior.end
            };
            if self.written.iter().any(overlaps) || ranges.iter().any(overlaps) {
                return Err("overlapping staging destination ranges in one frame".into());
            }
            ranges.push(WrittenRange {
                buffer: write.destination.clone(),
                start: write.offset,
                end,
            });
        }
        if ranges.is_empty() {
            return Ok(());
        }
        let device = self.device.as_ref().expect("begin binds a device");
        let lengths: Vec<_> = writes.iter().map(|write| write.bytes.len()).collect();
        let pack = layout::Pack::new(&lengths, device.limits().max_buffer_size)?;
        let selected = if self.enabled {
            pack.as_ref()
                .and_then(|pack| self.reserve(pack.capacity, pack.required_bytes))
        } else {
            None
        };
        // From here an error means an abandoned attempt, never a second route.
        self.written.extend(ranges);
        let Some(index) = selected else {
            self.stats.staging_fallback_arenas += 1;
            for write in writes.iter().filter(|write| !write.bytes.is_empty()) {
                let size = (write.bytes.len() as u64 + 3) & !3;
                let mut view = queue
                    .write_buffer_with(
                        write.destination,
                        write.offset,
                        wgpu::BufferSize::new(size).expect("nonempty write"),
                    )
                    .ok_or("cannot stage frame geometry upload")?;
                view.slice(..write.bytes.len()).copy_from_slice(write.bytes);
                view.slice(write.bytes.len()..).fill(0);
                self.stats.staging_queue_write_calls += 1;
                self.stats.staging_queue_write_bytes += size;
            }
            return Ok(());
        };
        let pack = pack.expect("reserved a valid layout");
        let chunk = &mut self.chunks[index];
        {
            let mut view = chunk
                .buffer
                .get_mapped_range_mut(..)
                .map_err(|error| format!("cannot access staging mapping: {error}"))?;
            for (write, segment) in writes.iter().zip(&pack.segments) {
                if segment.copy_len == 0 {
                    continue;
                }
                let start = segment.source_offset as usize;
                let end = start + segment.logical_len;
                view.slice(start..end).copy_from_slice(write.bytes);
                view.slice(end..start + segment.copy_len as usize).fill(0);
            }
        }
        chunk.buffer.unmap();
        let completion = Arc::new(AtomicU8::new(PENDING));
        chunk.completion = Some(completion.clone());
        for (write, segment) in writes.iter().zip(&pack.segments) {
            if segment.copy_len == 0 {
                continue;
            }
            encoder.copy_buffer_to_buffer(
                &chunk.buffer,
                segment.source_offset,
                write.destination,
                write.offset,
                segment.copy_len,
            );
            self.stats.staging_copy_bytes += segment.copy_len;
        }
        let callback = Completion(completion);
        encoder.map_buffer_on_submit(&chunk.buffer, wgpu::MapMode::Write, .., move |result| {
            callback.finish(result)
        });
        Ok(())
    }

    fn reserve(&mut self, capacity: u64, required: u64) -> Option<usize> {
        if let Some((index, _)) = self
            .chunks
            .iter()
            .enumerate()
            .filter(|(_, chunk)| chunk.ownership == Ownership::Ready && chunk.capacity >= required)
            .min_by_key(|(_, chunk)| chunk.capacity)
        {
            self.chunks[index].ownership = Ownership::Leased;
            self.stats.staging_buffer_reuses += 1;
            return Some(index);
        }
        if capacity > self.budget || self.max_chunks == 0 {
            return None;
        }
        while !layout::can_allocate(
            self.retained_bytes(),
            capacity,
            self.chunks.len(),
            self.budget,
            self.max_chunks,
        ) {
            // Only fully mapped/completed idle chunks may be trimmed. Never
            // replace a live submission or make it disappear from accounting.
            let index = self
                .chunks
                .iter()
                .position(|chunk| chunk.ownership == Ownership::Ready)?;
            self.chunks.remove(index);
        }
        let buffer =
            self.device
                .as_ref()
                .expect("bound device")
                .create_buffer(&wgpu::BufferDescriptor {
                    label: Some("bounded frame staging source"),
                    size: capacity,
                    usage: wgpu::BufferUsages::MAP_WRITE | wgpu::BufferUsages::COPY_SRC,
                    mapped_at_creation: true,
                });
        self.chunks.push(Chunk {
            buffer,
            capacity,
            ownership: Ownership::Leased,
            completion: None,
        });
        self.stats.staging_buffer_allocations += 1;
        self.stats.staging_buffer_allocated_bytes += capacity;
        Some(self.chunks.len() - 1)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn completion_does_not_release_a_still_owned_checkout() {
        assert_eq!(
            reclaim(Ownership::Leased, Some(MAPPED), false),
            Reclaim::Keep
        );
        assert_eq!(
            reclaim(Ownership::Submitted, Some(PENDING), false),
            Reclaim::Keep
        );
        assert_eq!(
            reclaim(Ownership::Submitted, Some(MAPPED), false),
            Reclaim::Ready
        );
        assert_eq!(
            reclaim(Ownership::Submitted, Some(MAPPED), true),
            Reclaim::Keep
        );
    }

    #[test]
    fn cancellation_never_becomes_ready_or_releases_submitted_work() {
        assert_eq!(
            reclaim(
                Ownership::Retired { submitted: false },
                Some(PENDING),
                false
            ),
            Reclaim::Keep
        );
        assert_eq!(
            reclaim(
                Ownership::Retired { submitted: false },
                Some(CANCELLED),
                false
            ),
            Reclaim::Release
        );
        assert_eq!(
            reclaim(
                Ownership::Retired { submitted: true },
                Some(CANCELLED),
                false
            ),
            Reclaim::Failed
        );
        assert_eq!(
            reclaim(Ownership::Submitted, Some(FAILED), false),
            Reclaim::Failed
        );
        assert_eq!(
            reclaim(Ownership::Failed, Some(MAPPED), false),
            Reclaim::Failed
        );
    }

    #[test]
    fn post_submit_clear_waits_for_success_before_releasing_charge() {
        let retired = Ownership::Retired { submitted: true };
        assert_eq!(reclaim(retired, Some(PENDING), false), Reclaim::Keep);
        assert_eq!(reclaim(retired, Some(MAPPED), false), Reclaim::Release);
        assert_eq!(reclaim(retired, Some(FAILED), false), Reclaim::Failed);
    }

    #[test]
    fn dropping_unsubmitted_callback_marks_cancelled() {
        let state = Arc::new(AtomicU8::new(PENDING));
        drop(Completion(state.clone()));
        assert_eq!(state.load(Ordering::Acquire), CANCELLED);
    }

    #[test]
    fn callback_completion_cannot_be_overwritten_by_drop() {
        for (success, expected) in [(true, MAPPED), (false, FAILED)] {
            let state = Arc::new(AtomicU8::new(PENDING));
            let completion = Completion(state.clone());
            completion.record(success);
            drop(completion);
            assert_eq!(state.load(Ordering::Acquire), expected);
        }
    }

    #[test]
    fn late_checkout_callback_has_no_access_to_the_next_generation() {
        let old = Arc::new(AtomicU8::new(PENDING));
        let new = Arc::new(AtomicU8::new(PENDING));
        let completion = Completion(old.clone());
        std::thread::spawn(move || completion.record(true))
            .join()
            .unwrap();
        assert_eq!(old.load(Ordering::Acquire), MAPPED);
        assert_eq!(new.load(Ordering::Acquire), PENDING);
        assert!(!Arc::ptr_eq(&old, &new));
    }

    #[test]
    fn production_retention_is_an_explicit_additional_cache_budget() {
        assert_eq!(MAX_CHUNKS, 8);
        assert_eq!(RETAINED_BYTES, 67_108_864);
        assert!(layout::can_allocate(
            56 * 1024 * 1024,
            8 * 1024 * 1024,
            7,
            RETAINED_BYTES,
            MAX_CHUNKS
        ));
        assert!(!layout::can_allocate(
            RETAINED_BYTES,
            4,
            8,
            RETAINED_BYTES,
            MAX_CHUNKS
        ));
    }
}
