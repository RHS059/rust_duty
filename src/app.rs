use crate::viewmodel_draw::*;
use crate::world_draw::{
    draw_body_placeholder, grid_texture, register_supply, supply_focus, world,
};
use crate::{authored_viewmodel, sound, weapon_model};
use std::io::Write;
use vector_range::draw::facade::*;
use vector_range::frame_performance::{BoundaryReason, Eligibility};
use vector_range::frame_performance_session as frame_trace;
use vector_range::hud::*;
use vector_range::platform::input::{KeyCode, MouseButton};
use vector_range::platform::runtime::{
    get_fps, get_time, mouse_delta_position, mouse_position, next_frame, screen_height,
    screen_width, set_cursor_grab, set_fullscreen, show_mouse,
};
use vector_range::scene_lighting::SceneLighting;
use vector_range::{
    action::{ActionEventKind, Rejection},
    body_presentation::{BodyPresentation, BodyTuning},
    weapon_sway::{LookSway, SwayTuning},
};
use vector_range::{
    clock::FixedClock,
    control::{ActionLatch, ControlMode, ControlState, IntentLatch},
};
use vector_range::{game_update, pause_menu};
use vector_range::{
    muzzle_fx::MuzzleFx,
    settings::Settings,
    sim::{Input, Shot, Simulation, FIXED_DT},
};
struct Trace {
    shot: Shot,
    life: f32,
}
struct Impact {
    point: Vec3,
    life: f32,
    target: bool,
}
pub(crate) async fn run(ui_theme: Option<std::path::PathBuf>) -> Result<(), String> {
    let args: Vec<String> = std::env::args().collect();
    let executable =
        std::env::current_exe().unwrap_or_else(|_| std::path::PathBuf::from("vector-range.exe"));
    let authored_executable =
        match rust_duty_launcher::game::managed_asset_executable(vector_range::BUILD_VERSION) {
            Ok(path) => path.unwrap_or_else(|| executable.clone()),
            Err(error) => {
                // No healthy startup acknowledgement: the existing helper will
                // roll back the executable and active version together.
                eprintln!("Managed game assets could not be verified: {error}");
                std::process::exit(1);
            }
        };
    let theme_path = resolve_theme_path(
        ui_theme.as_deref(),
        &executable,
        &authored_executable,
        |path| path.exists(),
    );
    let report_theme_error = ui_theme.is_some() || theme_path.exists();
    // Remember even a missing default path so F7 can load a newly created file.
    let theme_error = vector_range::ui_theme::load_theme(&theme_path)
        .err()
        .filter(|_| report_theme_error)
        .map(|error| {
            eprintln!("UI theme: {error}");
            format!("UI theme: {error}")
        });
    // Deterministic capture jobs never contact the release channel. Ordinary
    // double-click launches always start the background checker automatically.
    let update_enabled = !args
        .iter()
        .any(|arg| arg == "--no-update" || arg == "--demo" || arg.starts_with("--capture"));
    let mut game_update = game_update::UpdatePanel::start(update_enabled);
    // Present the same-window startup screen before audio/assets are loaded,
    // including fast checks that might otherwise finish before the first frame.
    if update_enabled {
        game_update.draw(true);
        next_frame().await?;
    }
    let framing = ViewmodelFraming::from_args(&args);
    let control_mode = if args.iter().any(|s| s == "--hold-controls") {
        ControlMode::Hold
    } else {
        ControlMode::Toggle
    };
    let mut controls = ControlState::new(control_mode);
    let profile = args
        .iter()
        .find_map(|s| s.strip_prefix("--profile="))
        .unwrap_or("m4a1");
    let base = match profile {
        "m4a1" => Settings::m4_candidate(),
        "kestrel" => Settings::default(),
        other => {
            return Err(format!("Unknown profile {other}; use m4a1 or kestrel"));
        }
    };
    let settings_path = args
        .iter()
        .find_map(|s| s.strip_prefix("--settings="))
        .unwrap_or(if profile == "kestrel" {
            "profiles/kestrel.cfg"
        } else {
            "settings.cfg"
        });
    let weapon_label = if profile == "m4a1" {
        "M4 / CANDIDATE"
    } else {
        "KESTREL-30 / AUTO"
    };
    // Both shipped rifles are 5.56-class. --caliber-mm= retunes the procedural flash.
    let caliber_mm = args
        .iter()
        .find_map(|s| s.strip_prefix("--caliber-mm="))
        .and_then(|s| s.parse::<f32>().ok())
        .filter(|mm| mm.is_finite())
        .unwrap_or(5.56);
    let mut cfg = Settings::load_with_base(settings_path, base.clone());
    let weapon_id = args
        .iter()
        .find_map(|arg| arg.strip_prefix("--weapon-id="))
        .unwrap_or(if args.iter().any(|arg| arg == "--procedural-weapon") {
            "kestrel30"
        } else {
            "hk416a5"
        });
    if !vector_range::settings::valid_weapon_id(weapon_id) {
        return Err(
            "Weapon ID must contain 1-80 ASCII letters, digits, underscores or hyphens".into(),
        );
    }
    let mut pause_menu = pause_menu::PauseMenu::default();
    let mut audio = sound::SoundBank::new().await;
    let mut step_distance = 0.;
    let mut was_reloading = false;
    let mut animation_state = vector_range::view_animation::ViewAnimation::default();
    let mut locomotion_state =
        vector_range::locomotion_presentation::LocomotionPresentation::default();
    let mut sim = Simulation::new();
    let mut startup_notice = theme_error;
    {
        // Authored action clips retime gameplay gates; unavailable slots keep
        // labeled placeholder timing. A broken binding is reported, not hidden.
        let manifest = args
            .iter()
            .find_map(|arg| arg.strip_prefix("--animation-manifest="))
            .map(std::path::PathBuf::from)
            .unwrap_or_else(|| {
                executable
                    .parent()
                    .unwrap_or(std::path::Path::new("."))
                    .join("assets/animations.cfg")
            });
        if manifest.exists() {
            let bound = vector_range::animation_manifest::AnimationManifest::load(&manifest)
                .and_then(|m| {
                    m.bind_action_timings(&mut sim.timings, |asset, clip| {
                        let set = vector_range::viewmodel_animation::AnimationSet::load(asset)
                            .map_err(|e| format!("{}: {e}", asset.display()))?;
                        set.clips()
                            .iter()
                            .find(|c| c.name == clip)
                            .map(|c| c.duration())
                            .ok_or_else(|| format!("missing action clip {clip}"))
                    })
                });
            if let Err(error) = bound {
                eprintln!("Action clip timings: {error}");
                startup_notice = Some(format!("Action clips: {error}"));
            }
        }
    }
    let mut action_latch = ActionLatch::default();
    let mut look_sway = LookSway::default();
    let sway_tuning = SwayTuning::default();
    let mut body = BodyPresentation::default();
    let body_tuning = BodyTuning::default();
    let mut supply = vector_range::ammo_supply::AmmoSupply::default();
    register_supply(&mut sim, &supply);
    let texture = grid_texture();
    let target = render_target_ex(
        if framing.reference { 960 } else { 1440 },
        if framing.reference { 540 } else { 900 },
        RenderTargetParams { depth: true },
    )?;
    let mut initial = true;
    let mut session = vector_range::session::SessionController::default();
    let mut focus_input = vector_range::session::FocusInput::new();
    let mut cursor_captured = false;
    let mut debug = false;
    let mut fullscreen = false;
    let mut clock = FixedClock::default();
    let mut last_frame = get_time();
    let mut traces: Vec<Trace> = Vec::new();
    let mut impacts: Vec<Impact> = Vec::new();
    let mut muzzle_fx = MuzzleFx::default();
    muzzle_fx.set_caliber_mm(caliber_mm);
    let mut hit_timer = 0.;
    let mut head = false;
    let mut notice = startup_notice.clone().unwrap_or_default();
    let mut notice_timer = if startup_notice.is_some() { 6. } else { 0. };
    let mut recording: Option<crate::telemetry_export::LocalExport> = None;
    let mut telemetry_status = String::new();
    let mut telemetry_csv_error: Option<String> = None;
    let mut frame_trace_sequence = 0_u64;
    let mut record_clock = 0.;
    let mut intents = IntentLatch::default();
    let explicit = args.iter().find_map(|s| s.strip_prefix("--weapon-asset="));
    let model_source = vector_range::asset_path::resolve_weapon(
        &executable,
        explicit.map(std::path::Path::new),
        args.iter().any(|s| s == "--procedural-weapon"),
        vector_range::EMBEDDED_WEAPON.is_some(),
    );
    let mut model_error = None;
    let explicit_viewmodel = args
        .iter()
        .find_map(|s| s.strip_prefix("--viewmodel-asset="));
    let authored_path = vector_range::asset_path::resolve_viewmodel(
        &authored_executable,
        explicit_viewmodel.map(std::path::Path::new),
        args.iter().any(|s| {
            s == "--procedural-weapon"
                || s.starts_with("--weapon-asset=")
                || s.starts_with("--arms-asset=")
        }),
    )
    .or_else(|| {
        args.iter()
            .find_map(|arg| arg.strip_prefix("--animation-manifest="))
            .map(std::path::PathBuf::from)
    });
    let authored_clip = args
        .iter()
        .find_map(|s| s.strip_prefix("--viewmodel-clip="))
        .unwrap_or(if explicit_viewmodel.is_none() {
            "locomotion"
        } else {
            "neutral"
        });
    let authored_time = args
        .iter()
        .find_map(|s| s.strip_prefix("--viewmodel-time="));
    let mut authored = if let Some(path) = authored_path.as_ref() {
        let time = authored_time
            .map(|value| {
                value
                    .parse::<f32>()
                    .map_err(|_| "invalid --viewmodel-time".to_string())
            })
            .transpose();
        match time.and_then(|time| {
            let path = path
                .to_str()
                .ok_or_else(|| "viewmodel path is not valid Unicode".to_string())?;
            if authored_clip == "locomotion" && time.is_none() {
                let manifest = args
                    .iter()
                    .find_map(|arg| arg.strip_prefix("--animation-manifest="))
                    .map(std::path::PathBuf::from)
                    .unwrap_or_else(|| {
                        authored_executable
                            .parent()
                            .unwrap_or(std::path::Path::new("."))
                            .join("assets/animations.cfg")
                    });
                authored_viewmodel::AuthoredViewmodel::load_manifest(&manifest)
            } else {
                authored_viewmodel::AuthoredViewmodel::load(path, authored_clip, time)
            }
        }) {
            Ok(viewmodel) => Some(viewmodel),
            Err(error) => {
                let message = format!("Authored viewmodel could not load: {error}");
                eprintln!("{message}");
                model_error = Some(message);
                None
            }
        }
    } else {
        None
    };
    let model_missing = authored_path.is_none()
        && matches!(
            &model_source,
            vector_range::asset_path::WeaponSource::Missing(_)
        );
    let mut model = if authored_path.is_some() {
        None
    } else {
        match vector_range::asset_path::load_weapon(&model_source, vector_range::EMBEDDED_WEAPON) {
            Ok(Some(asset)) => {
                eprintln!("Loaded VRMESH01 weapon: {} mesh parts", asset.meshes.len());
                Some(weapon_model::WeaponModel::from_asset(asset))
            }
            Err(error) => {
                let message = format!("Weapon asset could not load: {error}");
                eprintln!("{message}; source: {model_source:?}");
                model_error = Some(message);
                None
            }
            Ok(None) => None,
        }
    };
    let arms_path = if authored_path.is_some() {
        None
    } else {
        args.iter()
            .find_map(|s| s.strip_prefix("--arms-asset="))
            .map(std::path::PathBuf::from)
            .or_else(|| {
                executable
                    .parent()
                    .map(|p| p.join("assets/arms/first-person.vrs"))
                    .filter(|p| p.exists())
            })
    };
    let mut arms = if let Some(path) = arms_path {
        match vector_range::skinned_asset::SkinnedAsset::load(&path)
            .map_err(|error| error.to_string())
            .and_then(vector_range::arms::ArmModel::new)
        {
            Ok(asset) => Some(asset),
            Err(error) => {
                let message = format!("Arm asset could not load: {error}");
                eprintln!("{message}; path: {}", path.display());
                model_error = Some(message);
                None
            }
        }
    } else {
        None
    };
    let capture_lighting = args.iter().any(|s| s == "--capture-lighting");
    let capture_angle = |prefix: &str, default: f32| {
        args.iter()
            .find_map(|arg| arg.strip_prefix(prefix))
            .and_then(|value| value.parse::<f32>().ok())
            .filter(|v| v.is_finite())
            .unwrap_or(default)
            .to_radians()
    };
    let lighting_yaw = capture_angle("--capture-yaw=", -90.);
    let lighting_pitch = capture_angle("--capture-pitch=", 0.).clamp(-1.5, 1.5);
    let capture = args.iter().any(|s| s.starts_with("--capture"));
    let capture_ads = args.iter().any(|s| s == "--capture-ads");
    let capture_supply = args.iter().any(|s| s == "--capture-supply");
    let capture_fire = args.iter().any(|s| s == "--capture-fire");
    let capture_reload = args
        .iter()
        .find_map(|a| a.strip_prefix("--capture-reload="))
        .and_then(|s| s.parse::<f32>().ok())
        .filter(|v| v.is_finite() && (0. ..=1.).contains(v));
    let mut locomotion_capture_tick = 0_u64;
    let capture_sequence = args
        .iter()
        .find_map(|a| a.strip_prefix("--capture-sequence="))
        .filter(|s| {
            matches!(
                *s,
                "tactical"
                    | "empty"
                    | "ads"
                    | "locomotion"
                    | "gameplay-reload"
                    | "gameplay-walk"
                    | "gameplay-ads"
                    | "gameplay-layered"
                    | "gameplay-return"
                    | "gameplay-jump"
            ) || vector_range::traversal_replay::SEQUENCES.contains(s)
        });
    let traversal_capture =
        capture_sequence.filter(|s| vector_range::traversal_replay::SEQUENCES.contains(s));
    let gameplay_capture = traversal_capture.is_some()
        || matches!(
            capture_sequence,
            Some(
                "gameplay-reload"
                    | "gameplay-walk"
                    | "gameplay-ads"
                    | "gameplay-layered"
                    | "gameplay-return"
                    | "gameplay-jump"
            )
        );
    let mut gameplay_reload_issued = false;
    let mut gameplay_capture_tick = 0_u64;
    let capture_empty =
        args.iter().any(|s| s == "--capture-empty") || capture_sequence == Some("empty");
    let capture_hz = args
        .iter()
        .find_map(|arg| arg.strip_prefix("--capture-hz="))
        .map(|hz| match hz {
            "30" => 30.,
            "60" => 60.,
            _ => panic!("capture-hz must be 30 or 60"),
        })
        .unwrap_or(60000. / 1001.);
    let sequence_duration = match capture_sequence {
        Some("gameplay-ads") => 9.0,
        Some("gameplay-layered") => 11.0,
        Some("gameplay-return") => 6.3,
        Some("gameplay-jump") => 6.5,
        Some("empty") => vector_range::reference_motion::visual_duration(true),
        Some("tactical") => vector_range::reference_motion::visual_duration(false),
        Some("locomotion" | "gameplay-walk") => 3.5,
        Some(sequence) if traversal_capture.is_some() => {
            vector_range::traversal_replay::duration(sequence)
        }
        Some("gameplay-reload") => {
            authored
                .as_ref()
                .and_then(|model| model.tactical_duration())
                .unwrap_or(f64::from(cfg.reload_time))
                .max(f64::from(cfg.reload_time)) as f32
                + 0.75
        }
        _ => cfg.ads_time,
    };
    if capture_sequence.is_some() && !framing.reference {
        return Err("--capture-sequence requires --reference-viewport".into());
    }
    if capture_sequence.is_some() {
        std::fs::create_dir_all(
            args.iter()
                .find_map(|a| a.strip_prefix("--output="))
                .unwrap_or("capture-sequence"),
        )
        .expect("create capture sequence directory");
    }

    let capture_ads_fraction = args
        .iter()
        .find_map(|a| a.strip_prefix("--capture-ads-fraction="))
        .and_then(|s| s.parse::<f32>().ok())
        .filter(|v| v.is_finite() && (0. ..=1.).contains(v));
    let capture_fixtures = args.iter().any(|s| s == "--capture-fixtures");
    let output = args
        .iter()
        .find_map(|s| s.strip_prefix("--output="))
        .unwrap_or("capture.png");
    if matches!(
        capture_sequence,
        Some("gameplay-reload" | "gameplay-ads" | "gameplay-return" | "gameplay-jump")
    ) {
        sim.player.ammo = 12;
    }
    if let Some((position, yaw)) = traversal_capture.and_then(vector_range::traversal_replay::start)
    {
        sim.player.position = position;
        sim.player.yaw = yaw;
    }
    if capture_fixtures {
        sim.player.position = vec3(-18., 0., -12.);
        sim.player.yaw = -std::f32::consts::FRAC_PI_2;
    }
    if capture_ads {
        sim.player.ads = 1.;
    }
    if capture_supply {
        sim.player.position = vec3(0., 0., 11.7);
        sim.player.yaw = std::f32::consts::FRAC_PI_2;
        sim.player.pitch = (supply.bounds().center() - sim.player.eye())
            .normalize()
            .y
            .asin();
        sim.player.ammo = 15;
        sim.player.reserve = 30;
    }
    let demo = args.iter().any(|s| s == "--demo");
    let mut frames = 0;
    if capture || demo {
        session.set_active(true);
        initial = false;
        debug = true;
    }
    if model_error.is_none() {
        if let Err(error) = rust_duty_launcher::game::mark_ready(vector_range::BUILD_VERSION) {
            eprintln!("Update startup acknowledgement: {error}");
        }
    }
    loop {
        if let Some(done) = frame_trace::take_completion_notice() {
            let state = if let Some(error) = done.export_error {
                format!("FRAME EXPORT ERROR: {error}")
            } else if done.status.is_complete() {
                "Frame trace saved".into()
            } else {
                format!("INCOMPLETE frame trace: {:?}", done.status)
            };
            telemetry_status = format!(
                "{}{} | {}",
                if recording.is_some() {
                    "RECORDING CSV; "
                } else {
                    ""
                },
                state,
                done.output_path.display()
            );
            if let Some(error) = &telemetry_csv_error {
                telemetry_status = format!("CSV EXPORT ERROR: {error}; {telemetry_status}");
            }
        }
        let focus_state = focus_input.sample();
        let now = get_time();
        let raw_dt = now - last_frame;
        last_frame = now;
        let dt = raw_dt.min(FixedClock::MAX_FRAME) as f32;
        frames += 1;
        if focus_input.is_key_pressed(KeyCode::F10) {
            // This final frame exits before drawing gameplay; keep its return
            // as explicit shutdown evidence rather than an eligible sample.
            frame_trace::log_completion(frame_trace::set_eligibility(Eligibility::Ineligible(
                BoundaryReason::Shutdown,
            )));
            break;
        }
        // Resolve a replacement before either UI hit testing or drawing this
        // frame, including the startup updater panel. Focus-return edges cannot
        // trigger a reload from a key pressed while the app was interrupted.
        if !focus_state.unfocused && !focus_state.changed && focus_input.is_key_pressed(KeyCode::F7)
        {
            notice = match vector_range::ui_theme::reload_theme() {
                Ok(()) => "UI theme reloaded".into(),
                Err(error) => {
                    eprintln!("UI theme: {error}");
                    format!("UI theme retained: {error}")
                }
            };
            notice_timer = 6.;
        }
        game_update.set_pointer_input(
            !capture && focus_input.is_mouse_button_pressed(MouseButton::Left),
            !capture && focus_input.is_mouse_button_down(MouseButton::Left),
        );
        let startup_blocked = game_update.startup_blocked();
        let update_pointer = game_update.consumes_pointer(!session.is_active());
        let menu_enabled = !session.is_active()
            && !startup_blocked
            && !update_pointer
            && !focus_state.unfocused
            && !focus_state.changed;
        pause_menu.telemetry_state(recording.is_some(), frame_trace::is_stop_requested());
        let mut menu_action = pause_menu.input(
            &mut cfg,
            weapon_id,
            vec2(screen_width(), screen_height()),
            Vec2::from(mouse_position()),
            (
                focus_input.is_mouse_button_pressed(MouseButton::Left),
                focus_input.is_mouse_button_down(MouseButton::Left),
            ),
            menu_enabled,
        );
        let shift = focus_input.is_key_down(KeyCode::LeftShift)
            || focus_input.is_key_down(KeyCode::RightShift);
        let keys = pause_menu::MenuKeys {
            next: (focus_input.is_key_pressed(KeyCode::Tab) && !shift)
                || (pause_menu.has_keyboard_focus() && focus_input.is_key_pressed(KeyCode::Down)),
            previous: (focus_input.is_key_pressed(KeyCode::Tab) && shift)
                || (pause_menu.has_keyboard_focus() && focus_input.is_key_pressed(KeyCode::Up)),
            increase: focus_input.is_key_pressed(KeyCode::Right),
            decrease: focus_input.is_key_pressed(KeyCode::Left),
            minimum: focus_input.is_key_pressed(KeyCode::Home),
            maximum: focus_input.is_key_pressed(KeyCode::End),
            activate: focus_input.is_key_pressed(KeyCode::Enter)
                || focus_input.is_key_pressed(KeyCode::Space),
        };
        let key_action = pause_menu.keyboard(&mut cfg, weapon_id, keys, menu_enabled);
        menu_action.save |= key_action.save;
        menu_action.resume |= key_action.resume;
        menu_action.telemetry |= key_action.telemetry;
        if menu_action.save {
            notice = pause_menu.save_result(cfg.save(settings_path));
            notice_timer = 4.;
        }
        let transition = session.step(focus_state.apply_to_session_input(
            vector_range::session::SessionInput {
                window_unfocused: false,
                esc_pressed: !capture && focus_input.is_key_pressed(KeyCode::Escape),
                esc_down: !capture && focus_input.is_key_down(KeyCode::Escape),
                enter_pressed: !capture
                    && !pause_menu.has_keyboard_focus()
                    && focus_input.is_key_pressed(KeyCode::Enter),
                enter_down: !capture
                    && !pause_menu.has_keyboard_focus()
                    && focus_input.is_key_down(KeyCode::Enter),
                click_pressed: !capture && menu_action.resume,
                click_down: !capture && menu_action.resume,
                focus_shortcut_pressed: !capture
                    && (focus_input.is_key_down(KeyCode::LeftAlt)
                        || focus_input.is_key_down(KeyCode::RightAlt)
                        || focus_input.is_key_down(KeyCode::LeftSuper)
                        || focus_input.is_key_down(KeyCode::RightSuper)),
                blocked: model_error.is_some() || startup_blocked,
                dt: raw_dt,
            },
            capture,
        ));
        let active = transition.active;
        // Observe presentation context, never simulation dt. In particular a
        // hitch's discard_timing flag must not hide the actual wall-clock gap.
        let trace_eligibility = frame_trace_eligibility(
            active,
            capture,
            focus_state,
            model_error.is_some() || startup_blocked,
        );
        frame_trace::log_completion(frame_trace::set_eligibility(trace_eligibility));
        let mut just_resumed = transition.resumed;
        let capture_cursor = active && !focus_state.unfocused && !capture;
        if capture_cursor != cursor_captured {
            set_cursor_grab(capture_cursor);
            show_mouse(!capture_cursor);
            cursor_captured = capture_cursor;
        }
        if transition.paused {
            // Includes Escape, focus-shortcut, and asset-block interruptions.
            // A render hitch only discards time and must not cancel traversal.
            sim.cancel_mantle();
        }
        if transition.paused || transition.resumed || focus_state.changed {
            initial = false;
            focus_input.clear();
            game_update.set_pointer_input(false, false);
            clock.clear();
            intents.clear();
            controls.clear();
            action_latch.clear();
        }
        if transition.discard_timing {
            clock.clear();
            intents.clear();
        }
        if transition.interrupts_firing_sequence(gameplay_capture, focus_state.changed) {
            sim.player.firing_sequence = false;
        }
        // While startup owns the screen, no world tick, gameplay hotkey, weapon
        // input, HUD or pause-menu rendering can run. Session edges above are
        // still sampled, so held buttons cannot leak through on completion.
        if startup_blocked {
            if game_update.draw(true) {
                break;
            }
            next_frame().await?;
            continue;
        }
        let simulation_dt = if transition.discard_timing
            || capture_supply
            || capture_sequence.is_some()
            || capture_lighting
        {
            0.
        } else {
            raw_dt.min(FixedClock::MAX_FRAME)
        };
        if focus_input.is_key_pressed(KeyCode::M) {
            audio.muted = !audio.muted;
            notice = if audio.muted {
                "Audio muted".into()
            } else {
                "Audio on".into()
            };
            notice_timer = 2.;
        }
        if focus_input.is_key_pressed(KeyCode::F1) {
            debug = !debug;
        }
        if focus_input.is_key_pressed(KeyCode::F2) {
            frame_trace::log_completion(frame_trace::boundary(BoundaryReason::SceneChanged));
            sim.reset();
            supply.reset();
            register_supply(&mut sim, &supply);
            animation_state = vector_range::view_animation::ViewAnimation::default();
            locomotion_state.reset(sim.time);
            if let Some(viewmodel) = &mut authored {
                viewmodel.reset(sim.time);
            }
            intents.clear();
            controls.clear();
            action_latch.clear();
            look_sway.reset();
            body.reset();
            clock.clear();
            just_resumed = true;
            traces.clear();
            impacts.clear();
            muzzle_fx.clear();
            notice = "Range reset. Fresh magazine, clean telemetry.".into();
            notice_timer = 3.;
        }
        if focus_input.is_key_pressed(KeyCode::F9) {
            // Debug: kill the player to exercise death/respawn in any state.
            sim.damage_player(cfg.action.max_health);
        }
        if focus_input.is_key_pressed(KeyCode::F11) {
            fullscreen = !fullscreen;
            set_fullscreen(fullscreen);
        }
        let previous_tuning = (cfg.sensitivity, cfg.fov);
        if focus_input.is_key_pressed(KeyCode::LeftBracket) {
            cfg.sensitivity = (cfg.sensitivity - 0.01).max(0.01);
        }
        if focus_input.is_key_pressed(KeyCode::RightBracket) {
            cfg.sensitivity = (cfg.sensitivity + 0.01).min(1.);
        }
        if focus_input.is_key_pressed(KeyCode::Minus) {
            cfg.fov = (cfg.fov - 2.).max(65.);
        }
        if focus_input.is_key_pressed(KeyCode::Equal) {
            cfg.fov = (cfg.fov + 2.).min(120.);
        }
        if previous_tuning != (cfg.sensitivity, cfg.fov) {
            pause_menu.changed();
        }
        // Start menu / pause settings only. Arrows nudge the viewmodel, not the player.
        if !active && menu_enabled && !pause_menu.has_keyboard_focus() {
            let before = [cfg.viewmodel_x, cfg.viewmodel_y, cfg.viewmodel_z];
            if focus_input.is_key_pressed(KeyCode::Left) {
                cfg.nudge_viewmodel(-Settings::VIEWMODEL_NUDGE, 0.);
            }
            if focus_input.is_key_pressed(KeyCode::Right) {
                cfg.nudge_viewmodel(Settings::VIEWMODEL_NUDGE, 0.);
            }
            if focus_input.is_key_pressed(KeyCode::Down) {
                cfg.nudge_viewmodel(0., -Settings::VIEWMODEL_NUDGE);
            }
            if focus_input.is_key_pressed(KeyCode::Up) {
                cfg.nudge_viewmodel(0., Settings::VIEWMODEL_NUDGE);
            }
            if focus_input.is_key_pressed(KeyCode::PageUp) {
                cfg.set_viewmodel_z(cfg.viewmodel_z + Settings::VIEWMODEL_NUDGE);
            }
            if focus_input.is_key_pressed(KeyCode::PageDown) {
                cfg.set_viewmodel_z(cfg.viewmodel_z - Settings::VIEWMODEL_NUDGE);
            }
            if before != [cfg.viewmodel_x, cfg.viewmodel_y, cfg.viewmodel_z] {
                pause_menu.changed();
            }
        }
        if focus_input.is_key_pressed(KeyCode::F5) {
            notice = pause_menu.save_result(cfg.save(settings_path));
            notice_timer = 4.;
        }
        if focus_input.is_key_pressed(KeyCode::F6) {
            if let Err(error) = std::fs::read_to_string(settings_path) {
                notice = format!("Could not reload preset; current values retained: {error}");
            } else {
                cfg = Settings::load_with_base(settings_path, base.clone());
                pause_menu.reloaded();
                notice = format!("Reloaded {settings_path}; unsaved changes discarded");
            }
            notice_timer = 4.;
        }
        if focus_input.is_key_pressed(KeyCode::F8) || menu_action.telemetry {
            if frame_trace::is_stop_requested() {
                telemetry_status = "STOPPING telemetry: awaiting final presentation".into();
            } else if let Some(export) = recording.take() {
                let stopped = export.finish();
                let awaiting_frame = frame_trace::is_active();
                if awaiting_frame {
                    request_frame_trace_stop();
                }
                telemetry_status = match stopped {
                    Ok(path) => format!(
                        "{} | {}",
                        if awaiting_frame {
                            "STOPPING: CSV saved; awaiting final present"
                        } else {
                            "CSV saved; inspect frame status separately"
                        },
                        path.display()
                    ),
                    Err(error) => {
                        telemetry_csv_error = Some(error.clone());
                        format!("CSV EXPORT ERROR: {error}")
                    }
                };
            } else {
                let info = backend_info();
                let executable_hash = rust_duty_launcher::file_hash(&executable).ok();
                let identity = serde_json::json!({
                    "schema":"rust-duty-local-playtest-session/v1",
                    "build":{"version":vector_range::BUILD_VERSION,"number":vector_range::BUILD_NUMBER,"label":vector_range::BUILD_LABEL},
                    "executable_sha256":executable_hash,
                    "source":crate::telemetry_export::packaged_source(&executable,vector_range::BUILD_LABEL,executable_hash.as_deref()),
                    "runtime_observed":info.as_ref().ok().map(|value| serde_json::json!({"requested":value.requested,"backend":value.backend,"adapter":value.adapter})),
                    "hardware_classification":"unknown", "sharing":"local only; manual review before sharing",
                });
                match crate::telemetry_export::LocalExport::start(
                    std::path::Path::new("telemetry-sessions"),
                    std::path::Path::new("telemetry.csv"),
                    &identity,
                ) {
                    Ok(export) => {
                        telemetry_csv_error = None;
                        let scene = frame_trace_scene(
                            profile,
                            weapon_id,
                            if model_error.is_some() {
                                "unavailable"
                            } else if authored.is_some() {
                                "authored_viewmodel"
                            } else if model.is_some() {
                                "static_weapon_model"
                            } else {
                                "procedural"
                            },
                            framing.reference,
                            capture,
                            capture_sequence,
                            demo,
                        );
                        let trace = start_frame_trace(
                            scene,
                            trace_eligibility,
                            &mut frame_trace_sequence,
                            Some(export.frame_path()),
                        );
                        telemetry_status = match trace {
                            Ok(_) => format!(
                                "RECORDING CSV + CPU trace (F8 stops) | {}",
                                export.directory.display()
                            ),
                            Err(error) => format!(
                                "RECORDING CSV; CPU trace unavailable: {error} | {}",
                                export.directory.display()
                            ),
                        };
                        recording = Some(export);
                    }
                    Err(error) => {
                        telemetry_status = format!(
                            "TELEMETRY START ERROR: {error}; partial local folder may remain"
                        )
                    }
                }
            }
            notice = telemetry_status.clone();
            notice_timer = 6.;
        }
        if let Some(viewmodel) = &mut authored {
            viewmodel.set_walk_translation(cfg.walking_translation(weapon_id));
        }
        if active {
            let mouse = if just_resumed || transition.discard_timing {
                Vec2::ZERO
            } else {
                mouse_delta_position()
            };
            let view_before = vec2(sim.player.yaw, sim.player.pitch);
            // Normalized screen coordinates from Macroquad have a reversed delta sign.
            sim.player.yaw -= mouse.x
                * screen_width()
                * 0.5
                * cfg.sensitivity.to_radians()
                * (1. - sim.player.ads * 0.35);
            sim.player.pitch = (sim.player.pitch
                + mouse.y
                    * screen_height()
                    * 0.5
                    * cfg.sensitivity.to_radians()
                    * (1. - sim.player.ads * 0.35))
                .clamp(-1.48, 1.48);
            // Hang/mount aim limits apply before anything renders this frame.
            sim.clamp_look(&cfg);
            // Look sway reads the applied view rotation (camera space: +yaw
            // turns left), so sensitivity never changes the response.
            if !capture {
                // Captures drive sway from their scripted fixed-step view instead.
                look_sway.update(
                    vec2(
                        -(sim.player.yaw - view_before.x),
                        sim.player.pitch - view_before.y,
                    ),
                    dt,
                    &sway_tuning,
                );
            }
            let input_frame = focus_input.frame();
            input_frame.sample_actions(
                &mut action_latch,
                get_time(),
                cfg.action.tac_sprint_double_tap,
                !just_resumed && !transition.discard_timing,
            );
            input_frame.sample_intents(&mut intents, !just_resumed && !transition.discard_timing);
            controls.sample(input_frame.control_sample(get_time()), !just_resumed);
            let mut input = Input {
                movement: Vec2::from_array(input_frame.movement_axes()),
                jump: false,
                reload: false,
                crouch: false,
                prone: false,
                sprint: focus_input.is_key_down(KeyCode::LeftShift),
                ads: false,
                fire: false,
                tactical_sprint: false,
                mount: false,
                sidearm: false,
                lean: 0.,
                cant: false,
            };
            if demo {
                sim.player.yaw = -std::f32::consts::FRAC_PI_2;
                sim.player.pitch = 0.;
            }
            let steps = clock.advance(simulation_dt).unwrap_or(0);
            for _ in 0..steps {
                let step = intents.take(focus_input.is_mouse_button_down(MouseButton::Left));
                if step.jump {
                    controls.request_jump();
                }
                let control_intent = controls.intent();
                input.ads = capture_ads || demo || control_intent.ads;
                input.crouch = control_intent.crouch();
                input.lean = f32::from(controls.lean());
                input.cant = controls.cant();
                input.prone = control_intent.prone();
                input.jump = step.jump;
                input.reload = step.reload;
                input.fire = demo || step.fire;
                let action = action_latch.take();
                input.tactical_sprint = action.tactical_sprint;
                input.mount = action.mount;
                input.sidearm = action.sidearm;
                let authored_step_start = sim.time;
                sim.update(input, &cfg, FIXED_DT);
                if let Some(viewmodel) = &mut authored {
                    viewmodel.committed_step(authored_step_start, &sim);
                }
                // Cosmetic targets receive exact simulation timestamps; input
                // and movement remain fully authoritative and immediate.
                locomotion_state.sample(sim.time, locomotion_input(&sim));
                let focus = supply_focus(&sim, &cfg, &supply, active);
                if supply.tick(
                    &mut sim.player,
                    focus,
                    focus_input.is_key_down(KeyCode::F),
                    active,
                    FIXED_DT,
                ) == vector_range::ammo_supply::SupplyEvent::Refilled
                {
                    notice = "Ammunition replenished".into();
                    notice_timer = 2.;
                }
            }
            if sim.player.reload_left > 0. && !was_reloading {
                audio.play(3);
            }
            was_reloading = sim.player.reload_left > 0.;
            step_distance += sim.player.speed() * dt;
            if sim.player.grounded && step_distance > if sim.player.sprinting { 2.5 } else { 1.8 } {
                audio.play(2);
                step_distance = 0.;
            }
            for shot in sim.events.drain(..) {
                audio.play(0);
                if shot.hit_target {
                    audio.play(1);
                    hit_timer = 0.13;
                    head = shot.headshot;
                }
                traces.push(Trace { shot, life: 0.045 });
                impacts.push(Impact {
                    point: shot.end,
                    life: 5.,
                    target: shot.hit_target,
                });
                muzzle_fx.spawn_shot(&shot);
            }
            if impacts.len() > 96 {
                impacts.drain(0..impacts.len() - 96);
            }
            hit_timer = (hit_timer - dt).max(0.);
            for t in &mut traces {
                t.life -= dt;
            }
            traces.retain(|t| t.life > 0.);
            for i in &mut impacts {
                i.life -= dt;
            }
            impacts.retain(|i| i.life > 0.);
            muzzle_fx.update(dt, &sim.blocks, &sim.ramps);
            record_clock += dt;
            if record_clock >= 0.1 {
                record_clock = 0.;
                if let Some(f) = &mut recording {
                    let p = &sim.player;
                    let _ = writeln!(
                        f,
                        "{:.4},{:.4},{:.4},{:.4},{:.4},{},{},{},{:.4},{:.4},{},{},{},{},{}",
                        sim.time,
                        p.position.x,
                        p.position.y,
                        p.position.z,
                        p.speed(),
                        p.grounded,
                        p.crouched,
                        p.sprinting,
                        p.ads,
                        p.recoil.x.to_degrees(),
                        p.ammo,
                        sim.stats.shots,
                        sim.stats.hits,
                        sim.stats.kills,
                        get_fps()
                    );
                }
            }
        }
        if let Some(error) = recording.as_ref().and_then(|export| export.error()) {
            telemetry_csv_error = Some(error.to_owned());
            telemetry_status =
                format!("CSV RECORDING ERROR: {error}; F8 stops and records incomplete status");
        }
        let focus = supply_focus(&sim, &cfg, &supply, active);
        if !active
            || transition.discard_timing
            || !focus_input.is_key_down(KeyCode::F)
            || focus.is_none()
        {
            supply.cancel();
        }
        // Deterministic presentation samples for comparison; only explicit capture flags use these.
        let sequence_elapsed = ((frames - 8).max(0) as f32) / capture_hz;
        let sequence_phase = (sequence_elapsed / sequence_duration).clamp(0., 1.);
        let presentation_reload = if matches!(capture_sequence, Some("tactical" | "empty")) {
            Some(sequence_phase)
        } else {
            capture_reload
        };
        if capture_sequence.is_some() && !gameplay_capture {
            sim.time = sequence_elapsed as f64;
        }
        if gameplay_capture {
            // Real fixed-step input replay: no pose, velocity, animation-clock,
            // timer or normalized reload-phase overrides are used here.
            let target_tick = vector_range::clock::capture_tick_target(
                (frames - 8).max(0) as u64,
                capture_hz as u32,
            );
            while target_tick.map_or(
                sim.time + f64::from(FIXED_DT) <= f64::from(sequence_elapsed) + 1e-7,
                |target| gameplay_capture_tick < target,
            ) {
                let start = sim.time;
                let reload = capture_sequence == Some("gameplay-reload")
                    && !gameplay_reload_issued
                    && start >= 0.25;
                let movement =
                    if capture_sequence == Some("gameplay-walk") && (0.25..2.25).contains(&start) {
                        Vec2::Y
                    } else {
                        Vec2::ZERO
                    };
                gameplay_reload_issued |= reload;
                let input = if let Some(sequence) = traversal_capture {
                    vector_range::traversal_replay::input(sequence, start)
                } else if capture_sequence == Some("gameplay-ads") {
                    vector_range::authored_ads::gameplay_ads_replay_input(start)
                } else if capture_sequence == Some("gameplay-layered") {
                    vector_range::layered_locomotion::gameplay_layered_replay_input(start)
                } else if capture_sequence == Some("gameplay-jump") {
                    vector_range::authored_jump::gameplay_jump_replay_input(start)
                } else if capture_sequence == Some("gameplay-return") {
                    vector_range::authored_reload::gameplay_return_replay_input(start)
                } else {
                    Input {
                        reload,
                        movement,
                        ..Input::default()
                    }
                };
                let view_before = vec2(sim.player.yaw, sim.player.pitch);
                if traversal_capture == Some("gameplay-sway") {
                    // Scripted view turn (camera space +left = sim yaw decreasing).
                    sim.player.yaw -=
                        vector_range::traversal_replay::sway_yaw_rate(start) * FIXED_DT;
                }
                sim.update(input, &cfg, FIXED_DT);
                if traversal_capture.is_some() {
                    look_sway.update(
                        vec2(
                            -(sim.player.yaw - view_before.x),
                            sim.player.pitch - view_before.y,
                        ),
                        FIXED_DT,
                        &sway_tuning,
                    );
                }
                gameplay_capture_tick += 1;
                if let Some(model) = &mut authored {
                    model.committed_step(start, &sim);
                }
            }
        }
        if capture_sequence == Some("ads") {
            sim.player.ads = sequence_phase;
        }
        if capture_sequence == Some("locomotion") {
            // Diagnostic presentation only: sample target changes on the same
            // fixed clock used by gameplay, with camera/world movement frozen.
            let capture_time = sim.time;
            while locomotion_capture_tick as f64 / 120. <= capture_time {
                let t = locomotion_capture_tick as f64 / 120.;
                sim.player.sprinting = (1. ..2.).contains(&t);
                let speed = if !(0.25..3.).contains(&t) {
                    0.
                } else if sim.player.sprinting {
                    cfg.sprint_speed
                } else {
                    cfg.walk_speed
                };
                sim.player.velocity = vec3(speed, 0., 0.);
                locomotion_state.sample(t, locomotion_input(&sim));
                if let Some(viewmodel) = &mut authored {
                    sim.time = t;
                    let start = locomotion_capture_tick.saturating_sub(1) as f64 / 120.;
                    viewmodel.committed_step(start, &sim);
                }
                locomotion_capture_tick += 1;
            }
            sim.time = capture_time;
        }
        if let Some(ads) = capture_ads_fraction {
            sim.player.ads = ads;
        }
        if let Some(phase) = presentation_reload {
            sim.player.reload_empty = capture_empty;
            sim.player.reload_total = if capture_empty {
                cfg.empty_reload_time
            } else {
                cfg.reload_time
            };
            sim.player.reload_left = sim.player.reload_total * (1. - phase);
            sim.player.reload_ready_at = sim.time + sim.player.reload_left as f64;
        }
        if capture_lighting {
            sim.time = 0.;
            sim.player.yaw = lighting_yaw;
            sim.player.pitch = lighting_pitch;
            sim.player.recoil = Vec2::ZERO;
        }
        for event in sim.action_events.drain(..) {
            let message = match event.kind {
                ActionEventKind::Died => Some("Down. Respawning shortly."),
                ActionEventKind::Respawned => Some("Respawned."),
                ActionEventKind::SidearmRejected(Rejection::NoSidearm) => {
                    Some("No hang-eligible sidearm in this loadout")
                }
                ActionEventKind::PullUpRejected(Rejection::Blocked) => Some("No room to pull up"),
                ActionEventKind::PullUpRejected(Rejection::PistolOut) => {
                    Some("Stow the sidearm (2) before pulling up")
                }
                ActionEventKind::MountRejected(Rejection::Steep) => {
                    Some("Surface too steep to mount")
                }
                ActionEventKind::MountRejected(_) => Some("No valid cover to mount"),
                ActionEventKind::DiveRejected(Rejection::Blocked) => Some("No room to dive"),
                _ => None,
            };
            if let Some(message) = message {
                notice = message.into();
                notice_timer = 2.;
            }
        }
        notice_timer = (notice_timer - dt).max(0.);
        clear_background(Color::new(0.66, 0.76, 0.78, 1.));
        let aspect = if framing.reference {
            16. / 9.
        } else {
            screen_width() / screen_height()
        };
        let eye = sim.player.eye();
        let forward = sim.player.direction();
        let fov = cfg.fov
            + (cfg.ads_fov - cfg.fov)
                * vector_range::reference_motion::visual_world_ads(sim.player.ads);
        set_camera(&Camera3D {
            position: eye,
            target: eye + forward,
            // Lean rolls the world camera; the viewmodel stays fixed to the view.
            up: {
                let roll = sim.player.lean_roll(cfg.action.lean_roll);
                let right = forward.cross(Vec3::Y).normalize_or_zero();
                // Leaning right tilts the head's up vector toward the right.
                (Vec3::Y * roll.cos() + right * roll.sin()).normalize()
            },
            fovy: h_fov_to_v(fov, aspect),
            z_near: 0.035,
            z_far: 200.,
            ..Default::default()
        });
        world(&sim, &texture);
        let body_frame = body.update(&sim, if active { dt } else { 0. }, &body_tuning);
        if !capture_lighting && capture_sequence.is_none() {
            draw_body_placeholder(&body_frame);
        }
        if capture_lighting && frames == 8 {
            // Record the actual range pass before the overlay/HUD can cover it.
            let world_output = format!("{output}.world.png");
            capture_png(None, world_output.clone());
            crate::capture::write_world_metadata(&world_output)?;
            let light = SceneLighting::range().in_view(forward);
            let world = SceneLighting::range();
            std::fs::write(format!("{output}.lighting.json"), format!(
                "{{\"schema\":\"rust-duty-lighting-capture/v1\",\"yaw_degrees\":{},\"pitch_degrees\":{},\"world_light\":[{},{},{}],\"view_light\":[{},{},{}],\"ambient\":{},\"diffuse\":{},\"simulation_time\":{}}}",
                lighting_yaw.to_degrees(), lighting_pitch.to_degrees(), world.direction_to_light.x, world.direction_to_light.y, world.direction_to_light.z,
                light.direction_to_light.x, light.direction_to_light.y, light.direction_to_light.z, light.ambient, light.diffuse, sim.time))
                .map_err(|error| format!("write lighting capture metadata: {error}"))?;
        }
        for t in &traces {
            draw_line_3d(
                t.shot.start + forward * 0.6,
                t.shot.end,
                Color::new(1., 0.84, 0.5, 0.8),
            );
        }
        for i in &impacts {
            draw_sphere(i.point, 0.022, None, if i.target { CYAN } else { INK });
        }
        muzzle_fx.draw_world(eye, authored_path.is_some());
        if capture_fire {
            sim.player.shot_kick = 1.;
        }
        // An explicitly requested invalid authored asset never falls through
        // to the legacy procedural renderer while its startup error is shown.
        let action_pose = sim.action_pose();
        let layers = [
            look_sway.offset(&sway_tuning),
            vector_range::weapon_sway::action_offset(
                &sim.player,
                &action_pose,
                cfg.action.obstruct_max_retract,
            ),
        ];
        if (authored_path.is_none() || authored.is_some()) && !sim.player.dead() {
            weapon(
                &sim,
                &target,
                aspect,
                &mut locomotion_state,
                model.as_mut(),
                authored.as_mut(),
                arms.as_mut(),
                &mut animation_state,
                &cfg,
                cfg.walking_translation(weapon_id),
                framing,
                presentation_reload,
                &mut muzzle_fx,
                authored_path.is_none(),
                &layers,
            );
        }
        if let Some(warning) = authored.as_ref().and_then(|viewmodel| viewmodel.warning()) {
            label(warning, 24., screen_height() - 155., 15., YELLOW);
        }
        if let Some(error) = authored.as_ref().and_then(|viewmodel| viewmodel.error()) {
            if model_error.is_none() {
                model_error = Some(format!("Authored viewmodel: {error}"));
            }
        }
        hud(
            &sim,
            &cfg,
            hit_timer,
            head,
            debug,
            recording.is_some(),
            &notice,
            notice_timer,
            weapon_label,
        );
        if let Some(focus) = focus {
            vector_range::ammo_supply_view::draw_ammo_supply_hint(
                focus,
                if capture_supply {
                    0.5
                } else {
                    supply.progress()
                },
                supply.ammo_full(&sim.player),
            );
        }
        if !active {
            pause_menu.telemetry_state(recording.is_some(), frame_trace::is_stop_requested());
            pause_menu.draw(
                &cfg,
                weapon_id,
                initial,
                controls.mode(),
                (notice_timer > 0.).then_some(notice.as_str()),
            );
        }
        if game_update.draw(!active) {
            break;
        }
        if let Some(error) = &model_error {
            panel(24., screen_height() - 140., screen_width() - 48., 115.);
            label(
                &error.chars().take(105).collect::<String>(),
                42.,
                screen_height() - 108.,
                19.,
                RED,
            );
            label(
                if authored_path.is_some() {
                    "Check the matching .vra/.vrs/.vrm files and the selected clip name."
                } else {
                    "Re-extract the whole game folder. Expected: assets/weapons/hk416a5.vrm"
                },
                42.,
                screen_height() - 78.,
                16.,
                WHITE,
            );
            label(
                if authored_path.is_some() {
                    "F10 exits. Remove --viewmodel-asset to return to the existing gameplay presentation."
                } else {
                    "F10 exits. --procedural-weapon is an explicit diagnostic bypass."
                },
                42.,
                screen_height() - 48.,
                16.,
                MUTED,
            );
        } else if model_missing {
            label("HK416 asset missing: extract the whole package beside the EXE (procedural fallback active)",24.,screen_height()-155.,16.,YELLOW);
        }
        telemetry_indicator(&telemetry_status);
        if crate::capture::write_frame(crate::capture::CaptureFrame {
            capture,
            capture_sequence,
            frames,
            output,
            framing: &framing,
            target: &target,
            sim: &sim,
            presentation_reload,
            sequence_elapsed,
            sequence_phase,
            sequence_duration,
            capture_empty,
            cfg: &cfg,
            capture_hz,
            authored: &authored,
            gameplay_reload_issued,
            traversal_capture,
            look_sway: &look_sway,
            locomotion_state: &mut locomotion_state,
        })? {
            break;
        }
        next_frame().await?;
    }
    // The renderer submits after this future resolves. Defer trace export
    // through that final successful present; main handles missing/error exits.
    request_frame_trace_stop();
    Ok(())
}

