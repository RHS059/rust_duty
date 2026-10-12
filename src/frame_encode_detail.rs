//! Capture-only CPU encode diagnostics. These spans nest inside EncodeSubmit;
//! they never alter the primary frame report or the CPU-substages v1 contract.
use crate::frame_cpu_substages::CpuSubstages;
use crate::frame_performance::CpuWallSpan;
use serde_json::{json, Value};
use std::fs::OpenOptions;
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};

#[path = "frame_resident_policy.rs"]
pub mod resident_policy;
#[path = "frame_upload_policy.rs"]
pub mod upload_policy;

pub const SCHEMA: &str = "rust_duty_cpu_encode_detail_v3";
pub const MEASUREMENT: &str = "cpu_wall_clock_nested_encode_phase_ns";
pub const INTERPRETATION: &str = "CPU call durations nested inside encode_submit and renderer_submit, not GPU time. Parent and child durations must not be added. Missing or incomplete phases are unavailable; counters on incomplete rows are observed partial values, not complete frame totals.";
pub const MAX_SPANS: usize = 5;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EncodePhase {
    FramePlan,
    GeometryUpload,
    CommandEncoding,
    EncoderFinish,
    QueueSubmit,
}
impl EncodePhase {
    pub const ALL: [Self; MAX_SPANS] = [
        Self::FramePlan,
        Self::GeometryUpload,
        Self::CommandEncoding,
        Self::EncoderFinish,
        Self::QueueSubmit,
    ];
    pub fn label(self) -> &'static str {
        match self {
            Self::FramePlan => "frame_plan",
            Self::GeometryUpload => "geometry_upload",
            Self::CommandEncoding => "command_encoding",
            Self::EncoderFinish => "encoder_finish",
            Self::QueueSubmit => "queue_submit",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EncodeCounter {
    PreparedDraws,
    TextCharacters,
    UploadArenas,
    VertexBytes,
    IndexBytes,
    UniformBytes,
    DrawCalls,
    RenderPasses,
    TextureCacheMisses,
    PipelineCacheMisses,
    /// Destination buffers created during this attempt, including fallback.
    GpuBufferAllocations,
    /// Existing destination buffers reused by this attempt.
    GpuBufferReuses,
    /// Sum of capacities of newly created destination buffers, not retained bytes.
    GpuBufferAllocatedBytes,
    /// Transform bind groups created during this attempt, including fallback.
    TransformBindingAllocations,
    /// Nonempty arenas uploaded through an uncached path during this attempt.
    UncachedUploadArenas,
    ResidentDraws,
    ResidentRigidDraws,
    ResidentSkinnedDraws,
    ResidentVertexBytesUploaded,
    ResidentIndexBytesUploaded,
    ResidentUniformBytesUploaded,
    ResidentCacheHits,
    ResidentCacheMisses,
    ResidentTransientMeshes,
    ResidentBufferAllocations,
    ResidentBindingAllocations,
}
impl EncodeCounter {
    const ALL: [Self; 26] = [
        Self::PreparedDraws,
        Self::TextCharacters,
        Self::UploadArenas,
        Self::VertexBytes,
        Self::IndexBytes,
        Self::UniformBytes,
        Self::DrawCalls,
        Self::RenderPasses,
        Self::TextureCacheMisses,
        Self::PipelineCacheMisses,
        Self::GpuBufferAllocations,
        Self::GpuBufferReuses,
        Self::GpuBufferAllocatedBytes,
        Self::TransformBindingAllocations,
        Self::UncachedUploadArenas,
        Self::ResidentDraws,
        Self::ResidentRigidDraws,
        Self::ResidentSkinnedDraws,
        Self::ResidentVertexBytesUploaded,
        Self::ResidentIndexBytesUploaded,
        Self::ResidentUniformBytesUploaded,
        Self::ResidentCacheHits,
        Self::ResidentCacheMisses,
        Self::ResidentTransientMeshes,
        Self::ResidentBufferAllocations,
        Self::ResidentBindingAllocations,
    ];
    pub fn label(self) -> &'static str {
        match self {
            Self::PreparedDraws => "prepared_draws",
            Self::TextCharacters => "text_characters",
            Self::UploadArenas => "upload_arenas",
            Self::VertexBytes => "vertex_bytes",
            Self::IndexBytes => "index_bytes",
            Self::UniformBytes => "uniform_bytes",
            Self::DrawCalls => "draw_calls",
            Self::RenderPasses => "render_passes",
            Self::TextureCacheMisses => "texture_cache_misses",
            Self::PipelineCacheMisses => "pipeline_cache_misses",
            Self::GpuBufferAllocations => "gpu_buffer_allocations",
            Self::GpuBufferReuses => "gpu_buffer_reuses",
            Self::GpuBufferAllocatedBytes => "gpu_buffer_allocated_bytes",
            Self::TransformBindingAllocations => "transform_binding_allocations",
            Self::UncachedUploadArenas => "uncached_upload_arenas",
            Self::ResidentDraws => "resident_draws",
            Self::ResidentRigidDraws => "resident_rigid_draws",
            Self::ResidentSkinnedDraws => "resident_skinned_draws",
            Self::ResidentVertexBytesUploaded => "resident_vertex_bytes_uploaded",
            Self::ResidentIndexBytesUploaded => "resident_index_bytes_uploaded",
            Self::ResidentUniformBytesUploaded => "resident_uniform_bytes_uploaded",
            Self::ResidentCacheHits => "resident_cache_hits",
            Self::ResidentCacheMisses => "resident_cache_misses",
            Self::ResidentTransientMeshes => "resident_transient_meshes",
            Self::ResidentBufferAllocations => "resident_buffer_allocations",
            Self::ResidentBindingAllocations => "resident_binding_allocations",
        }
    }
}

#[derive(Clone, Copy, Debug)]
struct EncodeSpan {
    phase: EncodePhase,
    started_at_ns: u64,
    ended_at_ns: u64,
}

/// All per-call state is fixed storage. Counter updates never read a clock.
#[derive(Clone, Debug, Default)]
pub(crate) struct CpuEncodeDetails {
    spans: [Option<EncodeSpan>; MAX_SPANS],
    count: usize,
    open: Option<(EncodePhase, u64)>,
    parent_start: Option<u64>,
    parent_end: Option<u64>,
    counters: [u64; EncodeCounter::ALL.len()],
    observed: bool,
    first_phase_started: bool,
    success: bool,
    error: Option<&'static str>,
}
impl CpuEncodeDetails {
    pub fn invalidate(&mut self, error: &'static str) {
        self.error.get_or_insert(error);
    }

