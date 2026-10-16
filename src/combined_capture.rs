//! Dedicated combined route capture. Does not repurpose one-hand validation.
use crate::authored_viewmodel::AuthoredViewmodel;
use serde_json::json;
use std::path::PathBuf;
use vector_range::{
    combined_observer as trace,
    combined_replay::{Cadence, Observed, Phase, Replay, SEQUENCE},
    draw::{
        facade::{backend_info, capture_png_with_frame_witness},
        frame_witness,
    },
    settings::Settings,
    sim::{Input, Simulation},
};

pub struct Capture {
    replay: Replay,
    output: PathBuf,
    witness: String,
    hz: u32,
    frame: u64,
    pngs: u32,
    last_marker: String,
    tick: u64,
    cadence: Cadence,
}
impl Capture {
    pub fn open(args: &[String], s: &Simulation) -> Result<Option<Self>, String> {
        let sequence = args
            .iter()
            .any(|a| a == "--capture-sequence=gameplay-combined");
        let explicit = args.iter().any(|a| a.starts_with("--combined-"));
        if !sequence && !explicit {
            return Ok(None);
        }
        if !sequence
            || !args.iter().any(|a| a == "--combined-deterministic")
            || !args.iter().any(|a| a == "--level=range")
        {
            return Err("combined observer requires explicit deterministic gameplay-combined and shipped range".into());
        }
        if args.iter().filter(|a| a.starts_with("--level=")).count() != 1 {
            return Err("combined requires exactly one shipped-range level selector".into());
        }
        let allowed = [
            "--capture-sequence=gameplay-combined",
            "--capture-hz=30",
            "--capture-hz=60",
            "--capture-native-window",
        ];
        if args.iter().any(|a| {
            (a.starts_with("--capture") && !allowed.contains(&a.as_str()))
                || a.starts_with("--onehand")
                || a == "--demo"
                || a == "--reference-viewport"
                || a.starts_with("--output=")
                || a.starts_with("--viewmodel-time=")
                || a.starts_with("--viewmodel-clip=")
        }) {
            return Err("combined observer rejects alternate capture/fixture routes".into());
        }
        let rates: Vec<_> = args
            .iter()
            .filter_map(|a| a.strip_prefix("--capture-hz="))
            .collect();
        if rates.len() != 1 || !args.iter().any(|a| a == "--capture-native-window") {
            return Err("combined requires one 30/60 Hz rate and native window".into());
        }
        let hz = rates[0].parse::<u32>().map_err(|e| e.to_string())?;
        if ![30, 60].contains(&hz) {
            return Err("combined sampling must be 30 or 60 Hz".into());
        }
        let bindings = trace::bindings(s);
        if ["high", "low", "prone"]
            .iter()
            .any(|k| bindings[*k].is_null())
        {
            return Err("combined route requires all three normally admitted runtime bindings; production high pins remain gated".into());
        }
        for k in ["high", "low"] {
            if (bindings[k]["return_seconds"].as_f64().unwrap_or(0.) - 0.20).abs() > 1e-8 {
                return Err("combined route only covers independently pinned 0.20s returns".into());
            }
        }
        let witness = args
            .iter()
            .find_map(|a| a.strip_prefix("--combined-witness="))
            .ok_or("combined witness required")?
            .to_owned();
        frame_witness::parse_identity(&witness)?;
        let output = PathBuf::from(
            args.iter()
                .find_map(|a| a.strip_prefix("--combined-observer="))
                .ok_or("new combined observer output required")?,
        );
        std::fs::create_dir(&output).map_err(|e| e.to_string())?;
        trace::start(&output.join("observer.jsonl"))?;
        trace::record(
            json!({"kind":"header","input_route":"deterministic_committed_input_replay","sequence":SEQUENCE,"sampling_hz":hz,"fixed_hz":120,
            "render_cadence":{"policy":"nonuniform_committed_boundaries_v1","source_hz":10,"travel_hz":5,"dense_return_hz":hz,"render_on_committed_boundaries":true},
            "build_version":vector_range::BUILD_VERSION,"build_number":vector_range::BUILD_NUMBER,"bindings":bindings,
            "immutable_scene_start":{"position":[-8.6,0.,-3.],"yaw":std::f32::consts::PI,"setup":"combined_replay::start before first update"},
            "frame_witness":witness,"max_seconds":vector_range::combined_replay::MAX_SECONDS,"max_pngs":32,"max_jsonl_bytes":64*1024*1024,"max_journal_records":12000,
            "source_camera_and_rig_basis":"static","source_camera_motion_removal":"none","authored_stance_descent":false,
            "accepted_source1_is_committed_event_not_rendered_frame":true,
            "unsupported_scenarios":["platform_pause","platform_cancel","platform_reset","platform_debug_death","direct_high_low_outgoing_overlap","traversal_tail_active_prone_overlap"],
            "platform_hotkeys_verified":false,"performance_verified":false,"artistic_approval":false}),
        );
        trace::record(trace::state("initial", s));
        trace::check()?;
        Ok(Some(Self {
            replay: Replay::default(),
            output,
            witness,
            hz,
            frame: 0,
            pngs: 0,
            last_marker: String::new(),
            tick: 0,
            cadence: Cadence::new(hz),
        }))
    }
    pub fn target_tick(&self, app_frames: i32) -> u64 {
        if app_frames < 8 {
            0
        } else {
            self.tick + self.cadence.stride()
        }
    }
    pub fn boundary(&self) -> bool {
        self.cadence.boundary()
    }
    pub fn done(&self) -> bool {
        self.replay.done()
    }
    pub fn input(&mut self, s: &Simulation) -> Result<Input, String> {
        let before = format!("{:?}", self.replay.phase());
        match self.replay.input(Observed::from_sim(s)) {
            Ok(input) => {
                let after = format!("{:?}", self.replay.phase());
                if before != after {
                    trace::record(
                        json!({"kind":"phase","from":before,"phase":after,"simulation_time":s.time,"tick":self.tick}),
                    );
                }
                Ok(input)
            }
            Err(error) => {
                trace::record(
                    json!({"kind":"failed","simulation_time":s.time,"phase":before,"error":error}),
                );
                trace::check()?;
                Err(error)
            }
        }
    }
    pub fn step(
        &mut self,
        i: Input,
        started: f64,
        s: &Simulation,
        model: Option<&AuthoredViewmodel>,
        cfg: &Settings,
    ) -> Result<(), String> {
        let mut v = trace::state("step", s);
        v["step_started"] = json!(started);
        v["tick"] = json!(self.tick);
        v["phase"] = json!(format!("{:?}", self.replay.phase()));
        v["input"] = json!({"movement":i.movement.to_array(),"jump":i.jump,"ads":i.ads,"fire":i.fire,"reload":i.reload,"crouch":i.crouch,"prone":i.prone,"sprint":i.sprint,"tactical_sprint":i.tactical_sprint,"sidearm":i.sidearm,"mount":i.mount,"cant":i.cant,"lean":i.lean});
        add_visual(&mut v, s, model, cfg)?;
        trace::record(v);
        trace::check()?;
        self.cadence.commit(
            Observed::from_sim(s),
            self.replay.phase(),
            model.is_some_and(|m| m.low_vault_return_weight().is_some()),
        );
        self.tick += 1;
        Ok(())
    }
    pub fn frame(
        &mut self,
        s: &Simulation,
        cfg: &Settings,
        model: Option<&AuthoredViewmodel>,
        world_eye: glam::Vec3,
        world_forward: glam::Vec3,
        world_up: glam::Vec3,
    ) -> Result<(), String> {
        let mut v = trace::state("frame", s);
        v["sampling_hz"] = json!(self.hz);
        v["app_frame"] = json!(self.frame);
        v["phase"] = json!(format!("{:?}", self.replay.phase()));
        add_visual(&mut v, s, model, cfg)?;
        v["rendered_camera_eye"] = json!(world_eye.to_array());
        v["rendered_camera_forward"] = json!(world_forward.to_array());
        v["rendered_camera_up"] = json!(world_up.to_array());
        v["simulation_tick"] = json!(self.tick);
        let phase = self.replay.phase();
        let interesting = matches!(
            phase,
            Phase::PrimeShot
                | Phase::HighRide
                | Phase::HighReloadTail
                | Phase::ProneFull
                | Phase::ProneAds
                | Phase::ProneShort
                | Phase::ProneReload
                | Phase::LowRide
                | Phase::LowAdsTail
                | Phase::RepeatLowRide
                | Phase::RepeatLowAdsTail
                | Phase::RepeatHighRide
                | Phase::HighAdsTail
                | Phase::Done
        );
        let bucket = v["visual"]["outgoing"]["weight"].as_f64().map(|w| {
            if w < 0.33 {
                0
            } else if w < 0.66 {
                1
            } else {
                2
            }
        });
        let endpoint = s.low_vault_sample().is_some_and(|v| v.source_frame == 64.)
            || s.prone_sample().is_some_and(|v| v.frame == 69.);
        let return_phase = matches!(
            phase,
            Phase::HighReloadTail
                | Phase::LowAdsTail
                | Phase::RepeatLowAdsTail
                | Phase::HighAdsTail
                | Phase::ProneAds
                | Phase::ProneReload
        );
        let interesting = interesting && (!return_phase || bucket.is_some());
        let marker = format!("{phase:?}:{bucket:?}:{endpoint}");
        if interesting && marker != self.last_marker {
            if self.pngs >= 32 {
                return Err("combined native PNG bound exceeded".into());
            }
            let (width, height) = vector_range::platform::runtime::framebuffer_size();
            if width > 1440 || height > 900 {
                return Err("combined capture exceeds extent budget".into());
            }
            let info = backend_info()?;
            let name = format!("{:04}.png", self.pngs);
            let metadata = json!({"capture":"native window","width":width,"height":height,"requested":info.requested,"backend":info.backend,"adapter":info.adapter,"frame_witness":{"schema":frame_witness::SCHEMA,"frame_index":self.pngs,"capture_identity":self.witness}});
            std::fs::write(
                self.output.join(format!("{name}.json")),
                metadata.to_string(),
            )
            .map_err(|e| e.to_string())?;
            capture_png_with_frame_witness(
                None,
                self.output.join(&name),
                self.pngs,
                frame_witness::parse_identity(&self.witness)?,
            );
            v["png"] = json!(name);
            v["capture_index"] = json!(self.pngs);
            self.pngs += 1;
            self.last_marker = marker;
        }
        trace::record(v);
        trace::check()?;
        self.frame += 1;
        Ok(())
    }
    pub fn finish(self, s: &Simulation) -> Result<(), String> {
        let mut v = trace::state("finished", s);
        v["completed"] = json!(self.done());
        v["accepted_counts_high_low_prone"] = json!(self.replay.counts());
        v["pngs"] = json!(self.pngs);
        trace::record(v);
        trace::check()?;
        if !self.done() {
            return Err("combined replay exited before route completion".into());
        }
        Ok(())
    }
}
fn add_visual(
    v: &mut serde_json::Value,
    s: &Simulation,
    model: Option<&AuthoredViewmodel>,
    cfg: &Settings,
) -> Result<(), String> {
    v["visual"] = model
        .ok_or("combined renderer unavailable")?
        .combined_observation(s.time)?;
    let base_forward = s.player.direction();
    let base_up = s.player.camera_up(cfg.action.lean_roll);
    let (forward, up) =
        vector_range::authored_prone::camera_axes(base_forward, base_up, s.prone_camera_sample());
    v["camera_base_forward"] = json!(base_forward.to_array());
    v["camera_base_up"] = json!(base_up.to_array());
    v["camera_forward"] = json!(forward.to_array());
    v["camera_up"] = json!(up.to_array());
    Ok(())
}
