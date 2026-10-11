//! Isolated headless DX12 correctness scenarios, never game/FPS evidence.
#![deny(warnings)]
#[allow(dead_code)]
#[path = "../pinned_gpu_timing.rs"]
mod gpu_timing;

use gpu_timing::{ BeginFrame, FrameKey, GpuSample, GpuTimer, SampleStatus, SampleTicket, SubmissionValidation};
use serde_json::{json, Value};
use std::{future::Future, io::Write, sync::{atomic::{AtomicBool, Ordering}, Arc, Mutex}, task::{Context, Poll, Wake, Waker}, thread, time::{Duration, Instant}};

const DEADLINE: Duration = Duration::from_secs(15);
type Result<T> = std::result::Result<T, String>;

fn emit(value: Value) {
    println!("{value}");
    std::io::stdout().flush().expect("flush native evidence");
}
fn require(ok: bool, why: &str) -> Result<()> {
    if ok { Ok(()) } else { Err(why.into()) }
}
fn bounded<F: Future>(future: F, name: &str) -> Result<F::Output> {
    struct Noop;
    impl Wake for Noop { fn wake(self: Arc<Self>) {} }
    let waker = Waker::from(Arc::new(Noop));
    let mut context = Context::from_waker(&waker);
    let mut future = std::pin::pin!(future);
    let start = Instant::now();
    loop {
        if let Poll::Ready(value) = future.as_mut().poll(&mut context) { return Ok(value); }
        if start.elapsed() >= DEADLINE { return Err(format!("{name} future deadline exceeded")); }
        thread::sleep(Duration::from_millis(1));
    }
}
fn key(session: u64, attempt: u64) -> FrameKey { FrameKey { session, attempt } }
fn sample(sample: &GpuSample) -> Value {
    json!({"event":"sample", "session":sample.frame.session.to_string(), "attempt":sample.frame.attempt.to_string(), "status":sample.status.label(), "start_ticks":sample.start_ticks.map(|x|x.to_string()), "end_ticks":sample.end_ticks.map(|x|x.to_string()), "timestamp_period_ns":sample.timestamp_period_ns, "elapsed_ns":sample.elapsed_ns})
}
fn assert_sample(value: &GpuSample, frame: FrameKey, status: SampleStatus) -> Result<()> {
    emit(sample(value));
    require(value.frame == frame, "sample joined wrong original session/attempt")?;
    require(value.status == status, "unexpected sample status")?;
    if status == SampleStatus::Measured {
        require(value.start_ticks.is_some() && value.end_ticks.is_some(), "missing measured raw ticks")?;
        require(value.elapsed_ns.is_some_and(|x| x.is_finite() && x >= 0.0), "invalid measured elapsed value")?;
        require(value.timestamp_period_ns.is_some_and(|x| x.is_finite() && x > 0.0), "invalid measured period")?;
        let delta = value.end_ticks.unwrap().checked_sub(value.start_ticks.unwrap()).ok_or("measured ticks reversed")?;
        require(value.elapsed_ns == Some(delta as f64 * value.timestamp_period_ns.unwrap()), "raw ticks and elapsed value disagree")?;
    } else {
        require(value.start_ticks.is_none() && value.end_ticks.is_none() && value.elapsed_ns.is_none() && value.timestamp_period_ns.is_none(), "unavailable sample fabricated numeric values")?;
    }
    Ok(())
}

