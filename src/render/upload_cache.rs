//! Bounded destination buffers with an additive bounded staging-source seam.
//!
//! Each slot is written once per frame, after the preceding frame's submit.
//! Legacy queue writes and explicit staged copies follow older submissions;
//! no mapped destination, wait, poll, extra submit, or explicit destroy is used.
use super::{
    arena::{FrameArena, MATRIX_BYTES},
    mesh::{FrameGeometry, Pipelines},
};
use crate::frame_performance_session::{add_encode_counter, EncodeCounter};

#[path = "upload_staging.rs"]
mod staging;
pub(super) use staging::StagingStats;

#[cfg(all(test, target_os = "windows"))]
#[path = "upload_staging_tests.rs"]
mod staging_tests;

pub(super) const MAX_SLOTS: usize = 8;
pub(super) const RETAINED_BYTES: u64 = 64 * 1024 * 1024;

struct Slot {
    buffers: [wgpu::Buffer; 3],
    capacities: [u64; 3],
    transform: wgpu::BindGroup,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub(super) struct UploadStats {
    pub allocations: u64,
    pub reuses: u64,
    pub allocated_bytes: u64,
    pub bindings: u64,
    pub uncached_arenas: u64,
}

pub(super) struct UploadCache {
    slots: [Option<Slot>; MAX_SLOTS],
    enabled: bool,
    budget: u64,
    active: bool,
    used: u8,
    pub stats: UploadStats,
    staging: staging::StagingPool,
}
impl Default for UploadCache {
    fn default() -> Self {
        Self {
            slots: std::array::from_fn(|_| None),
            enabled: crate::frame_upload_policy::REUSE_ENABLED,
            budget: RETAINED_BYTES,
            active: false,
            used: 0,
            stats: UploadStats::default(),
            staging: staging::StagingPool::default(),
        }
    }
}
impl UploadCache {
    #[cfg(all(test, target_os = "windows"))]
    pub fn for_test(enabled: bool, budget: u64) -> Self {
        Self {
            enabled,
            budget,
            ..Self::default()
        }
    }

    #[cfg(all(test, target_os = "windows"))]
    pub fn for_staging_test(
        enabled: bool,
        destination_budget: u64,
        staging_budget: u64,
        staging_slots: usize,
    ) -> Self {
        Self {
            enabled: true,
            budget: destination_budget,
            staging: staging::StagingPool::for_test(enabled, staging_budget, staging_slots),
            ..Self::default()
        }
    }

    #[cfg(all(test, target_os = "windows"))]
    pub fn hold_ready_for_test(&mut self, hold: bool) {
        self.staging.hold_ready_for_test(hold);
    }

    /// Additive integration seam; the legacy caller remains queue-write-only.
    #[allow(dead_code)]
    pub fn begin_frame_with_device(&mut self, device: &wgpu::Device) -> Result<(), String> {
        self.begin_frame()?;
        self.staging.begin(device)
    }

    /// Aella's combined v3 instrumentation reads these without changing the
    /// historical destination-allocation counters.
    #[allow(dead_code)]
    pub fn staging_stats(&self) -> StagingStats {
        self.staging.stats()
    }

    #[allow(dead_code)]
    pub fn staging_policy_identity() -> &'static str {
        staging::policy::identity()
    }

    pub fn begin_frame(&mut self) -> Result<(), String> {
        if self.active {
            self.clear();
            return Err("frame upload began before the preceding submit".into());
        }
        self.active = true;
        self.used = 0;
        self.stats = UploadStats::default();
        Ok(())
    }

    /// Call only after Queue::submit. Idle slots are explicitly trimmed here.
    pub fn submitted(&mut self) {
        self.staging.submitted();
        for (index, slot) in self.slots.iter_mut().enumerate() {
            if self.used & (1 << index) == 0 {
                *slot = None;
            }
        }
        self.active = false;
    }

    /// Drop handles, never destroy buffers that older submissions may reference.
    /// Pending writes after a failed encode retain their old destinations inside
    /// wgpu; fresh slots cannot alias those abandoned destinations next frame.
    pub fn clear(&mut self) {
        self.staging.clear();
        self.slots = std::array::from_fn(|_| None);
        self.active = false;
        self.used = 0;
    }

    pub fn retained_bytes(&self) -> u64 {
        self.slots
            .iter()
            .flatten()
            .map(|slot| slot.capacities.iter().sum::<u64>())
            .sum()
    }