fn frame_trace_eligibility(
    active: bool,
    capture: bool,
    focus: vector_range::session::FocusState,
    blocked: bool,
) -> Eligibility {
    if capture {
        Eligibility::Ineligible(BoundaryReason::DiagnosticCapture)
    } else if focus.unfocused {
        Eligibility::Ineligible(BoundaryReason::FocusLost)
    } else if focus.changed {
        Eligibility::Ineligible(BoundaryReason::FocusRegained)
    } else if blocked {
        Eligibility::Ineligible(BoundaryReason::CallerExcluded)
    } else if !active {
        Eligibility::Ineligible(BoundaryReason::Paused)
    } else {
        Eligibility::Eligible
    }
}

/// Deliberately accept named runtime choices, never filesystem paths or the
/// unfiltered CLI. An explicit/private asset path must not enter trace identity.
fn frame_trace_scene(
    profile: &str,
    weapon_id: &str,
    presentation: &str,
    reference: bool,
    capture: bool,
    capture_sequence: Option<&str>,
    demo: bool,
) -> serde_json::Value {
    serde_json::json!({
        "name": "vector_range_default_range",
        "profile_base": profile,
        "weapon_id": weapon_id,
        "presentation": presentation,
        "reference_viewport": reference,
        "diagnostic_capture": capture,
        "capture_sequence": capture_sequence,
        "demo": demo,
    })
}

