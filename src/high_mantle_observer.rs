//! Opt-in, bounded observation only. Never owns input, clocks or gameplay state.
use crate::sim::Simulation;
use serde_json::{json, Value};
use std::{
    fs::{File, OpenOptions},
    io::Write,
    path::Path,
    sync::{
        atomic::{AtomicBool, Ordering},
        Mutex,
    },
    time::Instant,
};

static ENABLED: AtomicBool = AtomicBool::new(false);
static JOURNAL: Mutex<Option<Journal>> = Mutex::new(None);
const MAX_RECORDS: u64 = 12_000;
const MAX_BYTES: usize = 16 * 1024 * 1024;
struct Journal {
    file: File,
    start: Instant,
    count: u64,
    bytes: usize,
    error: Option<String>,
}

pub fn start(path: &Path) -> Result<(), String> {
    let file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|e| format!("create one-hand observer: {e}"))?;
    let mut journal = JOURNAL.lock().map_err(|e| e.to_string())?;
    if journal.is_some() {
        return Err("one-hand observer already started".into());
    }
    *journal = Some(Journal {
        file,
        start: Instant::now(),
        count: 0,
        bytes: 0,
        error: None,
    });
    ENABLED.store(true, Ordering::Release);
    Ok(())
}
pub fn enabled() -> bool {
    ENABLED.load(Ordering::Acquire)
}
/// Error is latched and surfaced by the app, never converted into successful evidence.
pub fn record(mut value: Value) {
    if !enabled() {
        return;
    }
    let Ok(mut guard) = JOURNAL.lock() else {
        return;
    };
    let Some(j) = guard.as_mut() else {
        return;
    };
    if j.error.is_some() {
        return;
    }
    if j.count >= MAX_RECORDS {
        j.error = Some("one-hand observer record bound exceeded".into());
        return;
    }
    value["schema"] = json!("rust-duty-onehand-observer/v1");
    value["record_index"] = json!(j.count);
    value["wall_seconds"] = json!(j.start.elapsed().as_secs_f64());
    let result = serde_json::to_vec(&value)
        .map_err(|e| e.to_string())
        .and_then(|mut bytes| {
            bytes.push(b'\n');
            if bytes.len() > 32_768 || j.bytes + bytes.len() > MAX_BYTES {
                return Err("one-hand observer byte bound exceeded".into());
            }
            j.bytes += bytes.len();
            j.file.write_all(&bytes).map_err(|e| e.to_string())
        })
        .and_then(|_| j.file.flush().map_err(|e| e.to_string()));
    if let Err(error) = result {
        j.error = Some(error);
    }
    j.count += 1;
}
pub fn check() -> Result<(), String> {
    if !enabled() {
        return Ok(());
    }
    let guard = JOURNAL.lock().map_err(|e| e.to_string())?;
    match guard.as_ref().and_then(|j| j.error.as_ref()) {
        Some(e) => Err(e.clone()),
        None => Ok(()),
    }
}
pub fn state(kind: &str, sim: &Simulation) -> Value {
    let p = &sim.player;
    let h = sim.high_mantle_presentation();
    json!({"kind":kind, "simulation_time":sim.time,
        "binding":sim.high_mantle_binding().map(|b| json!({"receipt_sha256":b.receipt_sha256(),
            "asset_sha256":b.asset_sha256(),"return_seconds":b.return_seconds()})),
        "high":h.map(|h|json!({"generation":h.generation,
            "seconds":h.sample.seconds,"source_frame":h.sample.source_frame,"reference_frame":h.sample.reference_frame,
            "outgoing":h.outgoing.map(|r|json!({"began":r.began,"duration":r.duration,
                "weight":r.weight(sim.time),"completed":r.completed,
                "frozen_seconds":r.sample.seconds,"frozen_source_frame":r.sample.source_frame}))})),
        "mantle":p.mantle.map(|m|json!({"kind":format!("{:?}",m.kind),"from_hang":m.from_hang,
            "duration":m.duration(),"progress":m.progress(),"start":m.start.to_array(),"landing":m.landing.to_array()})),
        "accepted_at":p.last_jump_at,"position":p.position.to_array(),"velocity":p.velocity.to_array(),
        "camera_eye":p.eye().to_array(),"direction":p.direction().to_array(),
        "eye_height":p.eye_height,"grounded":p.grounded,"prone":p.prone,"crouched":p.crouched,
        "stance_progress":p.stance_progress,"dead":p.dead(),"health":p.health,
        "ads_requested":p.ads_requested,"simulation_ads":p.ads,"speed":p.speed(),
        "ammo":p.ammo,"reserve":p.reserve,"shots":sim.stats.shots,
        "reload_left":p.reload_left,"reload_credit_at":p.reload_credit_at,"reload_ready_at":p.reload_ready_at})
}
pub fn event(kind: &str, sim: &Simulation) {
    if enabled() {
        record(state(kind, sim));
    }
}