    pub fn upload(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        pipelines: &Pipelines,
        index: usize,
        arena: &FrameArena,
    ) -> Result<Option<FrameGeometry>, String> {
        self.upload_inner(device, queue, pipelines, index, arena, None)
    }

    /// Copies are recorded before the caller's timestamp start/draws. The caller
    /// keeps its single submit and calls submitted immediately after it returns.
    #[allow(dead_code, clippy::too_many_arguments)]
    pub fn upload_with_encoder(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        pipelines: &Pipelines,
        index: usize,
        arena: &FrameArena,
        encoder: &mut wgpu::CommandEncoder,
    ) -> Result<Option<FrameGeometry>, String> {
        self.upload_inner(device, queue, pipelines, index, arena, Some(encoder))
    }

    #[allow(clippy::too_many_arguments)]
    fn upload_inner(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        pipelines: &Pipelines,
        index: usize,
        arena: &FrameArena,
        encoder: Option<&mut wgpu::CommandEncoder>,
    ) -> Result<Option<FrameGeometry>, String> {
        if !self.active {
            return Err("frame upload requires begin_frame".into());
        }
        let Some(contents) = arena.buffer_contents() else {
            return Ok(None);
        };
        let mut sizes = [0; 3];
        for i in 0..3 {
            sizes[i] = padded_size(contents[i].len() as u64).ok_or("frame upload size overflow")?;
        }
        let old = self.slots.get(index).and_then(Option::as_ref);
        let previous = old.map_or([0; 3], |slot| slot.capacities);
        let capacities = capacity_plan(previous, sizes, device.limits().max_buffer_size);
        let cacheable = self.enabled
            && index < MAX_SLOTS
            && capacities.is_some_and(|next| {
                fits_budget(self.retained_bytes(), previous, next, self.budget)
            });
        if !cacheable {
            self.record(UploadStats {
                allocations: 3,
                allocated_bytes: sizes.iter().sum(),
                bindings: 1,
                uncached_arenas: 1,
                ..UploadStats::default()
            });
            return Ok(pipelines.upload_geometry(device, arena));
        }
        if self.used & (1 << index) != 0 {
            return Err("frame upload slot written twice before submit".into());
        }
        self.used |= 1 << index;
        let capacities = capacities.expect("cacheable capacity plan");
        let old = self.slots[index].take();
        let usages = [
            wgpu::BufferUsages::VERTEX,
            wgpu::BufferUsages::INDEX,
            wgpu::BufferUsages::UNIFORM,
        ];
        let labels = [
            "cached frame vertices",
            "cached frame indices",
            "cached frame transforms",
        ];
        let mut stats = UploadStats::default();
        let buffers = std::array::from_fn(|i| {
            if let Some(slot) = old
                .as_ref()
                .filter(|slot| slot.capacities[i] == capacities[i])
            {
                stats.reuses += 1;
                slot.buffers[i].clone()
            } else {
                stats.allocations += 1;
                stats.allocated_bytes += capacities[i];
                device.create_buffer(&wgpu::BufferDescriptor {
                    label: Some(labels[i]),
                    size: capacities[i],
                    usage: usages[i] | wgpu::BufferUsages::COPY_DST,
                    mapped_at_creation: false,
                })
            }
        });
        let transform = if let Some(slot) = old
            .as_ref()
            .filter(|slot| slot.capacities[2] == capacities[2])
        {
            slot.transform.clone()
        } else {
            stats.bindings = 1;
            device.create_bind_group(&wgpu::BindGroupDescriptor {
                label: Some("cached frame transform slots"),
                layout: &pipelines.transform_layout,
                entries: &[wgpu::BindGroupEntry {
                    binding: 0,
                    resource: wgpu::BindingResource::Buffer(wgpu::BufferBinding {
                        buffer: &buffers[2],
                        offset: 0,
                        size: wgpu::BufferSize::new(MATRIX_BYTES),
                    }),
                }],
            })
        };
        self.record(stats);
        self.slots[index] = Some(Slot {
            buffers,
            capacities,
            transform,
        });
        let slot = self.slots[index].as_ref().expect("inserted upload slot");
        if let Some(encoder) = encoder {
            let writes = std::array::from_fn::<_, 3, _>(|i| staging::UploadSlice {
                destination: &slot.buffers[i],
                offset: 0,
                bytes: contents[i],
            });
            self.staging.upload(queue, encoder, &writes)?;
        } else {
            // Preflight all lengths/capacities before the first write. write_buffer_with
            // lets odd-u16 index payloads receive zero padding without a CPU scratch Vec.
            for i in 0..3 {
                let mut staging = queue
                    .write_buffer_with(
                        &slot.buffers[i],
                        0,
                        wgpu::BufferSize::new(sizes[i]).expect("nonempty arena payload"),
                    )
                    .ok_or("cannot stage frame geometry upload")?;
                staging
                    .slice(..contents[i].len())
                    .copy_from_slice(contents[i]);
                staging.slice(contents[i].len()..).fill(0);
            }
        }
        Ok(Some(FrameGeometry {
            vertices: slot.buffers[0].clone(),
            indices: slot.buffers[1].clone(),
            transform: slot.transform.clone(),
        }))
    }