struct Gpu {
    device: wgpu::Device,
    queue: wgpu::Queue,
    errors: Arc<Mutex<Vec<String>>>,
    adapter_supports_timestamps: bool,
}
impl Gpu {
    fn new(timestamps: bool) -> Result<Self> {
        require(cfg!(target_os="windows"), "runtime is Windows-only")?;
        require(wgpu::Instance::enabled_backend_features() == wgpu::Backends::DX12, "binary includes an unexpected backend")?;
        let mut descriptor = wgpu::InstanceDescriptor::new_without_display_handle();
        descriptor.backends = wgpu::Backends::DX12;
        descriptor.flags |= wgpu::InstanceFlags::VALIDATION;
        descriptor.backend_options.dx12.shader_compiler = wgpu::Dx12Compiler::Fxc;
        emit(json!({"event":"instance", "configured_backends":"DX12", "validation_requested":true, "shader_compiler":"Fxc", "force_fallback_adapter":true, "surface":null}));
        let instance = wgpu::Instance::new(descriptor);
        let adapter = bounded(instance.request_adapter(&wgpu::RequestAdapterOptions { force_fallback_adapter:true, ..Default::default() }), "request_adapter")?.map_err(|e|format!("DX12 fallback adapter unavailable: {e}"))?;
        let info = adapter.get_info();
        let available = adapter.features();
        let supported = available.contains(gpu_timing::required_features());
        let requested = gpu_timing::requested_features(timestamps, available);
        emit(json!({"event":"adapter", "backend":format!("{:?}",info.backend), "name":info.name, "vendor":info.vendor, "device":info.device, "device_type":format!("{:?}",info.device_type), "driver":info.driver, "driver_info":info.driver_info, "available_features":format!("{available:?}"), "requested_features":format!("{requested:?}"), "requested_timestamp_pair":requested.contains(gpu_timing::required_features()), "adapter_supports_timestamp_pair":supported}));
        require(info.backend == wgpu::Backend::Dx12, "selected backend is not DX12")?;
        require(info.device_type == wgpu::DeviceType::Cpu, "fallback adapter is not classified as CPU/software")?;
        let (device, queue) = bounded(adapter.request_device(&wgpu::DeviceDescriptor { label:Some("isolated GPU timing correctness device"), required_features:requested, required_limits:wgpu::Limits::downlevel_defaults().using_resolution(adapter.limits()), ..Default::default() }), "request_device")?.map_err(|e|format!("request device: {e}"))?;
        let errors: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(Vec::new()));
        let uncaptured = errors.clone();
        device.on_uncaptured_error(Arc::new(move |error| {
            let message = format!("uncaptured: {error}");
            emit(json!({"event":"uncaptured_error", "message":message}));
            uncaptured.lock().unwrap().push(message);
        }));
        let lost = errors.clone();
        device.set_device_lost_callback(move |reason,message| {
            let error = format!("device lost ({reason:?}): {message}");
            emit(json!({"event":"device_lost", "message":error}));
            lost.lock().unwrap().push(error);
        });
        emit(json!({"event":"device", "enabled_features":format!("{:?}",device.features()), "enabled_timestamp_pair":device.features().contains(gpu_timing::required_features()), "timestamp_period_ns":if requested.is_empty() {None} else {Some(queue.get_timestamp_period())}}));
        require(device.features().contains(requested), "requested device features not enabled")?;
        Ok(Self { device, queue, errors, adapter_supports_timestamps:supported })
    }
    fn check(&self) -> Result<()> {
        let errors = self.errors.lock().unwrap();
        if errors.is_empty() { Ok(()) } else { Err(format!("unexpected GPU failures: {errors:?}")) }
    }
    fn poll(&self) -> Result<()> {
        self.device.poll(wgpu::PollType::Poll).map_err(|e|format!("nonblocking device poll: {e}"))?;
        self.check()
    }
    fn timer(&self, enabled: bool) -> Result<GpuTimer> {
        let scope = self.device.push_error_scope(wgpu::ErrorFilter::Validation);
        let timer = GpuTimer::new(&self.device, &self.queue, enabled);
        let error = bounded(scope.pop(), "timer validation")?;
        require(error.is_none(), &format!("timer resource validation: {error:?}"))?;
        emit(json!({"event":"availability", "value":format!("{:?}",timer.availability())}));
        Ok(timer)
    }
    fn encoder(&self) -> wgpu::CommandEncoder { self.device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label:Some("isolated timestamp scenario") }) }
    fn done_flag(&self) -> Arc<AtomicBool> {
        let done = Arc::new(AtomicBool::new(false));
        let callback = done.clone();
        self.queue.on_submitted_work_done(move || callback.store(true, Ordering::Release));
        done
    }
    fn await_done(&self, flag: &AtomicBool, name: &str) -> Result<()> {
        let start = Instant::now();
        let mut polls = 0_u64;
        while !flag.load(Ordering::Acquire) {
            self.poll()?;
            polls += 1;
            if start.elapsed() >= DEADLINE { emit(json!({"event":"poll_deadline", "name":name, "polls":polls})); return Err(format!("{name}: GPU callback deadline exceeded")); }
            if !flag.load(Ordering::Acquire) { thread::sleep(Duration::from_millis(1)); }
        }
        self.check()?;
        emit(json!({"event":"work_done_witness", "name":name, "polls":polls, "deadline_ms":DEADLINE.as_millis(), "elapsed_ms":start.elapsed().as_millis(), "guarantee":"all mapped-buffer callbacks registered for that submission have run; this is harness correctness synchronization, not gameplay instrumentation"}));
        Ok(())
    }
    fn submit(&self, timer: &mut GpuTimer, frame: FrameKey, invalid: bool) -> Result<SampleTicket> {
        let scope = self.device.push_error_scope(wgpu::ErrorFilter::Validation);
        let buffer = self.device.create_buffer(&wgpu::BufferDescriptor { label:Some("known bounded clear workload"), size:64, usage:wgpu::BufferUsages::COPY_DST, mapped_at_creation:false });
        let mut encoder = self.encoder();
        let ticket = match timer.begin_frame(frame, &mut encoder) {
            BeginFrame::Recording(ticket) => ticket,
            BeginFrame::Unavailable(value) => { emit(sample(&value)); return Err("timestamp reservation unexpectedly unavailable".into()); }
        };
        encoder.clear_buffer(&buffer, 0, Some(if invalid {128} else {64}));
        timer.end_frame(&ticket, &mut encoder)?;
        self.queue.submit([encoder.finish()]);
        timer.after_submit(&ticket)?;
        let error = bounded(scope.pop(), "submission validation")?;
        emit(json!({"event":"submission_validation", "session":frame.session.to_string(), "attempt":frame.attempt.to_string(), "deliberate_invalid_clear":invalid, "error":error.as_ref().map(ToString::to_string)}));
        require(error.is_some() == invalid, "submission validation outcome did not match injected condition")?;
        self.check()?;
        Ok(ticket)
    }
}