#[cfg(any(feature = "wgpu-runtime", test))]
fn frame_trace_identity(
    info: vector_range::draw::BackendInfo,
    window: vector_range::frame_performance::WindowContext,
    scene: serde_json::Value,
) -> vector_range::frame_performance::RunIdentity {
    use vector_range::frame_performance::{RunIdentity, RuntimeIdentity};
    RunIdentity {
        runtime: RuntimeIdentity {
            actual_backend: Some(info.backend),
            // The frozen BackendInfo exposes the actual name, not device type
            // or hardware proof. Additional renderer diagnostics stay separate.
            actual_adapter: serde_json::json!({ "name": info.adapter }),
            build: serde_json::json!({
                "version": vector_range::BUILD_VERSION,
                "number": vector_range::BUILD_NUMBER,
                "label": vector_range::BUILD_LABEL,
            }),
            initial_window: window,
            scene,
        },
        operator_supplied: serde_json::Value::Null,
    }
}

#[cfg(any(feature = "wgpu-runtime", test))]
fn next_frame_trace_path(
    sequence: &mut u64,
    mut exists: impl FnMut(&std::path::Path) -> std::io::Result<bool>,
) -> Result<std::path::PathBuf, String> {
    // Exclusive creation at export remains the final authority. Bounded name
    // selection makes repeated F8 sessions useful without overwriting evidence.
    for _ in 0..1024 {
        *sequence = sequence
            .checked_add(1)
            .ok_or("frame trace sequence exhausted")?;
        let path = std::path::PathBuf::from(format!(
            "telemetry.frames.{}.{sequence:04}.json",
            std::process::id()
        ));
        if !exists(&path).map_err(|error| format!("inspect frame trace destination: {error}"))? {
            return Ok(path);
        }
    }
    Err("no unused frame trace destination after 1024 candidates".into())
}