    fn record(&mut self, stats: UploadStats) {
        self.stats.allocations += stats.allocations;
        self.stats.reuses += stats.reuses;
        self.stats.allocated_bytes += stats.allocated_bytes;
        self.stats.bindings += stats.bindings;
        self.stats.uncached_arenas += stats.uncached_arenas;
        for (counter, value) in [
            (EncodeCounter::GpuBufferAllocations, stats.allocations),
            (EncodeCounter::GpuBufferReuses, stats.reuses),
            (
                EncodeCounter::GpuBufferAllocatedBytes,
                stats.allocated_bytes,
            ),
            (EncodeCounter::TransformBindingAllocations, stats.bindings),
            (EncodeCounter::UncachedUploadArenas, stats.uncached_arenas),
        ] {
            add_encode_counter(counter, value);
        }
    }
}

fn padded_size(size: u64) -> Option<u64> {
    size.checked_add(3).map(|value| value & !3)
}

fn capacity_plan(previous: [u64; 3], sizes: [u64; 3], limit: u64) -> Option<[u64; 3]> {
    let mut result = previous;
    for i in 0..3 {
        if sizes[i] == 0 || sizes[i] > limit {
            return None;
        }
        if sizes[i] > previous[i] {
            result[i] = sizes[i]
                .checked_next_power_of_two()
                .filter(|&value| value <= limit)
                .unwrap_or(sizes[i]);
        }
    }
    Some(result)
}

fn fits_budget(retained: u64, previous: [u64; 3], next: [u64; 3], budget: u64) -> bool {
    previous
        .into_iter()
        .try_fold(retained, u64::checked_sub)
        .and_then(|bytes| next.into_iter().try_fold(bytes, u64::checked_add))
        .is_some_and(|bytes| bytes <= budget)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn upload_cache_capacity_and_padding_are_checked() {
        assert_eq!(padded_size(6), Some(8));
        assert_eq!(padded_size(u64::MAX), None);
        assert_eq!(
            capacity_plan([128, 8, 64], [120, 6, 64], 1024),
            Some([128, 8, 64])
        );
        assert_eq!(
            capacity_plan([128, 8, 64], [132, 8, 320], 1024),
            Some([256, 8, 512])
        );
        assert_eq!(
            capacity_plan([128, 8, 64], [132, 8, 64], 1024),
            Some([256, 8, 64])
        );
        assert_eq!(capacity_plan([0; 3], [120, 8, 64], 120), Some([120, 8, 64]));
        assert_eq!(capacity_plan([0; 3], [0, 8, 64], 1024), None);
        assert_eq!(capacity_plan([0; 3], [1025, 8, 64], 1024), None);
    }
    #[test]
    fn upload_cache_budget_is_retained_storage_not_frame_acceptance() {
        assert!(fits_budget(200, [128, 8, 64], [256, 8, 64], 328));
        assert!(!fits_budget(200, [128, 8, 64], [256, 8, 64], 327));
        assert!(!fits_budget(0, [1, 0, 0], [0; 3], 100));
        assert!(!fits_budget(u64::MAX, [0; 3], [1, 0, 0], u64::MAX));
        assert_eq!(MAX_SLOTS, 8);
        assert_eq!(RETAINED_BYTES, 67_108_864);
    }
    #[test]
    fn upload_cache_rejects_unsubmitted_reentry_and_resets() {
        let mut cache = UploadCache::default();
        cache.begin_frame().unwrap();
        assert!(cache.begin_frame().is_err());
        assert_eq!(cache.retained_bytes(), 0);
        cache.begin_frame().unwrap();
        cache.submitted();
        cache.begin_frame().unwrap();
    }
}
