use super::counters::instance;
use super::*;
use std::fs;
use std::sync::atomic::{AtomicU64, Ordering};

fn root() -> PathBuf {
    static NEXT: AtomicU64 = AtomicU64::new(0);
    let path = std::env::temp_dir().join(format!(
        "gpu-telemetry-{}-{}",
        std::process::id(),
        NEXT.fetch_add(1, Ordering::Relaxed)
    ));
    fs::create_dir(&path).unwrap();
    path
}
fn engine(pid: u32, adapter: u32, id: u32, kind: &str, value: f64) -> CounterValue {
    CounterValue {
        name: format!("pid_{pid}_luid_0x00000000_0x{adapter:08x}_phys_0_eng_{id}_engtype_{kind}"),
        value: Ok(value),
    }
}
fn absent() -> CounterResult {
    Err("unsupported test counter".into())
}
fn result(engines: Vec<CounterValue>) -> Value {
    aggregate(Ok(engines), absent(), absent(), absent(), absent(), 7)
}
fn wait_status(root: &Path) -> Value {
    let start = Instant::now();
    loop {
        if let Ok(bytes) = fs::read(root.join("GPU_STATUS.json")) {
            if let Ok(value) = serde_json::from_slice(&bytes) {
                return value;
            }
        }
        assert!(
            start.elapsed() < Duration::from_secs(10),
            "GPU worker did not finalize"
        );
        thread::sleep(Duration::from_millis(5));
    }
}
#[test]
fn parse_gpu_identity_exactly_and_reject_pid_prefix_collisions() {
    let parsed = instance(&engine(70, 2, 4, "VideoDecode", 1.0).name).unwrap();
    assert_eq!(parsed.pid, Some(70));
    assert_eq!(parsed.adapter, "luid_0x00000000_0x00000002_phys_0");
    assert_eq!(parsed.engine, Some((4, "VideoDecode".into())));
    for name in [
        "garbage",
        "pid_7_luid_0x0_0x1_phys_0",
        "pid_7_luid_0x00000000_0x00000001_phys_-1",
        "pid_7_luid_0x00000000_0x00000001_phys_0_eng_0_engtype_3D#1",
    ] {
        assert!(instance(name).is_none());
    }
}
#[test]
fn whole_adapter_sums_processes_per_engine_but_never_sums_parallel_engines() {
    let data = result(vec![
        engine(7, 1, 0, "3D", 40.0),
        engine(8, 1, 0, "3D", 30.0),
        engine(7, 1, 1, "Copy", 80.0),
        engine(70, 1, 1, "Copy", 15.0),
    ]);
    assert_eq!(
        data["adapters"][0]["adapter_busiest_engine_pct"]["value"],
        95.0
    );
    assert_eq!(
        data["adapters"][0]["process_busiest_engine_pct"]["value"],
        80.0
    );
    assert_eq!(data["adapters"][0]["renderer_binding"], "unverified");
    assert!(!data.to_string().contains("pid_8_"));
}
#[test]
fn keeps_multiple_gpus_and_real_zero_separate_from_missing_process() {
    let data = result(vec![
        engine(7, 1, 0, "3D", 0.0),
        engine(8, 2, 0, "Compute", 92.0),
    ]);
    assert_eq!(data["adapters"].as_array().unwrap().len(), 2);
    assert_eq!(
        data["adapters"][0]["process_busiest_engine_pct"]["value"],
        0.0
    );
    assert!(data["adapters"][1]["process_busiest_engine_pct"]["value"].is_null());
    assert!(data["adapters"][1]["process_busiest_engine_pct"]["unavailable_reason"].is_string());
}
#[test]
fn invalid_and_duplicate_values_cannot_turn_into_zero_or_partial_success() {
    for value in [f64::NAN, f64::INFINITY, -1.0, 101.0] {
        let data = result(vec![engine(7, 1, 0, "3D", value)]);
        assert!(data["adapters"][0]["process_busiest_engine_pct"]["value"].is_null());
    }
    let data = result(vec![
        engine(7, 1, 0, "3D", 40.0),
        engine(7, 1, 0, "3D", 40.0),
    ]);
    assert!(data["adapters"][0]["adapter_busiest_engine_pct"]["value"].is_null());
    let mut invalid = engine(8, 1, 0, "3D", 0.0);
    invalid.value = Err("invalid PDH status".into());
    let data = result(vec![engine(7, 1, 0, "3D", 40.0), invalid]);
    assert!(data["adapters"][0]["adapter_busiest_engine_pct"]["value"].is_null());
    assert_eq!(
        data["adapters"][0]["process_busiest_engine_pct"]["value"],
        40.0
    );
}
#[test]
fn sum_is_capped_at_100_with_an_explicit_rounding_marker() {
    let data = result(vec![
        engine(7, 1, 0, "3D", 50.5),
        engine(8, 1, 0, "3D", 50.5),
    ]);
    assert_eq!(
        data["adapters"][0]["adapter_busiest_engine_pct"]["value"],
        100.0
    );
    assert_eq!(
        data["adapters"][0]["adapter_engines"][0]["sum_capped_at_100"],
        true
    );
}
#[test]
fn memory_scopes_are_distinct_and_unsupported_is_null() {
    let memory = |name: &str, value| {
        Ok(vec![CounterValue {
            name: name.into(),
            value: Ok(value),
        }])
    };
    let data = aggregate(
        Ok(vec![engine(7, 1, 0, "3D", 1.0)]),
        memory("pid_7_luid_0x00000000_0x00000001_phys_0", 2_147_483_648.0),
        memory("pid_70_luid_0x00000000_0x00000001_phys_0", 5.0),
        memory("luid_0x00000000_0x00000001_phys_0", 4_294_967_296.0),
        absent(),
        7,
    );
    assert_eq!(
        data["adapters"][0]["process_dedicated_bytes"]["value"],
        2_147_483_648.0
    );
    assert_eq!(
        data["adapters"][0]["adapter_dedicated_bytes"]["value"],
        4_294_967_296.0
    );
    assert!(data["adapters"][0]["process_shared_bytes"]["value"].is_null());
    assert!(data["adapters"][0]["adapter_shared_bytes"]["value"].is_null());
}
#[test]
fn all_unsupported_has_reasons_without_zero_devices() {
    let data = aggregate(absent(), absent(), absent(), absent(), absent(), 7);
    assert!(data["adapters"].as_array().unwrap().is_empty());
    assert!(data["unavailable_reason"].is_string());
    assert_eq!(
        data["counter_status"]["engine"]["reason"],
        "unsupported test counter"
    );
}
#[test]
fn worker_exports_stopped_and_interrupted_sessions_without_overwriting() {
    let root = root();
    let samples = File::create(root.join("gpu.jsonl")).unwrap();
    let (send, receive) = mpsc::channel();
    send.send("stopped").unwrap();
    run_with_provider(
        root.clone(),
        samples,
        receive,
        Instant::now(),
        Box::new(Unavailable("synthetic unsupported".into())),
        Duration::from_secs(1),
        4,
    );
    let status = wait_status(&root);
    assert_eq!(status["state"], "stopped");
    assert_eq!(status["samples_written"], 1);
    assert_eq!(status["samples_with_game_process_utilization"], 0);
    let row: Value =
        serde_json::from_str(fs::read_to_string(root.join("gpu.jsonl")).unwrap().trim()).unwrap();
    assert_eq!(row["data"]["unavailable_reason"], "synthetic unsupported");
    assert!(write_new_json(&root.join("GPU_STATUS.json"), &json!({})).is_err());
    fs::remove_dir_all(root).unwrap();
    let root = self::root();
    let samples = File::create(root.join("gpu.jsonl")).unwrap();
    let (send, receive) = mpsc::channel();
    drop(send);
    run_with_provider(
        root.clone(),
        samples,
        receive,
        Instant::now(),
        Box::new(Unavailable("synthetic".into())),
        Duration::from_secs(1),
        4,
    );
    assert_eq!(wait_status(&root)["state"], "interrupted");
    fs::remove_dir_all(root).unwrap();
}
#[test]
fn bounded_capture_is_not_mislabeled_normal_completion() {
    let root = root();
    let samples = File::create(root.join("gpu.jsonl")).unwrap();
    let (_send, receive) = mpsc::channel();
    run_with_provider(
        root.clone(),
        samples,
        receive,
        Instant::now(),
        Box::new(Unavailable("synthetic".into())),
        Duration::ZERO,
        2,
    );
    let status = wait_status(&root);
    assert_eq!(status["state"], "sample_limit_reached");
    assert_eq!(status["samples_written"], 2);
    fs::remove_dir_all(root).unwrap();
}
#[cfg(not(windows))]
#[test]
fn real_unsupported_provider_and_repeated_stops_remain_explicit() {
    let root = root();
    let mut recorder = Recorder::start(&root, json!({"adapter":"synthetic"})).unwrap();
    recorder.stop();
    recorder.stop();
    drop(recorder);
    assert_eq!(wait_status(&root)["state"], "stopped");
    let rows = fs::read_to_string(root.join("gpu.jsonl")).unwrap();
    assert!(rows.contains("only implemented for Windows"));
    let metadata: Value =
        serde_json::from_slice(&fs::read(root.join("GPU_METADATA.json")).unwrap()).unwrap();
    assert!(metadata["gpu_frame_duration_ms"]["value"].is_null());
    assert!(Recorder::start(&root, json!({})).is_err());
    fs::remove_dir_all(root).unwrap();
}

