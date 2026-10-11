//! Optional bounded CPU diagnostics nested inside the existing four frame spans.
//! This does not change presentation, validation, or the frames.json contract.
use serde_json::{json, Value};

pub const SCHEMA: &str = "rust_duty_cpu_substages_v1";
pub const MEASUREMENT: &str = "cpu_wall_clock_nested_frame_substage_ns";
pub const INTERPRETATION: &str = "CPU call durations inside existing parent spans, not GPU time. Validation CPU is the existing error-scope pop and pollster wrapper, not a GPU completion wait. Missing calls are unavailable, not zero; parent and child times must not be added.";
pub const MAX_SPANS: usize = 6;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CpuSubstage {
    AcquireTexture,
    AcquireValidation,
    EncodeSubmit,
    SubmitValidation,
}
impl CpuSubstage {
    pub fn label(self) -> &'static str {
        match self {
            Self::AcquireTexture => "acquire_texture",
            Self::AcquireValidation => "acquire_validation_cpu",
            Self::EncodeSubmit => "encode_submit",
            Self::SubmitValidation => "submit_validation_cpu",
        }
    }
    pub fn parent(self) -> &'static str {
        match self {
            Self::AcquireTexture | Self::AcquireValidation => "surface_acquire",
            Self::EncodeSubmit | Self::SubmitValidation => "renderer_submit",
        }
    }
}

#[derive(Clone, Copy, Debug)]
struct Span {
    stage: CpuSubstage,
    started_at_ns: u64,
    ended_at_ns: u64,
}

/// Fixed storage per retained frame; no per-call allocation or filesystem I/O.
/// Callers use the session's existing clock only while capture is active.
#[derive(Clone, Debug)]
pub(crate) struct CpuSubstages {
    spans: [Option<Span>; MAX_SPANS],
    count: usize,
    open: Option<(CpuSubstage, u64)>,
    error: Option<&'static str>,
}
impl Default for CpuSubstages {
    fn default() -> Self {
        Self {
            spans: [None; MAX_SPANS],
            count: 0,
            open: None,
            error: None,
        }
    }
}
impl CpuSubstages {
    pub fn invalidate(&mut self, error: &'static str) {
        self.error.get_or_insert(error);
    }

    pub fn begin(&mut self, stage: CpuSubstage, at_ns: u64) {
        if self.error.is_some() {
            return;
        }
        if self.open.is_some() || self.count == MAX_SPANS {
            self.invalidate("overlapping_or_excess_substage");
            return;
        }
        let previous = self.count.checked_sub(1).and_then(|i| self.spans[i]);
        if previous.is_some_and(|span| at_ns < span.ended_at_ns) {
            self.invalidate("non_monotonic_substage");
            return;
        }
        use CpuSubstage::*;
        let ordered = matches!(
            (previous.map(|span| span.stage), stage),
            (None, AcquireTexture | EncodeSubmit)
                | (Some(AcquireTexture), AcquireValidation)
                | (Some(AcquireValidation), AcquireTexture | EncodeSubmit)
                | (Some(EncodeSubmit), SubmitValidation)
        );
        let maximum = if matches!(stage, AcquireTexture | AcquireValidation) {
            2
        } else {
            1
        };
        let already = self.spans[..self.count]
            .iter()
            .flatten()
            .filter(|span| span.stage == stage)
            .count();
        if !ordered || already >= maximum {
            self.invalidate("unexpected_substage_order_or_count");
            return;
        }
        self.open = Some((stage, at_ns));
    }

    pub fn end(&mut self, stage: CpuSubstage, at_ns: u64) {
        if self.error.is_some() {
            return;
        }
        let Some((opened, started_at_ns)) = self.open.take() else {
            self.invalidate("unopened_substage");
            return;
        };
        if opened != stage || at_ns < started_at_ns {
            self.invalidate("mismatched_or_non_monotonic_substage");
            return;
        }
        self.spans[self.count] = Some(Span {
            stage,
            started_at_ns,
            ended_at_ns: at_ns,
        });
        self.count += 1;
    }

    pub fn to_json(&self) -> Value {
        let error = self.error.or(self.open.map(|_| "unterminated_substage"));
        let spans: Vec<_> = self.spans[..self.count]
            .iter()
            .flatten()
            .map(|span| {
                json!({"stage":span.stage.label(), "parent":span.stage.parent(),
                "started_at_ns":span.started_at_ns, "ended_at_ns":span.ended_at_ns,
                "duration_ns":span.ended_at_ns - span.started_at_ns})
            })
            .collect();
        json!({"state":if error.is_some() { "incomplete" } else { "complete" },
            "error":error, "spans":spans})
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn retains_two_acquire_attempts_and_submission_without_allocation_growth() {
        use CpuSubstage::*;
        let mut details = CpuSubstages::default();
        for (i, stage) in [
            AcquireTexture,
            AcquireValidation,
            AcquireTexture,
            AcquireValidation,
            EncodeSubmit,
            SubmitValidation,
        ]
        .into_iter()
        .enumerate()
        {
            details.begin(stage, i as u64 * 10);
            details.end(stage, i as u64 * 10 + 7);
        }
        let value = details.to_json();
        assert_eq!(value["state"], "complete");
        assert_eq!(value["spans"].as_array().unwrap().len(), 6);
        assert_eq!(value["spans"][5]["duration_ns"], 7);
    }

    #[test]
    fn missing_end_is_unavailable_and_never_synthesized() {
        let mut details = CpuSubstages::default();
        details.begin(CpuSubstage::EncodeSubmit, 7);
        let value = details.to_json();
        assert_eq!(value["state"], "incomplete");
        assert_eq!(value["error"], "unterminated_substage");
        assert_eq!(value["spans"].as_array().unwrap().len(), 0);
    }

    #[test]
    fn overlap_wrong_order_and_non_monotonic_calls_fail_only_diagnostics() {
        use CpuSubstage::*;
        for kind in 0..4 {
            let mut details = CpuSubstages::default();
            details.begin(AcquireTexture, 10);
            match kind {
                0 => details.begin(AcquireValidation, 11),
                1 => details.end(AcquireValidation, 11),
                2 => details.end(AcquireTexture, 9),
                _ => {
                    details.end(AcquireTexture, 11);
                    details.begin(EncodeSubmit, 12);
                }
            }
            assert_eq!(details.to_json()["state"], "incomplete");
        }
    }

    #[test]
    fn a_third_acquisition_attempt_is_not_silently_truncated() {
        use CpuSubstage::*;
        let mut details = CpuSubstages::default();
        for i in 0..2 {
            details.begin(AcquireTexture, i * 4);
            details.end(AcquireTexture, i * 4 + 1);
            details.begin(AcquireValidation, i * 4 + 2);
            details.end(AcquireValidation, i * 4 + 3);
        }
        details.begin(AcquireTexture, 8);
        assert_eq!(details.to_json()["state"], "incomplete");
        assert_eq!(details.to_json()["spans"].as_array().unwrap().len(), 4);
    }
}