    pub fn begin_parent(&mut self, at_ns: u64) {
        if self.parent_start.is_some() {
            self.invalidate("overlapping_or_repeated_encode_parent");
            return;
        }
        self.parent_start = Some(at_ns);
    }

    pub fn end_parent(&mut self, at_ns: u64) {
        if self.parent_start.is_none_or(|start| at_ns < start) || self.parent_end.is_some() {
            self.invalidate("mismatched_or_non_monotonic_encode_parent");
            return;
        }
        self.parent_end = Some(at_ns);
        if self.spans[..self.count]
            .iter()
            .flatten()
            .any(|span| span.ended_at_ns > at_ns)
        {
            self.invalidate("encode_phase_outside_parent");
        }
    }

    fn parent_is_open(&self) -> bool {
        self.parent_start.is_some() && self.parent_end.is_none()
    }

    pub fn begin(&mut self, phase: EncodePhase, at_ns: u64) {
        self.observed = true;
        if self.error.is_some() {
            return;
        }
        if !self.parent_is_open() || self.success {
            self.invalidate("encode_parent_unavailable_or_already_complete");
            return;
        }
        if self.open.is_some() || self.count == MAX_SPANS {
            self.invalidate("overlapping_or_excess_encode_phase");
            return;
        }
        if self.previous_end().is_some_and(|end| at_ns < end)
            || self.parent_start.is_some_and(|start| at_ns < start)
        {
            self.invalidate("non_monotonic_encode_phase");
            return;
        }
        if EncodePhase::ALL[self.count] != phase {
            self.invalidate("unexpected_encode_phase_order");
            return;
        }
        if phase == EncodePhase::FramePlan {
            self.first_phase_started = true;
        }
        self.open = Some((phase, at_ns));
    }