fn start_frame_trace(
    scene: serde_json::Value,
    eligibility: Eligibility,
    sequence: &mut u64,
    output: Option<std::path::PathBuf>,
) -> Result<std::path::PathBuf, String> {
    #[cfg(feature = "wgpu-runtime")]
    {
        if !vector_range::platform::runtime::wgpu_active() {
            return Err("CPU present-return timing requires the wgpu runtime".into());
        }
        let identity = frame_trace_identity(
            backend_info()?,
            vector_range::platform::window::performance_window_context(),
            scene,
        );
        let path = match output {
            Some(path) => path,
            None => next_frame_trace_path(sequence, std::path::Path::try_exists)?,
        };
        frame_trace::start(
            identity,
            path.clone(),
            vector_range::frame_performance::CaptureLimits::default(),
        )
        .map_err(|error| error.to_string())?;
        // start defaults to Eligible. The first paused/capture frame must be
        // excluded too, even though its earlier disabled context hook was a no-op.
        frame_trace::log_completion(frame_trace::set_eligibility(eligibility));
        Ok(path)
    }
    #[cfg(not(feature = "wgpu-runtime"))]
    {
        let _ = (scene, eligibility, sequence, output);
        Err("CPU present-return timing requires the wgpu runtime".into())
    }
}

fn request_frame_trace_stop() {
    frame_trace::request_stop();
}