fn one_ready(gpu: &Gpu, timer: &mut GpuTimer, frame: FrameKey, status: SampleStatus) -> Result<GpuSample> {
    let witness = gpu.done_flag();
    gpu.await_done(&witness, "sample callback completion")?;
    let mut ready = timer.collect_ready();
    require(ready.len() == 1, "expected exactly one completed sample")?;
    let value = ready.remove(0);
    assert_sample(&value, frame, status)?;
    require(timer.collect_ready().is_empty(), "sample emitted twice")?;
    Ok(value)
}
fn unavailable(gpu: &Gpu, enabled: bool) -> Result<()> {
    let mut timer = gpu.timer(enabled)?;
    let expected = if enabled {SampleStatus::DeviceFeaturesNotEnabled} else {SampleStatus::Disabled};
    let mut encoder = gpu.encoder();
    match timer.begin_frame(key(1,1), &mut encoder) {
        BeginFrame::Unavailable(value) => assert_sample(&value,key(1,1),expected)?,
        BeginFrame::Recording(_) => return Err("unavailable timer recorded GPU commands".into()),
    }
    drop(encoder);
    require(timer.collect_ready().is_empty() && timer.finish_nonblocking().is_empty(), "unavailable timer retained slots")?;
    gpu.poll()
}
fn ring_and_verdict(gpu: &Gpu) -> Result<()> {
    let mut timer = gpu.timer(true)?;
    let mut tickets = Vec::new();
    for attempt in 1..=4 { tickets.push(gpu.submit(&mut timer,key(2,attempt),false)?); }
    let witness = gpu.done_flag();
    gpu.await_done(&witness,"four mapped callbacks before verdict")?;
    require(timer.collect_ready().is_empty(), "mapped data published before explicit submission verdict")?;
    let mut extra = gpu.encoder();
    match timer.begin_frame(key(2,5),&mut extra) {
        BeginFrame::Unavailable(value) => assert_sample(&value,key(2,5),SampleStatus::RingFull)?,
        BeginFrame::Recording(_) => return Err("full ring overwrote a pending reservation".into()),
    }
    drop(extra);
    for ticket in &tickets { timer.record_submission_validation(ticket,SubmissionValidation::Accepted)?; }
    let mut ready = timer.collect_ready();
    ready.sort_by_key(|s|s.frame.attempt);
    require(ready.len()==4,"four completed callbacks did not retire exactly four slots")?;
    for (index,value) in ready.iter().enumerate() { assert_sample(value,key(2,index as u64+1),SampleStatus::Measured)?; }
    require(timer.collect_ready().is_empty(),"ring sample emitted twice")?;
    let next = gpu.submit(&mut timer,key(2,6),false)?;
    require(timer.record_submission_validation(&tickets[0],SubmissionValidation::Accepted).is_err(),"stale reservation accepted after slot reuse")?;
    timer.record_submission_validation(&next,SubmissionValidation::Accepted)?;
    one_ready(gpu,&mut timer,key(2,6),SampleStatus::Measured)?;
    require(timer.finish_nonblocking().is_empty(),"drained ring retained samples")
}
fn rejection(gpu: &Gpu, synthetic: bool) -> Result<()> {
    let mut timer = gpu.timer(true)?;
    let prime = gpu.submit(&mut timer,key(3,1),false)?;
    timer.record_submission_validation(&prime,SubmissionValidation::Accepted)?;
    one_ready(gpu,&mut timer,key(3,1),SampleStatus::Measured)?;
    let rejected = gpu.submit(&mut timer,key(3,2),!synthetic)?;
    emit(json!({"event":"verdict_origin", "synthetic":synthetic, "explanation":if synthetic {"caller-injected rejection of valid submitted work"} else {"actual captured oversized-clear encoding/submission validation error"}}));
    timer.record_submission_validation(&rejected,SubmissionValidation::Rejected)?;
    one_ready(gpu,&mut timer,key(3,2),SampleStatus::SubmissionRejected)?;
    let reused = gpu.submit(&mut timer,key(3,3),false)?;
    timer.record_submission_validation(&reused,SubmissionValidation::Accepted)?;
    one_ready(gpu,&mut timer,key(3,3),SampleStatus::Measured)?;
    Ok(())
}
fn abandon(gpu: &Gpu) -> Result<()> {
    let mut timer = gpu.timer(true)?;
    let mut encoder = gpu.encoder();
    let BeginFrame::Recording(ticket) = timer.begin_frame(key(4,1),&mut encoder) else { return Err("cannot reserve abandonment case".into()); };
    timer.end_frame(&ticket,&mut encoder)?;
    drop(encoder);
    assert_sample(&timer.abandon_unsubmitted(&ticket)?,key(4,1),SampleStatus::AbandonedBeforeSubmit)?;
    let next = gpu.submit(&mut timer,key(4,2),false)?;
    timer.record_submission_validation(&next,SubmissionValidation::Accepted)?;
    one_ready(gpu,&mut timer,key(4,2),SampleStatus::Measured)?;
    Ok(())
}
fn restart(gpu: &Gpu) -> Result<()> {
    let mut old = gpu.timer(true)?;
    let old_ticket = gpu.submit(&mut old,key(5,1),false)?;
    let witness = gpu.done_flag();
    emit(json!({"event":"pre_stop", "old_work_witness_delivered":witness.load(Ordering::Acquire), "validation_verdict":"withheld", "helper_map_callback_timing":"not directly exposed"}));
    let stopped = old.finish_nonblocking();
    require(stopped.len()==1,"stop did not preserve exactly one unconfirmed reservation")?;
    assert_sample(&stopped[0],key(5,1),SampleStatus::ValidationUnconfirmedAtStop)?;
    require(old.finish_nonblocking().is_empty(),"second stop emitted duplicate sample")?;
    let mut encoder = gpu.encoder();
    match old.begin_frame(key(5,2),&mut encoder) { BeginFrame::Unavailable(value) => assert_sample(&value,key(5,2),SampleStatus::Stopped)?, _ => return Err("stopped timer accepted reservation".into()) }
    drop(encoder);
    let mut new = gpu.timer(true)?;
    gpu.await_done(&witness,"old submitted work after replacement creation")?;
    require(old.collect_ready().is_empty() && new.collect_ready().is_empty(),"old completion leaked into replacement timer")?;
    let ticket = gpu.submit(&mut new,key(6,1),false)?;
    // Both owners now have slot zero, generation one, and a submitted ticket.
    // Only the owner identity guard can reject this old ticket.
    require(new.record_submission_validation(&old_ticket,SubmissionValidation::Accepted).is_err(),"old ticket affected replacement timer")?;
    emit(json!({"event":"cross_owner_ticket_rejected", "replacement_session":"6", "replacement_attempt":"1", "matching_slot_and_generation":true}));
    new.record_submission_validation(&ticket,SubmissionValidation::Accepted)?;
    one_ready(gpu,&mut new,key(6,1),SampleStatus::Measured)?;
    emit(json!({"event":"restart_coverage", "observed":"stopped-owner isolation and replacement-session readback after old-work completion witness", "not_proven":"old helper map callback delivered after restart; unmap may synchronously cancel it"}));
    Ok(())
}
fn run(name: &str) -> Result<&'static str> {
    let timing = !matches!(name,"disabled"|"missing_features");
    let gpu = Gpu::new(timing)?;
    if timing && !gpu.adapter_supports_timestamps { return Ok("unsupported"); }
    if name == "missing_features" && !gpu.adapter_supports_timestamps {
        unavailable(&gpu,true)?;
        return Ok("unsupported");
    }
    match name {
        "disabled" => unavailable(&gpu,false)?,
        "missing_features" => unavailable(&gpu,true)?,
        "ring_and_verdict" => ring_and_verdict(&gpu)?,
        "real_validation_rejection" => rejection(&gpu,false)?,
        "synthetic_rejection" => rejection(&gpu,true)?,
        "abandon" => abandon(&gpu)?,
        "stop_restart" => restart(&gpu)?,
        _ => return Err("unknown scenario".into()),
    }
    gpu.check()?;
    Ok("passed")
}
fn main() {
    let scenario = std::env::args().nth(1).unwrap_or_default();
    emit(json!({"event":"scenario_start", "name":scenario, "method":if scenario=="synthetic_rejection" {"native_with_synthetic_verdict"} else {"native"}, "purpose":"bounded DX12 correctness only; no FPS or observer-overhead claim"}));
    let result = run(&scenario);
    let (status,error,code) = match result { Ok("passed") => ("passed",None,0), Ok(_) => ("unsupported",Some("adapter does not support the complete timestamp pair".to_string()),2), Err(error) => ("failed",Some(error),1) };
    emit(json!({"event":"scenario_result", "name":scenario, "status":status, "error":error}));
    std::process::exit(code);
}