    fn previous_end(&self) -> Option<u64> {
        self.count
            .checked_sub(1)
            .and_then(|index| self.spans[index])
            .map(|span| span.ended_at_ns)
    }

    pub fn end(&mut self, phase: EncodePhase, at_ns: u64) {
        self.observed = true;
        if self.error.is_some() {
            return;
        }
        let Some((opened, started_at_ns)) = self.open.take() else {
            self.invalidate("unopened_encode_phase");
            return;
        };
        if !self.parent_is_open() || opened != phase || at_ns < started_at_ns {
            self.invalidate("mismatched_or_non_monotonic_encode_phase");
            return;
        }
        self.spans[self.count] = Some(EncodeSpan {
            phase,
            started_at_ns,
            ended_at_ns: at_ns,
        });
        self.count += 1;
    }

    pub fn is_active(&self) -> bool {
        self.parent_is_open() && !self.success && self.first_phase_started
    }

    pub fn add_counter(&mut self, counter: EncodeCounter, amount: u64) {
        // Existing renderer helpers can run outside a captured encode attempt.
        // Do not count their work or mark diagnostics as observed before phase 1.
        if !self.is_active() {
            return;
        }
        // Keep observed partial counts even if timing diagnostics failed. On
        // overflow retain the previous value, never wrap or invent saturation.
        let value = &mut self.counters[counter as usize];
        match value.checked_add(amount) {
            Some(total) => *value = total,
            None => self.invalidate("encode_counter_overflow"),
        }
    }

    pub fn complete(&mut self) {
        self.observed = true;
        if self.error.is_some() {
            return;
        }
        if self.success || !self.parent_is_open() || self.open.is_some() || self.count != MAX_SPANS
        {
            self.invalidate("encode_success_without_all_phases");
            return;
        }
        self.success = true;
    }

    pub fn validate_substages(&mut self, substages: &CpuSubstages) {
        if !self.observed {
            return;
        }
        if !substages.is_complete() {
            self.invalidate("encode_ancestor_incomplete");
        }
        let Some((start, end)) = substages.retained_encode_submit() else {
            self.invalidate("encode_parent_span_unavailable");
            return;
        };
        self.retain_inside(start, end);
    }

    fn retain_inside(&mut self, lower: u64, upper: u64) {
        // Preserve only valid paired observations. Do not invent clipped
        // durations or shift later phases into a missing prefix position.
        if let Some(index) = self.spans[..self.count].iter().position(|span| {
            span.is_some_and(|span| span.started_at_ns < lower || span.ended_at_ns > upper)
        }) {
            self.spans[index..].fill(None);
            self.count = index;
            self.invalidate("encode_phase_outside_parent");
        }
    }

    pub fn validate_bounds(
        &mut self,
        frame_start: u64,
        frame_end: u64,
        renderer_submit: Option<CpuWallSpan>,
    ) {
        if !self.observed {
            return;
        }
        let mut lower = frame_start;
        let mut upper = frame_end;
        if let Some(renderer) = renderer_submit {
            lower = lower.max(renderer.started_at_ns);
            upper = upper.min(renderer.ended_at_ns);
        } else {
            self.invalidate("encode_parent_span_unavailable");
        }
        if let Some(start) = self.parent_start {
            lower = lower.max(start);
        } else {
            self.invalidate("encode_parent_span_unavailable");
        }
        if let Some(end) = self.parent_end {
            upper = upper.min(end);
        } else {
            self.invalidate("encode_parent_span_unavailable");
        }
        self.retain_inside(lower, upper);
        if let (Some(start), Some(end), Some(renderer)) =
            (self.parent_start, self.parent_end, renderer_submit)
        {
            if renderer.started_at_ns < frame_start
                || renderer.ended_at_ns > frame_end
                || start < renderer.started_at_ns
                || end > renderer.ended_at_ns
                || end < start
            {
                self.invalidate("encode_phase_outside_parent");
            }
        }
    }