/// Keep user-edited adjacent themes stable across managed updates. A verified
/// version directory supplies only the shipped default when no local file exists.
fn resolve_theme_path(
    explicit: Option<&std::path::Path>,
    executable: &std::path::Path,
    packaged_executable: &std::path::Path,
    exists: impl Fn(&std::path::Path) -> bool,
) -> std::path::PathBuf {
    if let Some(explicit) = explicit {
        return explicit.to_owned();
    }
    for executable in [executable, packaged_executable] {
        let path = executable
            .parent()
            .unwrap_or(std::path::Path::new("."))
            .join("ui/theme.css");
        if exists(&path) {
            return path;
        }
    }
    "ui/theme.css".into()
}

#[cfg(test)]
mod tests {
    use super::{
        frame_trace_eligibility, frame_trace_identity, frame_trace_scene, next_frame_trace_path,
        request_frame_trace_stop, resolve_theme_path, start_frame_trace,
    };
    use std::path::Path;
    use vector_range::frame_performance::{
        BoundaryReason, CaptureError, CaptureLimits, CaptureStatus, Eligibility, RecordKind,
        WindowContext, WindowMode,
    };
    use vector_range::frame_performance_session as frame_trace;

    #[test]
    fn explicit_and_editable_local_themes_take_precedence_over_managed_defaults() {
        let executable = Path::new("install/vector-range.exe");
        let packaged = Path::new("install/versions/current/vector-range.exe");
        let explicit = Path::new("custom/colors.css");
        assert_eq!(
            resolve_theme_path(Some(explicit), executable, packaged, |_| false),
            explicit
        );
        assert_eq!(
            resolve_theme_path(None, executable, packaged, |_| true),
            Path::new("install/ui/theme.css")
        );
    }

