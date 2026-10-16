//! Native-app observer with explicit platform / deterministic ordinary-Input routes.
//! Neither route writes simulation state, source clocks or outgoing durations.
use crate::authored_viewmodel::AuthoredViewmodel;
use serde_json::json;
use std::path::PathBuf;
use vector_range::{
    draw::{
        facade::{backend_info, capture_png_with_frame_witness},
        frame_witness,
    },
    high_mantle_observer as trace,
    settings::Settings,
    sim::{Input, Simulation},
};

pub struct Capture {
    sampling_hz: Option<u32>,
    output: PathBuf,
    witness: String,
    index: u32,
    frame: u64,
    next_source: f64,
    next_return: f32,
    seen_high: bool,
    captured_clear: bool,
    captured_ads: bool,
}
impl Capture {
    pub fn open(args: &[String], sim: &Simulation) -> Result<Option<Self>, String> {
        let deterministic = args.iter().any(|a| a == "--onehand-deterministic");
        let high_sequence = args
            .iter()
            .any(|a| a == "--capture-sequence=gameplay-high-onto");
        if deterministic != high_sequence
            || (deterministic && !args.iter().any(|a| a.starts_with("--onehand-observer=")))
        {
            return Err(
                "deterministic high-ONTO requires its explicit sequence and bounded observer"
                    .into(),
            );
        }
        let Some(path) = args
            .iter()
            .find_map(|a| a.strip_prefix("--onehand-observer="))
        else {
            return Ok(None);
        };
        let allowed_capture = [
            "--capture-sequence=gameplay-high-onto",
            "--capture-hz=30",
            "--capture-hz=60",
            "--capture-native-window",
        ];
        if args.iter().any(|a| {
            (a.starts_with("--capture")
                && (!deterministic || !allowed_capture.contains(&a.as_str())))
                || a == "--demo"
                || a == "--reference-viewport"
        }) {
            return Err("one-hand observer requires ordinary native-window input, no replay/demo/capture flags".into());
        }
        if !args.iter().any(|a| a == "--level=range") {
            return Err("one-hand observer requires explicit shipped range".into());
        }
        let sampling_hz = if deterministic {
            let rates: Vec<_> = args
                .iter()
                .filter_map(|a| a.strip_prefix("--capture-hz="))
                .collect();
            if rates.len() != 1 || !args.iter().any(|a| a == "--capture-native-window") {
                return Err(
                    "deterministic observer requires one explicit 30/60 Hz rate and native window"
                        .into(),
                );
            }
            Some(rates[0].parse::<u32>().map_err(|e| e.to_string())?)
        } else {
            None
        };
        if deterministic
            && !sim
                .high_mantle_binding()
                .is_some_and(|b| (b.return_seconds() - 0.20).abs() < 1e-8)
        {
            return Err("deterministic fixture requires admitted high-ONTO and the independently pinned 0.20s return".into());
        }
        let witness = args
            .iter()
            .find_map(|a| a.strip_prefix("--onehand-witness="))
            .ok_or("onehand-witness is required")?
            .to_owned();
        frame_witness::parse_identity(&witness)?;
        let output = PathBuf::from(path);
        std::fs::create_dir(&output).map_err(|e| format!("new observer directory: {e}"))?;
        trace::start(&output.join("observer.jsonl"))?;
        trace::record(
            json!({"kind":"header","input_route":if deterministic {"deterministic_ordinary_input"} else {"platform"},
            "sampling_hz":sampling_hz,"sequence":if deterministic {Some("gameplay-high-onto")} else {None},
            "immutable_scene_start":if deterministic {Some(json!({"position":[-8.6,0.,-3.],"yaw":std::f32::consts::PI,
                "setup":"existing traversal_replay::start before first update","existing_block_center":[-10.,0.9,-3.],"existing_block_size":[2.,1.8,2.]}))} else {None},
            "scene":"range","source_camera_and_rig_basis":"static","source_camera_motion_removal":"none",
            "authored_stance_descent":false,"source_range":[1,96],"reference_range_half_open":[7787,7883],
            "native_seconds":vector_range::authored_high_mantle::NATIVE_SECONDS,
            "frame_witness":witness,"pngs_are_native_window":true,"max_pngs":12,"max_jsonl_bytes":16*1024*1024,
            "accepted_source1_is_committed_event_not_rendered_frame":true}),
        );
        trace::event("initial", sim);
        trace::check()?;
        Ok(Some(Self {
            sampling_hz,
            output,
            witness,
            index: 0,
            frame: 0,
            next_source: 1.,
            next_return: 0.,
            seen_high: false,
            captured_clear: false,
            captured_ads: false,
        }))
    }
    pub fn deterministic(&self) -> bool {
        self.sampling_hz.is_some()
    }
    pub fn step(
        input: Input,
        started: f64,
        sim: &Simulation,
        model: Option<&AuthoredViewmodel>,
    ) -> Result<(), String> {
        if !trace::enabled() {
            return Ok(());
        }
        let mut row = trace::state("step", sim);
        row["step_started"] = json!(started);
        row["input"] = json!({"movement":input.movement.to_array(),"jump":input.jump,"ads":input.ads,
            "fire":input.fire,"reload":input.reload,"sprint":input.sprint,"tactical_sprint":input.tactical_sprint,"crouch":input.crouch,
            "prone":input.prone,"sidearm":input.sidearm,"mount":input.mount,"cant":input.cant,"lean":input.lean});
        add_visual(&mut row, model);
        trace::record(row);
        trace::check()
    }
    pub fn frame(
        &mut self,
        sim: &Simulation,
        cfg: &Settings,
        model: Option<&AuthoredViewmodel>,
        active: bool,
    ) -> Result<(), String> {
        let mut row = trace::state("frame", sim);
        row["sampling_hz"] = json!(self.sampling_hz);
        row["app_active"] = json!(active);
        row["app_frame"] = json!(self.frame);
        row["look_sensitivity_degrees_per_pixel"] = json!(cfg.sensitivity);
        let (forward, up) = vector_range::authored_prone::camera_axes(
            sim.player.direction(),
            sim.player.camera_up(cfg.action.lean_roll),
            sim.prone_camera_sample(),
        );
        row["camera_forward"] = json!(forward.to_array());
        row["camera_up"] = json!(up.to_array());
        row["prone_camera_active"] = json!(sim.prone_camera_sample().is_some());
        add_visual(&mut row, model);
        // At most 12 PNGs, selected at observed boundaries (never fabricated
        // times): baseline, native milestones, return thirds, clear and live ADS.
        let mut capture = self.frame == 0;
        if let Some(h) = sim.high_mantle_presentation() {
            self.seen_high = true;
            if let Some(r) = h.outgoing {
                let weight = r.weight(sim.time);
                if weight >= self.next_return {
                    capture = true;
                    self.next_return = if weight < 0.33 {
                        0.33
                    } else if weight < 0.66 {
                        0.66
                    } else {
                        1.01
                    };
                }
            } else if h.sample.source_frame >= self.next_source {
                capture = true;
                self.next_source = if h.sample.source_frame < 24. {
                    24.
                } else if h.sample.source_frame < 48. {
                    48.
                } else if h.sample.source_frame < 72. {
                    72.
                } else {
                    97.
                };
            }
        } else if self.seen_high && !self.captured_clear {
            capture = true;
            self.captured_clear = true;
        } else if self.seen_high
            && !self.captured_ads
            && model.is_some_and(|m| m.visual_ads_amount() > 0.95)
        {
            capture = true;
            self.captured_ads = true;
        }
        if capture {
            if self.index >= 12 {
                return Err("one-hand observer PNG bound exceeded".into());
            }
            let name = format!("{:04}.png", self.index);
            let path = self.output.join(&name);
            let info = backend_info()?;
            let (width, height) = vector_range::platform::runtime::framebuffer_size();
            if width > 1440 || height > 900 {
                return Err("one-hand observer extent exceeds reserved disk budget".into());
            }
            let metadata = json!({"capture":"native window","width":width,"height":height,
                "requested":info.requested,"backend":info.backend,"adapter":info.adapter,
                "frame_witness":{"schema":frame_witness::SCHEMA,"frame_index":self.index,"capture_identity":self.witness}});
            std::fs::write(
                self.output.join(format!("{name}.json")),
                metadata.to_string(),
            )
            .map_err(|e| e.to_string())?;
            capture_png_with_frame_witness(
                None,
                &path,
                self.index,
                frame_witness::parse_identity(&self.witness)?,
            );
            row["png"] = json!(name);
            row["capture_index"] = json!(self.index);
            self.index += 1;
        }
        trace::record(row);
        trace::check()?;
        self.frame += 1;
        Ok(())
    }
    pub fn finish(self, sim: &Simulation) -> Result<(), String> {
        let mut row = trace::state("finished", sim);
        row["pngs"] = json!(self.index);
        trace::record(row);
        trace::check()
    }
}
fn add_visual(row: &mut serde_json::Value, model: Option<&AuthoredViewmodel>) {
    row["route"] = json!(model.map_or("unavailable", |m| m.presentation_route()));
    row["renderer_failed"] = json!(model.is_none_or(|m| m.error().is_some()));
    row["visual_ads"] = json!(model.map_or(0., |m| m.visual_ads_amount()));
    row["procedural_weight"] = json!(model.map_or(1., |m| m.authored_procedural_weight()));
    row["render_return_weight"] = json!(model.and_then(|m| m.high_mantle_return_weight()));
    row["walk_seconds"] = json!(model.and_then(|m| m.walk_sample()));
    row["walk_weight"] = json!(model.map_or(0., |m| m.walk_weight()));
    row["underlying_pose_crc32"] = json!(model.and_then(|m| m.pose_crc32()));
    row["weapon_anchor"] = json!(model
        .and_then(|m| m.presented_anchor())
        .map(|v| v.to_array()));
}