    fn to_json(&self) -> Value {
        let error = self.error.or_else(|| {
            if !self.observed {
                Some("encode_not_observed")
            } else if self.open.is_some() {
                Some("unterminated_encode_phase")
            } else if self.count != MAX_SPANS {
                Some("encode_incomplete")
            } else if !self.success {
                Some("encode_success_not_reported")
            } else if self.parent_end.is_none() {
                Some("encode_parent_span_unavailable")
            } else {
                None
            }
        });
        let spans: Vec<_> = self.spans[..self.count]
            .iter()
            .flatten()
            .map(|span| {
                json!({"stage":span.phase.label(), "started_at_ns":span.started_at_ns,
                    "ended_at_ns":span.ended_at_ns,
                    "duration_ns":span.ended_at_ns - span.started_at_ns})
            })
            .collect();
        let counters: serde_json::Map<String, Value> = EncodeCounter::ALL
            .into_iter()
            .map(|counter| {
                (
                    counter.label().into(),
                    json!(self.counters[counter as usize]),
                )
            })
            .collect();
        json!({"state":if error.is_some() { "incomplete" } else { "complete" },
            "error":error,"spans":spans,"counters":counters})
    }
}

/// Capture allocation is deferred until the first CPU-frame attempt. Rows are
/// retained in the same order as the primary CPU samples and joined only after
/// primary export, keeping the historical report completely unchanged.
pub(crate) struct CpuEncodeCapture {
    rows: Vec<CpuEncodeDetails>,
    max_records: usize,
    attempted: bool,
    allocation_failed: bool,
}
impl CpuEncodeCapture {
    pub fn new(max_records: usize) -> Self {
        Self {
            rows: Vec::new(),
            max_records,
            attempted: false,
            allocation_failed: false,
        }
    }

    pub fn begin_attempt(&mut self) {
        self.attempted = true;
        if self.rows.capacity() == 0 && !self.allocation_failed {
            self.allocation_failed = self.rows.try_reserve_exact(self.max_records).is_err();
        }
    }

    pub fn retain(&mut self, details: CpuEncodeDetails) {
        if !self.allocation_failed && self.rows.len() < self.max_records {
            self.rows.push(details);
        }
    }