    #[test]
    fn shipped_managed_theme_is_selected_before_the_development_fallback() {
        let executable = Path::new("install/vector-range.exe");
        let packaged = Path::new("install/versions/current/vector-range.exe");
        let managed = Path::new("install/versions/current/ui/theme.css");
        assert_eq!(
            resolve_theme_path(None, executable, packaged, |path| path == managed),
            managed
        );
        assert_eq!(
            resolve_theme_path(None, executable, packaged, |_| false),
            Path::new("ui/theme.css")
        );
    }
    #[test]
    fn performance_eligibility_preserves_active_hitches_and_explicit_exclusions() {
        let focus = vector_range::session::FocusState::default();
        let mut session = vector_range::session::SessionController::default();
        session.set_active(true);
        let transition = session.step(vector_range::session::SessionInput {
            dt: 1.0,
            ..Default::default()
        });
        assert!(transition.active && transition.discard_timing);
        assert_eq!(
            frame_trace_eligibility(transition.active, false, focus, false),
            Eligibility::Eligible
        );
        assert_eq!(
            frame_trace_eligibility(false, false, focus, false),
            Eligibility::Ineligible(BoundaryReason::Paused)
        );
        assert_eq!(
            frame_trace_eligibility(true, true, focus, false),
            Eligibility::Ineligible(BoundaryReason::DiagnosticCapture)
        );
        assert_eq!(
            frame_trace_eligibility(true, false, focus, true),
            Eligibility::Ineligible(BoundaryReason::CallerExcluded)
        );
        assert_eq!(
            frame_trace_eligibility(
                true,
                false,
                vector_range::session::FocusState {
                    unfocused: true,
                    ..focus
                },
                false
            ),
            Eligibility::Ineligible(BoundaryReason::FocusLost)
        );
        assert_eq!(
            frame_trace_eligibility(
                true,
                false,
                vector_range::session::FocusState {
                    changed: true,
                    ..focus
                },
                false
            ),
            Eligibility::Ineligible(BoundaryReason::FocusRegained)
        );
    }