#[cfg(windows)]
#[test]
fn windows_live_recorder_reports_data_or_explicit_counter_unavailability() {
    let root = root();
    let mut recorder =
        Recorder::start(&root, json!({"adapter":"test; no renderer binding"})).unwrap();
    thread::sleep(Duration::from_millis(2200));
    recorder.stop();
    let status = wait_status(&root);
    assert_eq!(status["state"], "stopped");
    let text = fs::read_to_string(root.join("gpu.jsonl")).unwrap();
    let rows: Vec<Value> = text
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect();
    assert!(!rows.is_empty());
    for row in rows {
        let data = &row["data"];
        if data["adapters"].as_array().unwrap().is_empty() {
            assert!(data["unavailable_reason"].is_string());
        } else {
            for adapter in data["adapters"].as_array().unwrap() {
                for key in [
                    "process_busiest_engine_pct",
                    "adapter_busiest_engine_pct",
                    "process_dedicated_bytes",
                    "adapter_dedicated_bytes",
                ] {
                    let value = &adapter[key];
                    assert!(value["value"].is_number() || value["unavailable_reason"].is_string());
                }
            }
        }
    }
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn stream_write_failure_is_incomplete_and_does_not_count_the_failed_row() {
    let root = root();
    fs::write(root.join("gpu.jsonl"), b"preserved").unwrap();
    let read_only = File::open(root.join("gpu.jsonl")).unwrap();
    let (_send, receive) = mpsc::channel();
    run_with_provider(
        root.clone(),
        read_only,
        receive,
        Instant::now(),
        Box::new(Unavailable("synthetic".into())),
        Duration::ZERO,
        2,
    );
    let status = wait_status(&root);
    assert_eq!(status["state"], "incomplete");
    assert_eq!(status["samples_written"], 0);
    assert!(status["error"].is_string());
    assert_eq!(fs::read(root.join("gpu.jsonl")).unwrap(), b"preserved");
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn terminal_status_failure_does_not_overwrite_an_existing_file() {
    let root = root();
    fs::write(root.join("GPU_STATUS.json"), b"preserved").unwrap();
    let samples = File::create(root.join("gpu.jsonl")).unwrap();
    let (send, receive) = mpsc::channel();
    send.send("stopped").unwrap();
    run_with_provider(
        root.clone(),
        samples,
        receive,
        Instant::now(),
        Box::new(Unavailable("synthetic".into())),
        Duration::ZERO,
        2,
    );
    assert_eq!(
        fs::read(root.join("GPU_STATUS.json")).unwrap(),
        b"preserved"
    );
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn stop_signals_without_waiting_for_a_blocked_provider_and_worker_exits() {
    struct Blocking {
        started: Sender<()>,
        release: Receiver<()>,
        exited: Sender<()>,
    }
    impl Provider for Blocking {
        fn sample(&mut self) -> Value {
            self.started.send(()).unwrap();
            self.release.recv_timeout(Duration::from_secs(10)).unwrap();
            json!({"adapters":[],"unavailable_reason":"synthetic blocking provider"})
        }
    }
    impl Drop for Blocking {
        fn drop(&mut self) {
            let _ = self.exited.send(());
        }
    }
    let root = root();
    let samples = File::create(root.join("gpu.jsonl")).unwrap();
    let (send, receive) = mpsc::channel();
    let (started, at_sample) = mpsc::channel();
    let (release, proceed) = mpsc::channel();
    let (exited, at_exit) = mpsc::channel();
    let directory = root.clone();
    let worker = thread::spawn(move || {
        run_with_provider(
            directory,
            samples,
            receive,
            Instant::now(),
            Box::new(Blocking {
                started,
                release: proceed,
                exited,
            }),
            INTERVAL,
            10,
        )
    });
    at_sample.recv_timeout(Duration::from_secs(10)).unwrap();
    let mut recorder = Recorder { stop: Some(send) };
    recorder.stop();
    // This code is reached while the worker is deliberately still blocked.
    assert!(at_exit.try_recv().is_err());
    assert!(!root.join("GPU_STATUS.json").exists());
    release.send(()).unwrap();
    assert_eq!(wait_status(&root)["state"], "stopped");
    at_exit.recv_timeout(Duration::from_secs(10)).unwrap();
    worker.join().unwrap();
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn unrecognized_engine_instances_cannot_hide_missing_load() {
    let data = result(vec![
        engine(7, 1, 0, "3D", 10.0),
        CounterValue {
            name: "unexpected future engine naming".into(),
            value: Ok(50.0),
        },
    ]);
    assert_eq!(data["rejected_instance_names"], 1);
    assert!(data["adapters"][0]["adapter_busiest_engine_pct"]["value"].is_null());
}

#[test]
fn warmup_is_unavailable_and_only_valid_subsequent_samples_are_counted() {
    struct Sequence(bool);
    impl Provider for Sequence {
        fn sample(&mut self) -> Value {
            if self.0 {
                result(vec![engine(7, 1, 0, "3D", 55.0)])
            } else {
                self.0 = true;
                json!({"adapters":[],"unavailable_reason":"warming_up; rate counters require two observations"})
            }
        }
    }
    let root = root();
    let samples = File::create(root.join("gpu.jsonl")).unwrap();
    let (_send, receive) = mpsc::channel();
    run_with_provider(
        root.clone(),
        samples,
        receive,
        Instant::now(),
        Box::new(Sequence(false)),
        Duration::ZERO,
        2,
    );
    let status = wait_status(&root);
    assert_eq!(status["samples_written"], 2);
    assert_eq!(status["samples_with_game_process_utilization"], 1);
    let rows: Vec<Value> = fs::read_to_string(root.join("gpu.jsonl"))
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect();
    assert!(rows[0]["data"]["unavailable_reason"]
        .as_str()
        .unwrap()
        .contains("warming_up"));
    assert_eq!(
        rows[1]["data"]["adapters"][0]["process_busiest_engine_pct"]["value"],
        55.0
    );
    fs::remove_dir_all(root).unwrap();
}
