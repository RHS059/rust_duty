//! Opt-in, local GPU counters sampled off the render thread. These are OS
//! engine-occupancy/memory observations, never GPU frame-duration measurements.
use serde_json::{json, Value};
use std::fs::{File, OpenOptions};
use std::io::{self, BufWriter, Write};
use std::path::{Path, PathBuf};
use std::sync::mpsc::{self, Receiver, Sender};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

#[cfg(any(windows, test))]
#[path = "gpu_telemetry/counters.rs"]
mod counters;
#[cfg(any(windows, test))]
#[cfg_attr(not(windows), allow(dead_code))]
#[path = "gpu_telemetry/windows.rs"]
mod windows;
#[cfg(any(windows, test))]
use counters::{aggregate, CounterResult, CounterValue};

const INTERVAL: Duration = Duration::from_secs(1);
const MAX_SAMPLES: u64 = 86_400;

/// The game owns only a stop sender. No PDH query, sample, file write or thread
/// join is performed in a frame hook. Dropping requests an interrupted stop.
pub struct Recorder {
    stop: Option<Sender<&'static str>>,
}
impl Recorder {
    pub fn start(directory: &Path, renderer_observed: Value) -> io::Result<Self> {
        let epoch = Instant::now();
        let wall_start = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .ok()
            .map(|value| value.as_millis().min(u64::MAX as u128) as u64);
        let samples = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(directory.join("gpu.jsonl"))?;
        let metadata = json!({
            "schema":"rust-duty-gpu-telemetry/v1", "provider":provider_name(),
            "process_id":std::process::id(), "recording_started_unix_ms":wall_start,
            "nominal_sample_interval_ms":INTERVAL.as_millis(), "sample_limit":MAX_SAMPLES,
            "renderer_observed":renderer_observed,
            "renderer_adapter_binding":"unverified; Windows LUID/physical-adapter counters are not bound to the renderer adapter name",
            "utilization_definition":"OS GPU engine occupancy, not shader/core occupancy; whole-adapter sums processes per engine and takes the busiest engine; game process takes its busiest engine",
            "memory_definition":"OS reported dedicated/shared usage bytes, not installed capacity or memory-controller utilization",
            "scope":"all recording wall time including paused/unfocused periods; not limited to eligible presented frames",
            "timing":"sample start/end are monotonic milliseconds since GPU recorder start; the frame trace has its own clock origin",
            "gpu_frame_duration_ms":{"value":null,"unavailable_reason":"GPU timestamp queries are not instrumented; CPU present-return intervals are not GPU duration"},
            "completion":"Read GPU_STATUS.json independently; missing, partial or interrupted status is not a completed GPU export. Stopping is asynchronous."
        });
        write_new_json(&directory.join("GPU_METADATA.json"), &metadata)?;
        let (stop, receive) = mpsc::channel();
        let directory = directory.to_owned();
        thread::Builder::new()
            .name("gpu-telemetry".into())
            .spawn(move || run(directory, samples, receive, epoch))?;
        Ok(Self { stop: Some(stop) })
    }
    /// Signalling never waits for a driver/provider call on the game thread.
    pub fn stop(&mut self) {
        if let Some(sender) = self.stop.take() {
            let _ = sender.send("stopped");
        }
    }
}
impl Drop for Recorder {
    fn drop(&mut self) {
        if let Some(sender) = self.stop.take() {
            let _ = sender.send("interrupted");
        }
    }
}

fn write_new_json(path: &Path, value: &Value) -> io::Result<()> {
    let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
    serde_json::to_writer_pretty(&mut file, value).map_err(io::Error::other)?;
    file.write_all(b"\n")?;
    file.sync_all()
}
fn provider_name() -> &'static str {
    if cfg!(windows) {
        "windows_pdh"
    } else {
        "unavailable"
    }
}

trait Provider {
    fn sample(&mut self) -> Value;
}
struct Unavailable(String);
impl Provider for Unavailable {
    fn sample(&mut self) -> Value {
        json!({"adapters":[],"unavailable_reason":self.0})
    }
}
fn provider() -> Box<dyn Provider> {
    #[cfg(windows)]
    {
        match windows::PdhProvider::new() {
            Ok(provider) => Box::new(provider),
            Err(error) => Box::new(Unavailable(error)),
        }
    }
    #[cfg(not(windows))]
    {
        Box::new(Unavailable(
            "GPU utilization provider is only implemented for Windows".into(),
        ))
    }
}
fn run(directory: PathBuf, samples: File, stop: Receiver<&'static str>, epoch: Instant) {
    run_with_provider(
        directory,
        samples,
        stop,
        epoch,
        provider(),
        INTERVAL,
        MAX_SAMPLES,
    );
}
fn run_with_provider(
    directory: PathBuf,
    samples: File,
    stop: Receiver<&'static str>,
    epoch: Instant,
    mut provider: Box<dyn Provider>,
    interval: Duration,
    limit: u64,
) {
    let mut writer = BufWriter::new(samples);
    let mut count = 0;
    let mut available = 0;
    let mut failure = None;
    let state = loop {
        // The initial sample is explicit warm-up/unavailable when a counter
        // needs two observations. Subsequent queries occur no faster than 1 Hz.
        let started = epoch.elapsed();
        let values = provider.sample();
        let finished = epoch.elapsed();
        let has_process_utilization = values["adapters"].as_array().is_some_and(|rows| {
            rows.iter()
                .any(|row| row["process_busiest_engine_pct"]["value"].is_number())
        });
        let row = json!({"sample":count,"sample_started_ms":started.as_secs_f64()*1000.0,
            "sample_finished_ms":finished.as_secs_f64()*1000.0,
            "provider_query_cpu_wall_ms":finished.saturating_sub(started).as_secs_f64()*1000.0,
            "data":values});
        if let Err(error) = serde_json::to_writer(&mut writer, &row)
            .map_err(io::Error::other)
            .and_then(|()| writer.write_all(b"\n"))
            .and_then(|()| writer.flush())
        {
            failure = Some(error.to_string());
            break "incomplete";
        }
        count += 1;
        available += u64::from(has_process_utilization);
        if count >= limit {
            break "sample_limit_reached";
        }
        match stop.recv_timeout(interval) {
            Ok(state) => break state,
            Err(mpsc::RecvTimeoutError::Disconnected) => break "interrupted",
            Err(mpsc::RecvTimeoutError::Timeout) => {}
        }
    };
    if let Err(error) = writer.flush().and_then(|()| writer.get_ref().sync_all()) {
        failure.get_or_insert_with(|| error.to_string());
    }
    // Release stream and native query before publishing terminal evidence.
    drop(writer);
    drop(provider);
    let status = json!({"schema":"rust-duty-gpu-status/v1", "state":if failure.is_some(){"incomplete"}else{state},
        "samples_written":count,"samples_with_game_process_utilization":available,
        "error":failure,"gpu_frame_duration_available":false,
        "note":"An exported sample may report unavailable metrics. Export completion is not hardware or performance validation."});
    if let Err(error) = write_new_json(&directory.join("GPU_STATUS.json"), &status) {
        eprintln!(
            "GPU telemetry status export failed in {}: {error}",
            directory.display()
        );
    }
}

#[cfg(test)]
#[path = "gpu_telemetry/tests.rs"]
mod tests;