    pub fn write_new(&self, frame_path: &Path) -> Result<Option<PathBuf>, String> {
        if !self.attempted {
            return Ok(None);
        }
        // The persisted primary report supplies exact status and retained CPU
        // record indices. No additional frame/session clock calls are needed.
        let frame_bytes = std::fs::read(frame_path).map_err(|error| error.to_string())?;
        let primary: Value =
            serde_json::from_slice(&frame_bytes).map_err(|error| error.to_string())?;
        // Match the optional CPU-substage exporter: an attempted frame without
        // a retained CPU terminal record cannot supply an analyzable parent row.
        let Some(cpu_samples) = primary["cpu_frame_stages"]["samples"]
            .as_array()
            .filter(|samples| !samples.is_empty())
        else {
            return Ok(None);
        };
        if cpu_samples.len() > self.max_records {
            return Err("primary CPU samples exceed encode capture bound".into());
        }
        let digest = rust_duty_launcher::bytes_hash(&frame_bytes);
        let mut samples = Vec::new();
        for (index, sample) in cpu_samples.iter().enumerate() {
            let mut absent = CpuEncodeDetails::default();
            let details = if self.allocation_failed {
                absent.invalidate("encode_capture_allocation_failed");
                &absent
            } else if self.rows.len() != cpu_samples.len() {
                absent.invalidate("encode_capture_sample_mismatch");
                &absent
            } else {
                &self.rows[index]
            };
            samples.push(json!({"record_index":sample["record_index"],
                "details":details.to_json()}));
        }
        let value = json!({"schema":SCHEMA,"measurement":MEASUREMENT,
            "upload_policy":upload_policy::identity(), "resident_policy":resident_policy::identity(),
            "interpretation":INTERPRETATION,"frame_report_sha256":digest,
            "frame_status":primary["status"],"samples":samples});
        let path = frame_path.with_extension("cpu-encode-detail.json");
        let file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&path)
            .map_err(|error| format!("create {}: {error}", path.display()))?;
        let mut writer = BufWriter::new(file);
        let write = (|| -> Result<(), String> {
            serde_json::to_writer_pretty(&mut writer, &value).map_err(|error| error.to_string())?;
            writer.flush().map_err(|error| error.to_string())?;
            writer
                .get_ref()
                .sync_all()
                .map_err(|error| error.to_string())?;
            Ok(())
        })();
        write
            .map_err(|error| format!("write {}: {error}; partial file possible", path.display()))?;
        Ok(Some(path))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn phases(details: &mut CpuEncodeDetails) {
        for (index, phase) in EncodePhase::ALL.into_iter().enumerate() {
            details.begin(phase, 10 + index as u64 * 10);
            details.end(phase, 15 + index as u64 * 10);
        }
    }
    fn finish(details: &mut CpuEncodeDetails) {
        details.end_parent(60);
        details.validate_bounds(
            0,
            100,
            Some(CpuWallSpan {
                started_at_ns: 5,
                ended_at_ns: 80,
            }),
        );
    }
    #[test]
    fn complete_requires_all_five_phases_and_explicit_success() {
        let mut details = CpuEncodeDetails::default();
        details.begin_parent(8);
        phases(&mut details);
        let mut missing_success = details.clone();
        finish(&mut missing_success);
        assert_eq!(
            missing_success.to_json()["error"],
            "encode_success_not_reported"
        );
        details.complete();
        finish(&mut details);
        let value = details.to_json();
        assert_eq!(value["state"], "complete");
        assert!(value["error"].is_null());
        assert_eq!(value["spans"].as_array().unwrap().len(), MAX_SPANS);
        assert_eq!(value["spans"][4]["stage"], "queue_submit");
        assert_eq!(value["spans"][4]["duration_ns"], 5);
    }
    #[test]
    fn v3_counters_are_exact_fixed_storage_per_attempt_sums() {
        let names = [
            "prepared_draws",
            "text_characters",
            "upload_arenas",
            "vertex_bytes",
            "index_bytes",
            "uniform_bytes",
            "draw_calls",
            "render_passes",
            "texture_cache_misses",
            "pipeline_cache_misses",
            "gpu_buffer_allocations",
            "gpu_buffer_reuses",
            "gpu_buffer_allocated_bytes",
            "transform_binding_allocations",
            "uncached_upload_arenas",
            "resident_draws",
            "resident_rigid_draws",
            "resident_skinned_draws",
            "resident_vertex_bytes_uploaded",
            "resident_index_bytes_uploaded",
            "resident_uniform_bytes_uploaded",
            "resident_cache_hits",
            "resident_cache_misses",
            "resident_transient_meshes",
            "resident_buffer_allocations",
            "resident_binding_allocations",
        ];
        let mut details = CpuEncodeDetails::default();
        assert_eq!(details.counters.len(), names.len());
        for counter in EncodeCounter::ALL {
            details.add_counter(counter, 99);
        }
        details.begin_parent(8);
        details.begin(EncodePhase::FramePlan, 10);
        for (index, counter) in EncodeCounter::ALL.into_iter().enumerate() {
            assert_eq!(counter.label(), names[index]);
            details.add_counter(counter, index as u64 + 1);
            details.add_counter(counter, 2);
        }
        details.end(EncodePhase::FramePlan, 15);
        for (index, phase) in EncodePhase::ALL.into_iter().enumerate().skip(1) {
            details.begin(phase, 10 + index as u64 * 10);
            details.end(phase, 15 + index as u64 * 10);
        }
        details.complete();
        for counter in EncodeCounter::ALL {
            details.add_counter(counter, 99);
        }
        finish(&mut details);
        let value = details.to_json();
        assert_eq!(value["state"], "complete");
        let counters = value["counters"].as_object().unwrap();
        assert_eq!(counters.len(), names.len());
        let next_attempt = CpuEncodeDetails::default().to_json();
        for (index, name) in names.into_iter().enumerate() {
            assert_eq!(counters[name], index as u64 + 3);
            assert_eq!(next_attempt["counters"][name], 0);
        }
    }
    #[test]
    fn every_counter_preserves_observed_partial_value_on_overflow() {
        for counter in EncodeCounter::ALL {
            let mut details = CpuEncodeDetails::default();
            details.begin_parent(8);
            details.begin(EncodePhase::FramePlan, 10);
            details.add_counter(counter, u64::MAX);
            details.add_counter(counter, 1);
            details.complete();
            finish(&mut details);
            let value = details.to_json();
            assert_eq!(value["state"], "incomplete");
            assert_eq!(value["error"], "encode_counter_overflow");
            assert_eq!(value["counters"][counter.label()], u64::MAX);
            assert_eq!(
                value["counters"].as_object().unwrap().len(),
                EncodeCounter::ALL.len()
            );
        }
    }
    #[test]
    fn writer_emits_v3_with_explicit_upload_and_resident_policies() {
        let directory = std::env::temp_dir().join(format!(
            "rust-duty-encode-v2-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&directory).unwrap();
        let frame_path = directory.join("frames.json");
        let primary = json!({"status":{"state":"complete","error":null},
            "cpu_frame_stages":{"samples":[{"record_index":1}]}});
        let bytes = serde_json::to_vec(&primary).unwrap();
        std::fs::write(&frame_path, &bytes).unwrap();
        let mut capture = CpuEncodeCapture::new(1);
        capture.begin_attempt();
        capture.retain(CpuEncodeDetails::default());
        let output = capture.write_new(&frame_path).unwrap().unwrap();
        let value: Value = serde_json::from_slice(&std::fs::read(&output).unwrap()).unwrap();
        assert_eq!(value["schema"], "rust_duty_cpu_encode_detail_v3");
        assert_eq!(value["upload_policy"], upload_policy::identity());
        assert_eq!(value["resident_policy"], resident_policy::identity());
        assert_eq!(value.as_object().unwrap().len(), 8);
        assert_eq!(
            value["frame_report_sha256"],
            rust_duty_launcher::bytes_hash(&bytes)
        );
        assert_eq!(value["samples"][0]["record_index"], 1);
        assert_eq!(value["samples"][0]["details"]["state"], "incomplete");
        assert_eq!(
            value["samples"][0]["details"]["counters"]
                .as_object()
                .unwrap()
                .len(),
            EncodeCounter::ALL.len()
        );
        assert!(capture.write_new(&frame_path).is_err());
        std::fs::remove_dir_all(directory).unwrap();
    }
    #[test]
    fn absent_interrupted_and_partial_rows_are_explicitly_incomplete() {
        let mut details = CpuEncodeDetails::default();
        assert_eq!(details.to_json()["error"], "encode_not_observed");
        details.begin_parent(5);
        details.begin(EncodePhase::FramePlan, 10);
        details.add_counter(EncodeCounter::TextCharacters, 3);
        assert_eq!(details.to_json()["error"], "unterminated_encode_phase");
        assert_eq!(details.to_json()["counters"]["text_characters"], 3);
        assert_eq!(details.to_json()["spans"].as_array().unwrap().len(), 0);
        details.end(EncodePhase::FramePlan, 15);
        finish(&mut details);
        assert_eq!(details.to_json()["error"], "encode_incomplete");
    }
    #[test]
    fn errors_never_turn_into_success_or_wrap_counters() {
        for kind in 0..7 {
            let mut details = CpuEncodeDetails::default();
            details.begin_parent(8);
            details.begin(EncodePhase::FramePlan, 10);
            match kind {
                0 => details.begin(EncodePhase::GeometryUpload, 11),
                1 => details.end(EncodePhase::GeometryUpload, 11),
                2 => details.end(EncodePhase::FramePlan, 9),
                3 => {
                    details.end(EncodePhase::FramePlan, 15);
                    details.begin(EncodePhase::CommandEncoding, 16);
                }
                4 => {
                    details.add_counter(EncodeCounter::VertexBytes, u64::MAX);
                    details.add_counter(EncodeCounter::VertexBytes, 1);
                    assert_eq!(details.to_json()["counters"]["vertex_bytes"], u64::MAX);
                }
                5 => {
                    details.end(EncodePhase::FramePlan, 15);
                    details.begin(EncodePhase::GeometryUpload, 14);
                }
                _ => details.complete(),
            }
            details.complete();
            finish(&mut details);
            assert_eq!(details.to_json()["state"], "incomplete");
        }
    }
    #[test]
    fn first_phase_clock_error_keeps_later_observed_partial_counters() {
        let mut details = CpuEncodeDetails::default();
        details.begin_parent(8);
        details.add_counter(EncodeCounter::PreparedDraws, 99);
        assert!(!details.is_active());
        details.begin(EncodePhase::FramePlan, 10);
        details.add_counter(EncodeCounter::PreparedDraws, 1);
        details.end(EncodePhase::FramePlan, 9);
        assert!(details.is_active());
        details.add_counter(EncodeCounter::PreparedDraws, 2);
        finish(&mut details);
        let value = details.to_json();
        assert_eq!(value["state"], "incomplete");
        assert_eq!(value["counters"]["prepared_draws"], 3);
        assert!(value["spans"].as_array().unwrap().is_empty());
    }
    #[test]
    fn unavailable_and_out_of_bounds_parents_fail_only_details() {
        for parent in [
            None,
            Some(CpuWallSpan {
                started_at_ns: 9,
                ended_at_ns: 70,
            }),
            Some(CpuWallSpan {
                started_at_ns: 5,
                ended_at_ns: 59,
            }),
        ] {
            let mut details = CpuEncodeDetails::default();
            details.begin_parent(8);
            phases(&mut details);
            details.complete();
            details.end_parent(60);
            details.validate_bounds(0, 100, parent);
            assert_eq!(details.to_json()["state"], "incomplete");
        }
    }
    #[test]
    fn outside_parent_suffix_is_unavailable_instead_of_clipped() {
        let mut details = CpuEncodeDetails::default();
        details.begin_parent(8);
        phases(&mut details);
        details.complete();
        details.end_parent(26);
        details.validate_bounds(
            0,
            100,
            Some(CpuWallSpan {
                started_at_ns: 5,
                ended_at_ns: 80,
            }),
        );
        let value = details.to_json();
        assert_eq!(value["state"], "incomplete");
        assert_eq!(value["error"], "encode_phase_outside_parent");
        assert_eq!(value["spans"].as_array().unwrap().len(), 2);
        assert_eq!(value["spans"][1]["ended_at_ns"], 25);
    }
    #[test]
    fn excess_phases_never_expand_fixed_storage() {
        let mut details = CpuEncodeDetails::default();
        details.begin_parent(8);
        phases(&mut details);
        details.begin(EncodePhase::QueueSubmit, 56);
        details.end(EncodePhase::QueueSubmit, 57);
        details.complete();
        finish(&mut details);
        assert_eq!(details.to_json()["state"], "incomplete");
        assert_eq!(
            details.to_json()["spans"].as_array().unwrap().len(),
            MAX_SPANS
        );
    }
    #[test]
    fn bounded_buffer_does_not_grow_with_excess_rows() {
        let mut capture = CpuEncodeCapture::new(2);
        capture.begin_attempt();
        let capacity = capture.rows.capacity();
        for _ in 0..3 {
            capture.retain(CpuEncodeDetails::default());
        }
        assert_eq!(capture.rows.len(), 2);
        assert_eq!(capture.rows.capacity(), capacity);
    }
}