    fn trace_identity() -> vector_range::frame_performance::RunIdentity {
        frame_trace_identity(
            vector_range::draw::BackendInfo {
                requested: "/must-not-copy-requested/auto".into(),
                backend: "Dx12".into(),
                adapter: "synthetic CPU test adapter".into(),
            },
            WindowContext {
                physical_width: 960,
                physical_height: 540,
                scale_factor: 1.,
                mode: WindowMode::Windowed,
            },
            frame_trace_scene(
                "m4a1",
                "hk416a5",
                "authored_viewmodel",
                false,
                false,
                None,
                false,
            ),
        )
    }

    #[test]
    fn performance_identity_records_observed_values_without_asset_paths_or_hardware_claims() {
        let identity = trace_identity();
        assert_eq!(identity.runtime.actual_backend.as_deref(), Some("Dx12"));
        assert_eq!(
            identity.runtime.actual_adapter,
            serde_json::json!({"name":"synthetic CPU test adapter"})
        );
        assert_eq!(identity.runtime.build["label"], vector_range::BUILD_LABEL);
        assert_eq!(identity.runtime.scene["profile_base"], "m4a1");
        assert_eq!(identity.runtime.scene["presentation"], "authored_viewmodel");
        assert_eq!(identity.operator_supplied, serde_json::Value::Null);
        let scene = identity.runtime.scene.to_string();
        assert!(!scene.contains("path") && !scene.contains("/") && !scene.contains("\\"));
        assert!(!identity
            .runtime
            .actual_adapter
            .to_string()
            .contains("hardware"));
    }

