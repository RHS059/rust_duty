//! Native capture image and telemetry output from the application frame loop.

use macroquad::prelude::*;
use vector_range::{
    locomotion_presentation::LocomotionPresentation, settings::Settings, sim::Simulation,
    weapon_sway::LookSway,
};

use crate::{
    authored_viewmodel::AuthoredViewmodel,
    viewmodel_draw::{locomotion_input, ViewmodelFraming},
};

pub(crate) struct CaptureFrame<'a> {
    pub(crate) capture: bool,
    pub(crate) capture_sequence: Option<&'a str>,
    pub(crate) frames: i32,
    pub(crate) output: &'a str,
    pub(crate) framing: &'a ViewmodelFraming,
    pub(crate) target: &'a RenderTarget,
    pub(crate) sim: &'a Simulation,
    pub(crate) presentation_reload: Option<f32>,
    pub(crate) sequence_elapsed: f32,
    pub(crate) sequence_phase: f32,
    pub(crate) sequence_duration: f32,
    pub(crate) capture_empty: bool,
    pub(crate) cfg: &'a Settings,
    pub(crate) capture_hz: f32,
    pub(crate) authored: &'a Option<AuthoredViewmodel>,
    pub(crate) gameplay_reload_issued: bool,
    pub(crate) traversal_capture: Option<&'a str>,
    pub(crate) look_sway: &'a LookSway,
    pub(crate) locomotion_state: &'a mut LocomotionPresentation,
}

