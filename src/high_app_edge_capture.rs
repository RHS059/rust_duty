//! Narrow app-input-edge witness. Ordinary real-time app handlers own every
//! update and interruption; this module observes and supplies control edges only.
use crate::authored_viewmodel::AuthoredViewmodel;
use serde_json::{json, Value};
use std::{collections::HashSet, path::PathBuf};
use vector_range::{
    draw::{
        facade::{backend_info, capture_png_with_frame_witness},
        frame_witness,
    },
    high_app_edge_input::{
        renderer_status_valid, Case, Driver, Options, MAX_BYTES, MAX_RECORDS, MAX_SECONDS, RECIPE,
    },
    high_mantle_observer as trace,
    platform::input::{InputFrame, KeyCode, MouseButton},
    session::SessionTransition,
    settings::Settings,
    sim::{Input, Simulation},
};

pub struct Capture {
    options: Options,
    driver: Driver,
    output: PathBuf,
    frame: u64,
    tick: u64,
    pngs: u32,
    markers: HashSet<String>,
}
impl Capture {
    pub fn open(
        options: Options,
        sim: &Simulation,
        model: Option<&AuthoredViewmodel>,
    ) -> Result<Self, String> {
        let binding = sim
            .high_mantle_binding()
            .ok_or("app-edge requires normally admitted high binding")?;
        let model = model.ok_or("app-edge requires admitted authored renderer")?;
        if !renderer_status_valid(model.warning(), model.error().is_some())
            || model.high_mantle_binding().as_ref() != Some(binding)
            || (binding.return_seconds() - 0.20).abs() > 1e-8
            || sim.time != 0.
            || sim.player.position != vector_range::high_app_edge_input::start().0
        {
            return Err("app-edge requires valid matched renderer/binding, 0.20s return and declared initial spawn".into());
        }
        let output = PathBuf::from(&options.output);
        std::fs::create_dir(&output).map_err(|e| format!("new app-edge output: {e}"))?;
        trace::start_bounded(
            &output.join("observer.jsonl"),
            MAX_RECORDS,
            MAX_BYTES,
            Some(MAX_SECONDS),
        )?;
        trace::app_edge_frame(0);
        trace::record(
            json!({"kind":"header", "diagnostic_schema":"rust-duty-app-edge/v3",
            "recipe":RECIPE,"case":options.case.name(),"input_route":"app_input_edge_fixture",
            "ordinary_session_and_hotkey_handlers":true,"os_input_verified":false,
            "os_focus_verified":false,"focus_policy":"existing_platform_signal_or_fallback",
            "combat_death_verified":false,"capture_mode":false,"clock":"real_wall_fixed_120hz",
            "contract_sha256":options.contract,"frame_witness":options.witness,
            "build_version":vector_range::BUILD_VERSION,"build_number":vector_range::BUILD_NUMBER,
            "max_seconds":MAX_SECONDS,"max_records":MAX_RECORDS,"max_jsonl_bytes":MAX_BYTES,
            "max_pngs":options.case.png_limit(),"max_extent":[1440,900],
            "binding":trace::state("header_binding",sim)["binding"],
            "immutable_scene_start":{"position":[-8.6,0.,-3.],"yaw":std::f32::consts::PI},
            "source_range":[1,96],"native_seconds":vector_range::authored_high_mantle::NATIVE_SECONDS,
            "return_seconds":0.20,"source_camera_and_rig_basis":"static",
            "source_camera_motion_removal":"none","authored_stance_descent":false,
            "native_capture_verified":false,"artistic_approval":false,"performance_verified":false}),
        );
        trace::event("initial", sim);
        trace::check()?;
        Ok(Self {
            driver: Driver::new(options.case),
            options,
            output,
            frame: 0,
            tick: 0,
            pngs: 0,
            markers: HashSet::new(),
        })
    }
    pub fn input(&mut self, sim: &Simulation, active: bool) -> Result<InputFrame, String> {
        trace::app_edge_frame(self.frame);
        let frame = self.driver.next(sim, active)?;
        let mut row = trace::state("fixture_input", sim);
        row["phase"] = json!(self.driver.phase());
        row["session_active_before"] = json!(active);
        row["edges"] = edges(&frame);
        trace::record(row);
        trace::check()?;
        Ok(frame)
    }
    pub fn session(
        &self,
        sim: &Simulation,
        frame: &InputFrame,
        transition: SessionTransition,
        frame_started: f64,
        raw_dt: f64,
        blocked: bool,
    ) -> Result<(), String> {
        let mut row = trace::state("app_input", sim);
        row["edges"] = edges(frame);
        row["raw_dt"] = json!(raw_dt);
        row["frame_started"] = json!(frame_started);
        row["blocked"] = json!(blocked);
        row["transition"] = json!({"active":transition.active,"paused":transition.paused,
            "resumed":transition.resumed,"discard_timing":transition.discard_timing,
            "hitch":transition.hitch});
        row["focus"] = json!({"unfocused":frame.focus.unfocused,"changed":frame.focus.changed,
            "native_supported":frame.focus.native_supported});
        trace::record(row);
        trace::check()?;
        if blocked
            || frame.focus.unfocused
            || frame.focus.changed
            || !raw_dt.is_finite()
            || raw_dt < 0.
        {
            return Err("app-edge actual input/session/time admission interrupted".into());
        }
        Ok(())
    }
    pub fn clock(&self, sim: &Simulation, dt: f64, steps: usize) -> Result<(), String> {
        let mut row = trace::state("app_clock", sim);
        row["simulation_dt"] = json!(dt);
        row["planned_steps"] = json!(steps);
        trace::record(row);
        trace::check()
    }
    pub fn step(
        &mut self,
        input: Input,
        started: f64,
        sim: &Simulation,
        model: Option<&AuthoredViewmodel>,
        cfg: &Settings,
    ) -> Result<(), String> {
        self.tick += 1;
        let mut row = trace::state("app_step", sim);
        row["tick"] = json!(self.tick);
        row["step_started"] = json!(started);
        row["input"] = json!({"movement":input.movement.to_array(),"jump":input.jump,
            "reload":input.reload,"ads":input.ads,"fire":input.fire,"crouch":input.crouch,
            "prone":input.prone,"sprint":input.sprint,"tactical_sprint":input.tactical_sprint,
            "mount":input.mount,"sidearm":input.sidearm,"lean":input.lean,"cant":input.cant});
        add_visual(&mut row, sim, model, cfg)?;
        trace::record(row);
        trace::check()
    }
    #[allow(clippy::too_many_arguments)]
    pub fn frame(
        &mut self,
        sim: &Simulation,
        cfg: &Settings,
        model: Option<&AuthoredViewmodel>,
        active: bool,
        eye: glam::Vec3,
        forward: glam::Vec3,
        up: glam::Vec3,
    ) -> Result<(), String> {
        let mut row = trace::state("app_frame", sim);
        row["tick"] = json!(self.tick);
        row["phase"] = json!(self.driver.phase());
        row["app_active"] = json!(active);
        add_visual(&mut row, sim, model, cfg)?;
        row["rendered_camera_eye"] = json!(eye.to_array());
        row["rendered_camera_forward"] = json!(forward.to_array());
        row["rendered_camera_up"] = json!(up.to_array());
        let high = sim.high_mantle_presentation();
        let marker = if high.is_some_and(|h| h.outgoing.is_none() && h.sample.seconds >= 0.25)
            && !self.markers.contains("native")
        {
            Some("native")
        } else if self.options.case == Case::Pause {
            if !active && high.is_some() && !self.markers.contains("paused") {
                Some("paused")
            } else if high
                .and_then(|h| h.outgoing)
                .is_some_and(|r| r.weight(sim.time) > 0. && r.weight(sim.time) < 0.5)
                && !self.markers.contains("tail_early")
            {
                Some("tail_early")
            } else if high
                .and_then(|h| h.outgoing)
                .is_some_and(|r| r.weight(sim.time) >= 0.5 && r.weight(sim.time) < 1.)
                && !self.markers.contains("tail_late")
            {
                Some("tail_late")
            } else if high.is_none()
                && self.markers.contains("paused")
                && !self.markers.contains("clear")
            {
                Some("clear")
            } else if high.is_none()
                && self.markers.contains("clear")
                && !self.markers.contains("ads")
                && model.is_some_and(|m| m.visual_ads_amount() > 0.95)
            {
                Some("ads")
            } else {
                None
            }
        } else if high.is_none()
            && self.markers.contains("native")
            && !self.markers.contains("after")
        {
            Some("after")
        } else if self.driver.done() && !self.markers.contains("terminal") {
            Some("terminal")
        } else {
            None
        };
        if let Some(marker) = marker {
            if self.pngs >= self.options.case.png_limit() {
                return Err("app-edge PNG bound exceeded".into());
            }
            let info = backend_info()?;
            let (width, height) = vector_range::platform::runtime::framebuffer_size();
            if width < 64 || height < 22 || width > 1440 || height > 900 {
                return Err("app-edge framebuffer extent outside reservation".into());
            }
            let name = format!("{:04}.png", self.pngs);
            let metadata = json!({"capture":"native window","width":width,"height":height,
                "requested":info.requested,"backend":info.backend,"adapter":info.adapter,
                "frame_witness":{"schema":frame_witness::SCHEMA,"frame_index":self.pngs,
                    "capture_identity":self.options.witness}});
            std::fs::write(
                self.output.join(format!("{name}.json")),
                metadata.to_string(),
            )
            .map_err(|e| e.to_string())?;
            capture_png_with_frame_witness(
                None,
                &self.output.join(&name),
                self.pngs,
                frame_witness::parse_identity(&self.options.witness)?,
            );
            row["png"] = json!(name);
            row["capture_index"] = json!(self.pngs);
            row["marker"] = json!(marker);
            self.pngs += 1;
            self.markers.insert(marker.into());
        }
        trace::record(row);
        trace::check()?;
        self.frame += 1;
        Ok(())
    }
    pub fn done(&self) -> bool {
        self.driver.done()
    }
    pub fn finish(self, sim: &Simulation) -> Result<(), String> {
        let complete = self.driver.done() && self.pngs == self.options.case.png_limit();
        let mut row = trace::state("finished", sim);
        row["completed"] = json!(complete);
        row["tick"] = json!(self.tick);
        row["pngs"] = json!(self.pngs);
        trace::record(row);
        trace::check()?;
        if !complete {
            return Err("app-edge case or required native raster coverage incomplete".into());
        }
        Ok(())
    }
}
fn edges(f: &InputFrame) -> Value {
    let keys = [
        KeyCode::W,
        KeyCode::D,
        KeyCode::Space,
        KeyCode::Escape,
        KeyCode::Enter,
        KeyCode::F2,
        KeyCode::F9,
    ];
    json!({"keys":keys.iter().map(|k|json!({"key":format!("{k:?}"),"down":f.is_key_down(*k),
        "pressed":f.is_key_pressed(*k),"released":f.is_key_released(*k)})).collect::<Vec<_>>(),
        "right_mouse":{"down":f.is_mouse_button_down(MouseButton::Right),
            "pressed":f.is_mouse_button_pressed(MouseButton::Right),"released":f.is_mouse_button_released(MouseButton::Right)},
        "movement":f.movement_axes(),"mouse_delta":f.mouse_delta})
}
fn add_visual(
    row: &mut Value,
    sim: &Simulation,
    model: Option<&AuthoredViewmodel>,
    cfg: &Settings,
) -> Result<(), String> {
    let model = model.ok_or("app-edge renderer unavailable")?;
    row["visual"] = model.combined_observation(sim.time)?;
    row["high_pose_sampling"] = json!(model.app_edge_high_pose_observation());
    let (forward, up) = vector_range::authored_prone::camera_axes(
        sim.player.direction(),
        sim.player.camera_up(cfg.action.lean_roll),
        sim.prone_camera_sample(),
    );
    row["camera_forward"] = json!(forward.to_array());
    row["camera_up"] = json!(up.to_array());
    if !renderer_status_valid(model.warning(), model.error().is_some())
        || sim.high_mantle_binding().is_none()
    {
        return Err("app-edge renderer/binding became invalid".into());
    }
    Ok(())
}