    #[test]
    fn performance_output_names_preserve_prior_reports_and_are_bounded() {
        let mut sequence = 0;
        let mut inspected = Vec::new();
        let output = next_frame_trace_path(&mut sequence, |path| {
            inspected.push(path.to_owned());
            Ok(inspected.len() < 3)
        })
        .unwrap();
        assert_eq!(sequence, 3);
        assert_eq!(output, inspected[2]);
        assert!(!output.is_absolute());
        assert_ne!(output, Path::new("telemetry.csv"));
        assert!(output.to_string_lossy().ends_with(".0003.json"));
        let error = next_frame_trace_path(&mut sequence, |_| Err(std::io::Error::other("denied")))
            .unwrap_err();
        assert!(error.contains("denied"));
        let mut sequence = 0;
        assert!(next_frame_trace_path(&mut sequence, |_| Ok(true))
            .unwrap_err()
            .contains("1024"));
        assert_eq!(sequence, 1024);
    }

    struct TraceOutput(std::path::PathBuf);
    impl TraceOutput {
        fn new() -> Self {
            static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
            let next = NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            Self(std::env::temp_dir().join(format!(
                "rust-duty-app-frame-trace-{}-{next}.json",
                std::process::id()
            )))
        }
    }
    impl Drop for TraceOutput {
        fn drop(&mut self) {
            let _ = frame_trace::shutdown();
            let _ = std::fs::remove_file(&self.0);
        }
    }
    fn start_test_trace(path: &Path) {
        assert!(!frame_trace::is_active());
        frame_trace::start(
            trace_identity(),
            path.to_owned(),
            CaptureLimits {
                max_records: 32,
                max_metadata_bytes: 4096,
            },
        )
        .unwrap();
    }

    #[test]
    fn normal_app_stop_includes_final_success_before_export_and_shutdown_is_idle() {
        let output = TraceOutput::new();
        start_test_trace(&output.0);
        assert!(frame_trace::present_success().is_none());
        assert!(frame_trace::present_success().is_none());
        request_frame_trace_stop();
        assert!(frame_trace::is_active() && frame_trace::is_stop_requested());
        assert!(!output.0.exists());
        let completion = frame_trace::present_success().unwrap();
        assert_eq!(completion.report.successful_present_count, 3);
        assert_eq!(completion.report.summary.interval_count, 2);
        assert_eq!(completion.export.unwrap(), CaptureStatus::Complete);
        assert!(!frame_trace::is_active());
        assert!(frame_trace::shutdown().is_none());
    }

    #[test]
    fn missing_final_present_is_reported_incomplete_without_synthesizing_a_sample() {
        let output = TraceOutput::new();
        start_test_trace(&output.0);
        assert!(frame_trace::present_success().is_none());
        assert!(frame_trace::present_success().is_none());
        request_frame_trace_stop();
        let completion = frame_trace::shutdown().unwrap();
        assert_eq!(completion.report.successful_present_count, 2);
        assert_eq!(
            completion.report.status,
            CaptureStatus::Incomplete(CaptureError::FinalPresentMissing)
        );
        assert_eq!(
            completion.export.unwrap(),
            CaptureStatus::Incomplete(CaptureError::FinalPresentMissing)
        );
    }

    #[test]
    fn first_and_repeated_paused_capture_frames_are_excluded_after_start() {
        for reason in [BoundaryReason::Paused, BoundaryReason::DiagnosticCapture] {
            let output = TraceOutput::new();
            start_test_trace(&output.0);
            assert!(frame_trace::set_eligibility(Eligibility::Ineligible(reason)).is_none());
            assert!(frame_trace::present_success().is_none());
            request_frame_trace_stop();
            let completion = frame_trace::present_success().unwrap();
            assert_eq!(completion.report.ineligible_present_count, 2);
            assert_eq!(completion.report.summary.interval_count, 0);
            assert!(completion
                .report
                .raw_records()
                .iter()
                .filter_map(|record| {
                    if let RecordKind::PresentReturn {
                        eligibility,
                        interval_ns,
                    } = record.kind
                    {
                        Some((eligibility, interval_ns))
                    } else {
                        None
                    }
                })
                .all(
                    |(eligibility, interval)| eligibility == Eligibility::Ineligible(reason)
                        && interval.is_none()
                ));
            assert_eq!(
                completion.export.unwrap(),
                CaptureStatus::Incomplete(CaptureError::NoEligibleIntervals)
            );
        }
    }

    #[test]
    fn unavailable_wgpu_start_does_not_enable_tracing_or_choose_a_file() {
        let mut sequence = 0;
        let result = start_frame_trace(
            serde_json::Value::Null,
            Eligibility::Eligible,
            &mut sequence,
            None,
        );
        assert!(result.unwrap_err().contains("requires the wgpu runtime"));
        assert_eq!(sequence, 0);
        assert!(!frame_trace::is_active());
    }
}