/// Write the requested frame and report whether its capture sequence has finished.
pub(crate) fn write_frame(frame: CaptureFrame<'_>) -> bool {
    let CaptureFrame {
        capture,
        capture_sequence,
        frames,
        output,
        framing,
        target,
        sim,
        presentation_reload,
        sequence_elapsed,
        sequence_phase,
        sequence_duration,
        capture_empty,
        cfg,
        capture_hz,
        authored,
        gameplay_reload_issued,
        traversal_capture,
        look_sway,
        locomotion_state,
    } = frame;
    if capture
        && ((capture_sequence.is_none() && frames == 8)
            || (capture_sequence.is_some() && frames >= 8))
    {
        let sequence_output;
        let output = if capture_sequence.is_some() {
            sequence_output = format!(
                "{}/{:04}.png",
                if output == "capture.png" {
                    "capture-sequence"
                } else {
                    output
                },
                frames - 8
            );
            sequence_output.as_str()
        } else {
            output
        };
        if framing.reference {
            unsafe {
                get_internal_gl().flush();
            }
            target.texture.get_texture_data().export_png(output);
            let _ = std::fs::write(format!("{output}.json"), format!("{{\"capture\":\"native offscreen viewmodel\",\"width\":960,\"height\":540,\"hfov\":{},\"ads\":{},\"reload_phase\":{}}}",framing.hfov,sim.player.ads,presentation_reload.map(|v|v.to_string()).unwrap_or_else(||"null".into())));
        } else {
            get_screen_data().export_png(output);
        }
        if capture_sequence.is_some() {
            let _ = std::fs::write(format!("{output}.time.json"), format!("{{\"elapsed_seconds\":{},\"normalized_phase\":{},\"visual_duration_seconds\":{},\"simulation_ready_seconds\":{},\"sampling_hz\":{}}}", sequence_elapsed, sequence_phase, sequence_duration, if capture_empty { cfg.empty_reload_time } else if matches!(capture_sequence, Some("ads" | "gameplay-ads")) { cfg.ads_time } else { cfg.reload_time }, capture_hz));
        }
        if capture_sequence == Some("gameplay-reload") {
            let sample = authored.as_ref().and_then(|model| model.reload_sample());
            let route = if sample.is_some() {
                "reload.tactical"
            } else {
                "locomotion"
            };
            let native = sample
                .map(|sample| sample.seconds.to_string())
                .unwrap_or_else(|| "null".into());
            let _ = std::fs::write(format!("{output}.gameplay.json"), format!(
                "{{\"simulation_time\":{},\"accepted_r_issued\":{},\"route\":\"{}\",\"native_clip_seconds\":{},\"ammo\":{},\"reserve\":{},\"reload_left\":{},\"reload_credit_at\":{},\"reload_ready_at\":{}}}",
                sim.time, gameplay_reload_issued, route, native, sim.player.ammo, sim.player.reserve, sim.player.reload_left, sim.player.reload_credit_at, sim.player.reload_ready_at));
        }
        if capture_sequence == Some("gameplay-ads") {
            let model = authored.as_ref();
            let sample = model.and_then(|model| model.ads_sample());
            let native = sample
                .map(|sample| sample.seconds.to_string())
                .unwrap_or_else(|| "null".into());
            let direction = sample.map_or(0, |sample| sample.direction);
            let clip = model.and_then(|model| model.ads_clip()).unwrap_or("");
            let duration = model
                .and_then(|model| model.ads_duration())
                .map(|value| value.to_string())
                .unwrap_or_else(|| "null".into());
            let route = model.map_or("unavailable", |model| model.presentation_route());
            let failed = model.is_none_or(|model| model.error().is_some());
            let segment = vector_range::authored_ads::gameplay_ads_replay_segment(sim.time);
            let _ = std::fs::write(format!("{output}.gameplay.json"), format!(
                "{{\"simulation_time\":{},\"segment\":\"{}\",\"route\":\"{}\",\"clip\":\"{}\",\"native_clip_seconds\":{},\"clip_duration\":{},\"direction\":{},\"ads_requested\":{},\"simulation_ads\":{},\"speed\":{},\"grounded\":{},\"sprinting\":{},\"mantling\":{},\"ammo\":{},\"reserve\":{},\"shots\":{},\"reload_left\":{},\"reload_credit_at\":{},\"reload_ready_at\":{},\"renderer_failed\":{},\"walk_weight\":{},\"walk_seconds\":{},\"run_weight\":{},\"walk_min_rate\":{}}}",
                sim.time, segment, route, clip, native, duration, direction, sim.player.ads_requested,
                sim.player.ads, sim.player.speed(), sim.player.grounded, sim.player.sprinting,
                sim.player.mantle.is_some(), sim.player.ammo, sim.player.reserve, sim.stats.shots,
                sim.player.reload_left, sim.player.reload_credit_at, sim.player.reload_ready_at, failed,
                model.map_or(0., |m| m.walk_weight()), model.and_then(|m| m.walk_sample()).map_or("null".into(), |v| v.to_string()),
                model.map_or(0., |m| m.run_weight()), model.map_or(1., |m| m.walk_min_rate())));
        }
        if capture_sequence == Some("gameplay-layered") {
            let model = authored.as_ref();
            let route = model.map_or("unavailable", |model| model.presentation_route());
            let failed = model.is_none_or(|model| model.error().is_some());
            let segment =
                vector_range::layered_locomotion::gameplay_layered_replay_segment(sim.time);
            let direction = model
                .and_then(|model| model.directional_weights())
                .map_or("null".into(), |weights| format!("{:?}", weights));
            let walk_seconds = model
                .and_then(|model| model.walk_sample())
                .map_or("null".into(), |seconds| seconds.to_string());
            let _ = std::fs::write(format!("{output}.gameplay.json"), format!(
                "{{\"simulation_time\":{},\"segment\":\"{}\",\"route\":\"{}\",\"sampling_hz\":{},\"renderer_failed\":{},\"pose_crc32\":{},\"walk_weight\":{},\"walk_seconds\":{},\"run_weight\":{},\"directional_weights\":{},\"sprinting\":{},\"ads_requested\":{},\"simulation_ads\":{},\"position\":[{},{},{}],\"velocity\":[{},{},{}],\"ammo\":{},\"shots\":{}}}",
                sim.time, segment, route, capture_hz, failed, model.and_then(|m| m.pose_crc32()).map_or("null".into(), |value| value.to_string()),
                model.map_or(0., |m| m.walk_weight()), walk_seconds, model.map_or(0., |m| m.run_weight()), direction,
                sim.player.sprinting, sim.player.ads_requested, sim.player.ads,
                sim.player.position.x, sim.player.position.y, sim.player.position.z,
                sim.player.velocity.x, sim.player.velocity.y, sim.player.velocity.z,
                sim.player.ammo, sim.stats.shots));
        }
        if let Some(sequence) = traversal_capture {
            let pose = sim.action_pose();
            let p = &sim.player;
            let vec =
                |v: Option<Vec3>| v.map_or("null".into(), |v| format!("[{},{},{}]", v.x, v.y, v.z));
            let sway = look_sway.angle_degrees();
            let _ = std::fs::write(format!("{output}.gameplay.json"), format!(
                "{{\"simulation_time\":{},\"segment\":\"{}\",\"slot\":{},\"phase\":\"{:?}\",\"normalized\":{},\"weight\":{},\"placeholder\":{},\"left_hand\":{},\"right_hand\":{},\"left_owner\":\"{:?}\",\"right_owner\":\"{:?}\",\"obstruction\":{},\"obstruction_raw\":{},\"fire_blocked\":{},\"mounted\":{},\"position\":[{},{},{}],\"eye_height\":{},\"speed\":{},\"grounded\":{},\"look_sway_degrees\":[{},{}],\"shots\":{}}}",
                sim.time, vector_range::traversal_replay::segment(sequence, sim.time),
                pose.slot.map_or("null".into(), |slot| format!("\"{}\"", slot.name())),
                pose.phase, pose.normalized, pose.weight, pose.placeholder,
                vec(pose.contacts.left_hand), vec(pose.contacts.right_hand),
                pose.contacts.left_owner, pose.contacts.right_owner,
                p.obstruction.amount, p.obstruction.raw, p.obstruction.fire_blocked, p.mount.is_some(),
                p.position.x, p.position.y, p.position.z, p.eye_height, p.speed(), p.grounded,
                sway.x, sway.y, sim.stats.shots));
        }
        if capture_sequence == Some("gameplay-return") {
            let model = authored.as_ref();
            let anchor = model
                .and_then(|m| m.presented_anchor())
                .map_or("null".into(), |p| format!("[{},{},{}]", p.x, p.y, p.z));
            let _ = std::fs::write(format!("{output}.gameplay.json"), format!(
                "{{\"simulation_time\":{},\"route\":\"{}\",\"renderer_failed\":{},\"return_weight\":{},\"extra_actor_opacity\":{},\"anchor\":{},\"walk_weight\":{},\"run_weight\":{},\"visual_ads\":{},\"native_reload_seconds\":{},\"native_reload_duration\":{},\"ammo\":{},\"reserve\":{},\"shots\":{}}}",
                sim.time, model.map_or("unavailable", |m| m.presentation_route()), model.is_none_or(|m| m.error().is_some()),
                model.and_then(|m| m.reload_return_weight()).map_or("null".into(), |v| v.to_string()), model.map_or(0., |m| m.reload_extra_opacity()), anchor,
                model.map_or(0., |m| m.walk_weight()), model.map_or(0., |m| m.run_weight()), model.map_or(0., |m| m.visual_ads_amount()),
                model.and_then(|m| m.reload_sample()).map_or("null".into(), |v| v.seconds.to_string()),
                model.and_then(|m| m.tactical_duration()).map_or("null".into(), |v| v.to_string()), sim.player.ammo, sim.player.reserve, sim.stats.shots));
        }
        if capture_sequence == Some("gameplay-jump") {
            let model = authored.as_ref();
            let sample = model.and_then(|model| model.jump_sample());
            let phase = sample.map_or("none", |sample| match sample.phase {
                vector_range::authored_jump::JumpPhase::Takeoff => "takeoff",
                vector_range::authored_jump::JumpPhase::Air => "air",
                vector_range::authored_jump::JumpPhase::Land => "land",
            });
            let seconds = sample.map_or(0., |sample| sample.seconds);
            let holding = sample.is_some_and(|sample| sample.holding_air_endpoint);
            let failed = model.is_none_or(|model| model.error().is_some());
            let crc = model
                .and_then(|model| model.pose_crc32())
                .map_or("null".to_owned(), |v| v.to_string());
            let visual_ads = model.map_or(0., |model| model.visual_ads_amount());
            let _ = std::fs::write(format!("{output}.gameplay.json"), format!(
                "{{\"simulation_time\":{},\"phase\":\"{}\",\"native_seconds\":{},\"holding_air_endpoint\":{},\"grounded\":{},\"accepted_jump_at\":{},\"reload_left\":{},\"visual_ads\":{},\"renderer_failed\":{},\"pose_crc32\":{},\"sampling_hz\":{}}}",
                sim.time, phase, seconds, holding, sim.player.grounded, sim.player.last_jump_at, sim.player.reload_left,
                visual_ads, failed, crc, capture_hz));
        }
        if capture_sequence == Some("gameplay-walk") {
            let native = authored.as_ref().and_then(|model| model.walk_sample());
            let route = if native.is_some() {
                "regular_walk"
            } else {
                "locomotion"
            };
            let native = native
                .map(|seconds| seconds.to_string())
                .unwrap_or_else(|| "null".into());
            let duration = authored
                .as_ref()
                .and_then(|model| model.walk_duration())
                .map(|seconds| seconds.to_string())
                .unwrap_or_else(|| "null".into());
            let failed = authored
                .as_ref()
                .is_none_or(|model| model.error().is_some());
            let _ = std::fs::write(format!("{output}.gameplay.json"), format!(
                "{{\"simulation_time\":{},\"route\":\"{}\",\"native_clip_seconds\":{},\"clip_duration\":{},\"speed\":{},\"grounded\":{},\"sprinting\":{},\"position\":[{},{},{}],\"renderer_failed\":{},\"walk_weight\":{}}}",
                sim.time, route, native, duration, sim.player.speed(), sim.player.grounded, sim.player.sprinting,
                sim.player.position.x, sim.player.position.y, sim.player.position.z, failed, authored.as_ref().map_or(0., |m| m.walk_weight())));
        }
        if capture_sequence == Some("locomotion") {
            let motion = locomotion_state.sample(sim.time, locomotion_input(sim));
            let _ = std::fs::write(format!("{output}.motion.json"), format!(
                "{{\"elapsed\":{},\"target_sprint\":{},\"cosmetic_sprint\":{},\"bob\":{},\"bob_phase\":{},\"speed\":{}}}",
                sequence_elapsed, sim.player.sprinting, motion.sprint, motion.bob, motion.phase, sim.player.speed()));
        }
        if capture_sequence.is_none() || sequence_elapsed >= sequence_duration + 0.2 {
            return true;
        }
    }
    false
}
