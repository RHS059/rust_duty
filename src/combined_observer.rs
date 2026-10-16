//! Bounded observation only. Gameplay never reads this journal.
use crate::sim::Simulation;
use serde_json::{json, Value};
use std::{fs::OpenOptions, io::Write, path::Path, sync::Mutex};
const MAX_BYTES: usize = 64 * 1024 * 1024;
const MAX_RECORDS: u64 = 12_000;
struct Journal {
    file: std::fs::File,
    count: u64,
    bytes: usize,
    error: Option<String>,
}
static JOURNAL: Mutex<Option<Journal>> = Mutex::new(None);
pub fn start(path: &Path) -> Result<(), String> {
    let mut g = JOURNAL.lock().map_err(|e| e.to_string())?;
    if g.is_some() {
        return Err("combined observer already opened".into());
    }
    let file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|e| e.to_string())?;
    *g = Some(Journal {
        file,
        count: 0,
        bytes: 0,
        error: None,
    });
    Ok(())
}
pub fn record(mut v: Value) {
    let Ok(mut g) = JOURNAL.lock() else { return };
    let Some(j) = g.as_mut() else { return };
    if j.error.is_some() {
        return;
    }
    v["schema"] = json!("rust-duty-combined-observer/v1");
    v["record_index"] = json!(j.count);
    let result = (|| -> Result<(), String> {
        let mut bytes = serde_json::to_vec(&v).map_err(|e| e.to_string())?;
        bytes.push(b'\n');
        if j.count >= MAX_RECORDS || bytes.len() > 65536 || j.bytes + bytes.len() > MAX_BYTES {
            return Err("combined observer bound exceeded".into());
        }
        j.file
            .write_all(&bytes)
            .and_then(|_| j.file.flush())
            .map_err(|e| e.to_string())?;
        j.bytes += bytes.len();
        j.count += 1;
        Ok(())
    })();
    if let Err(e) = result {
        j.error = Some(e);
    }
}
pub fn check() -> Result<(), String> {
    let g = JOURNAL.lock().map_err(|e| e.to_string())?;
    match g.as_ref().and_then(|j| j.error.as_ref()) {
        Some(e) => Err(e.clone()),
        None => Ok(()),
    }
}
pub fn bindings(s: &Simulation) -> Value {
    json!({"high":s.high_mantle_binding().map(|b|json!({"receipt_sha256":b.receipt_sha256(),"asset_sha256":b.asset_sha256(),"return_seconds":b.return_seconds(),"native_seconds":crate::authored_high_mantle::NATIVE_SECONDS,"source_range":[1,96],"reference_range_half_open":[7787,7883]})),
        "low":s.low_vault_binding().map(|b|json!({"receipt_sha256":b.receipt_sha256(),"asset_sha256":b.asset_sha256(),"candidate_sha256":b.candidate_sha256(),"clip":b.clip(),"return_seconds":b.return_seconds(),"native_seconds":crate::authored_low_vault::KEY_SPAN_SECONDS,"source_range":[1,64]})),
        "prone":s.prone_binding_identity()})
}
pub fn state(kind: &str, s: &Simulation) -> Value {
    // Reuse the established read-only state projection, not its journal/schema.
    let mut v = crate::high_mantle_observer::state(kind, s);
    v.as_object_mut().unwrap().remove("binding");
    // Observe the current admitted loaders on every state, never cache the header.
    // A disabled or failed binding remains null so verification can reject it.
    v["bindings"] = bindings(s);
    v["look"] = json!({"yaw":s.player.yaw,"pitch":s.player.pitch});
    v["prone_entry_started"] = json!(s.prone_entry_started());
    v["low"]=json!(s.low_vault_sample().map(|x|json!({"generation":s.low_vault_generation(),"seconds":x.seconds,"source_frame":x.source_frame,"reference_frame":x.reference_frame})));
    v["low_generation"] = json!(s.low_vault_generation());
    v["prone_sample"]=json!(s.prone_sample().map(|x|json!({"seconds":x.seconds,"source_frame":x.frame,"eye_height":x.eye_height,"orientation_xyzw":x.orientation.to_array()})));
    v["prone_return"]=json!(s.prone_return().map(|r|json!({"began":r.began,"duration":r.duration,"weight":r.weight(s.time),"frozen_seconds":r.sample.seconds,"frozen_source_frame":r.sample.frame,"orientation_xyzw":r.sample.orientation.to_array()})));
    v["prone_camera"]=json!(s.prone_camera_sample().map(|x|json!({"seconds":x.seconds,"source_frame":x.frame,"eye_height":x.eye_height,"orientation_xyzw":x.orientation.to_array()})));
    v["lean_offset"] = json!(s.player.lean_offset.to_array());
    v["landing_kick"] = json!(s.player.landing_kick);
    v
}
pub fn accepted(s: &Simulation) {
    let Ok(g) = JOURNAL.lock() else { return };
    if g.is_none() {
        return;
    }
    drop(g);
    let mut v = state("accepted", s);
    // Low's first sampled update occurs after acceptance; record the exact
    // native acceptance clock separately, never call it a rendered sample.
    v["accepted_source_clock"]=json!(s.player.mantle.map(|m|json!({"kind":format!("{:?}",m.kind),"seconds":0.,"source_frame":1.,"rendered":false,"from_hang":m.from_hang})));
    record(v);
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn combined_observer_states_report_current_admitted_bindings() {
        let mut sim = crate::authored_viewmodel::combined_replay_sim();
        let initial = bindings(&sim);
        assert!(["high", "low", "prone"]
            .iter()
            .all(|key| !initial[*key].is_null()));
        for kind in ["initial", "accepted", "step", "frame", "finished"] {
            assert_eq!(state(kind, &sim)["bindings"], initial);
        }
        sim.set_high_mantle_binding(None);
        let missing_high = state("step", &sim)["bindings"].clone();
        assert!(missing_high["high"].is_null());
        assert_eq!(missing_high["low"], initial["low"]);
        assert_eq!(missing_high["prone"], initial["prone"]);
        assert_ne!(missing_high, initial);
        sim.set_low_vault_binding(None).unwrap();
        sim.set_prone_camera_track(None);
        let disabled = state("frame", &sim)["bindings"].clone();
        assert!(["high", "low", "prone"]
            .iter()
            .all(|key| disabled[*key].is_null()));
    }
}
