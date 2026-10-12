//! Native capture image and telemetry output from the application frame loop.

use glam::Vec3;
use vector_range::draw::facade::{
    backend_info, capture_png, capture_png_with_frame_witness, RenderTarget,
};
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
pub(crate) fn write_frame(frame: CaptureFrame<'_>) -> Result<bool, String> {
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
        let info = backend_info()?;
        let (width, height) = if framing.reference {
            (target.texture.width, target.texture.height)
        } else {
            vector_range::platform::runtime::framebuffer_size()
        };
        let witness = vector_range::draw::frame_witness::requested_identity(std::env::args())?;
        let frame_index = u32::try_from(frames - 8).map_err(|_| "invalid capture frame index")?;
        if let Some(identity) = &witness {
            capture_png_with_frame_witness(
                framing.reference.then_some(target),
                output,
                frame_index,
                vector_range::draw::frame_witness::parse_identity(identity)?,
            );
        } else {
            capture_png(framing.reference.then_some(target), output);
        }
        let mut metadata = capture_metadata(
            &info,
            width,
            height,
            framing.reference,
            framing.hfov,
            sim.player.ads,
            presentation_reload,
        );
        if let Some(identity) = witness {
            metadata["frame_witness"] = serde_json::json!({
                "schema": vector_range::draw::frame_witness::SCHEMA,
                "frame_index": frame_index, "capture_identity": identity,
            });
        }
        write_sidecar(format!("{output}.json"), metadata.to_string())?;
        if capture_sequence.is_some() {
            write_sidecar(format!("{output}.time.json"), format!("{{\"elapsed_seconds\":{},\"normalized_phase\":{},\"visual_duration_seconds\":{},\"simulation_ready_seconds\":{},\"sampling_hz\":{}}}", sequence_elapsed, sequence_phase, sequence_duration, if capture_empty { cfg.empty_reload_time } else if matches!(capture_sequence, Some("ads" | "gameplay-ads")) { cfg.ads_time } else { cfg.reload_time }, capture_hz))?;
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
            write_sidecar(format!("{output}.gameplay.json"), format!(
                "{{\"simulation_time\":{},\"accepted_r_issued\":{},\"route\":\"{}\",\"native_clip_seconds\":{},\"ammo\":{},\"reserve\":{},\"reload_left\":{},\"reload_credit_at\":{},\"reload_ready_at\":{}}}",
                sim.time, gameplay_reload_issued, route, native, sim.player.ammo, sim.player.reserve, sim.player.reload_left, sim.player.reload_credit_at, sim.player.reload_ready_at))?;
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
            write_sidecar(format!("{output}.gameplay.json"), format!(
                "{{\"simulation_time\":{},\"segment\":\"{}\",\"route\":\"{}\",\"clip\":\"{}\",\"native_clip_seconds\":{},\"clip_duration\":{},\"direction\":{},\"ads_requested\":{},\"simulation_ads\":{},\"speed\":{},\"grounded\":{},\"sprinting\":{},\"mantling\":{},\"ammo\":{},\"reserve\":{},\"shots\":{},\"reload_left\":{},\"reload_credit_at\":{},\"reload_ready_at\":{},\"renderer_failed\":{},\"walk_weight\":{},\"walk_seconds\":{},\"run_weight\":{},\"walk_min_rate\":{}}}",
                sim.time, segment, route, clip, native, duration, direction, sim.player.ads_requested,
                sim.player.ads, sim.player.speed(), sim.player.grounded, sim.player.sprinting,
                sim.player.mantle.is_some(), sim.player.ammo, sim.player.reserve, sim.stats.shots,
                sim.player.reload_left, sim.player.reload_credit_at, sim.player.reload_ready_at, failed,
                model.map_or(0., |m| m.walk_weight()), model.and_then(|m| m.walk_sample()).map_or("null".into(), |v| v.to_string()),
                model.map_or(0., |m| m.run_weight()), model.map_or(1., |m| m.walk_min_rate())))?;
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
            write_sidecar(format!("{output}.gameplay.json"), format!(
                "{{\"simulation_time\":{},\"segment\":\"{}\",\"route\":\"{}\",\"sampling_hz\":{},\"renderer_failed\":{},\"pose_crc32\":{},\"walk_weight\":{},\"walk_seconds\":{},\"run_weight\":{},\"directional_weights\":{},\"sprinting\":{},\"ads_requested\":{},\"simulation_ads\":{},\"position\":[{},{},{}],\"velocity\":[{},{},{}],\"ammo\":{},\"shots\":{}}}",
                sim.time, segment, route, capture_hz, failed, model.and_then(|m| m.pose_crc32()).map_or("null".into(), |value| value.to_string()),
                model.map_or(0., |m| m.walk_weight()), walk_seconds, model.map_or(0., |m| m.run_weight()), direction,
                sim.player.sprinting, sim.player.ads_requested, sim.player.ads,
                sim.player.position.x, sim.player.position.y, sim.player.position.z,
                sim.player.velocity.x, sim.player.velocity.y, sim.player.velocity.z,
                sim.player.ammo, sim.stats.shots))?;
        }
        if let Some(sequence) = traversal_capture {
            let pose = sim.action_pose();
            let p = &sim.player;
            let vec =
                |v: Option<Vec3>| v.map_or("null".into(), |v| format!("[{},{},{}]", v.x, v.y, v.z));
            let sway = look_sway.angle_degrees();
            write_sidecar(format!("{output}.gameplay.json"), format!(
                "{{\"simulation_time\":{},\"segment\":\"{}\",\"slot\":{},\"phase\":\"{:?}\",\"normalized\":{},\"weight\":{},\"placeholder\":{},\"left_hand\":{},\"right_hand\":{},\"left_owner\":\"{:?}\",\"right_owner\":\"{:?}\",\"obstruction\":{},\"obstruction_raw\":{},\"fire_blocked\":{},\"mounted\":{},\"position\":[{},{},{}],\"eye_height\":{},\"speed\":{},\"grounded\":{},\"look_sway_degrees\":[{},{}],\"shots\":{}}}",
                sim.time, vector_range::traversal_replay::segment(sequence, sim.time),
                pose.slot.map_or("null".into(), |slot| format!("\"{}\"", slot.name())),
                pose.phase, pose.normalized, pose.weight, pose.placeholder,
                vec(pose.contacts.left_hand), vec(pose.contacts.right_hand),
                pose.contacts.left_owner, pose.contacts.right_owner,
                p.obstruction.amount, p.obstruction.raw, p.obstruction.fire_blocked, p.mount.is_some(),
                p.position.x, p.position.y, p.position.z, p.eye_height, p.speed(), p.grounded,
                sway.x, sway.y, sim.stats.shots))?;
        }
        if capture_sequence == Some("gameplay-return") {
            let model = authored.as_ref();
            let anchor = model
                .and_then(|m| m.presented_anchor())
                .map_or("null".into(), |p| format!("[{},{},{}]", p.x, p.y, p.z));
            write_sidecar(format!("{output}.gameplay.json"), format!(
                "{{\"simulation_time\":{},\"route\":\"{}\",\"renderer_failed\":{},\"return_weight\":{},\"extra_actor_opacity\":{},\"anchor\":{},\"walk_weight\":{},\"run_weight\":{},\"visual_ads\":{},\"native_reload_seconds\":{},\"native_reload_duration\":{},\"ammo\":{},\"reserve\":{},\"shots\":{}}}",
                sim.time, model.map_or("unavailable", |m| m.presentation_route()), model.is_none_or(|m| m.error().is_some()),
                model.and_then(|m| m.reload_return_weight()).map_or("null".into(), |v| v.to_string()), model.map_or(0., |m| m.reload_extra_opacity()), anchor,
                model.map_or(0., |m| m.walk_weight()), model.map_or(0., |m| m.run_weight()), model.map_or(0., |m| m.visual_ads_amount()),
                model.and_then(|m| m.reload_sample()).map_or("null".into(), |v| v.seconds.to_string()),
                model.and_then(|m| m.tactical_duration()).map_or("null".into(), |v| v.to_string()), sim.player.ammo, sim.player.reserve, sim.stats.shots))?;
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
            write_sidecar(format!("{output}.gameplay.json"), format!(
                "{{\"simulation_time\":{},\"phase\":\"{}\",\"native_seconds\":{},\"holding_air_endpoint\":{},\"grounded\":{},\"accepted_jump_at\":{},\"reload_left\":{},\"visual_ads\":{},\"renderer_failed\":{},\"pose_crc32\":{},\"sampling_hz\":{}}}",
                sim.time, phase, seconds, holding, sim.player.grounded, sim.player.last_jump_at, sim.player.reload_left,
                visual_ads, failed, crc, capture_hz))?;
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
            write_sidecar(format!("{output}.gameplay.json"), format!(
                "{{\"simulation_time\":{},\"route\":\"{}\",\"native_clip_seconds\":{},\"clip_duration\":{},\"speed\":{},\"grounded\":{},\"sprinting\":{},\"position\":[{},{},{}],\"renderer_failed\":{},\"walk_weight\":{}}}",
                sim.time, route, native, duration, sim.player.speed(), sim.player.grounded, sim.player.sprinting,
                sim.player.position.x, sim.player.position.y, sim.player.position.z, failed, authored.as_ref().map_or(0., |m| m.walk_weight())))?;
        }
        if capture_sequence == Some("locomotion") {
            let motion = locomotion_state.sample(sim.time, locomotion_input(sim));
            write_sidecar(format!("{output}.motion.json"), format!(
                "{{\"elapsed\":{},\"target_sprint\":{},\"cosmetic_sprint\":{},\"bob\":{},\"bob_phase\":{},\"speed\":{}}}",
                sequence_elapsed, sim.player.sprinting, motion.sprint, motion.bob, motion.phase, sim.player.speed()))?;
        }
        if capture_sequence.is_none() || sequence_elapsed >= sequence_duration + 0.2 {
            return Ok(true);
        }
    }
    Ok(false)
}

/// World-only capture checkpoints use the same backend identity as the final image.
pub(crate) fn write_world_metadata(output: &str) -> Result<(), String> {
    let info = backend_info()?;
    let (width, height) = vector_range::platform::runtime::framebuffer_size();
    let metadata = capture_metadata(&info, width, height, false, 0., 0., None);
    write_sidecar(format!("{output}.json"), metadata.to_string())
}

fn write_sidecar(
    path: impl AsRef<std::path::Path>,
    contents: impl AsRef<[u8]>,
) -> Result<(), String> {
    let path = path.as_ref();
    if let Some(parent) = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
    {
        std::fs::create_dir_all(parent)
            .map_err(|error| format!("create capture directory {}: {error}", parent.display()))?;
    }
    std::fs::write(path, contents)
        .map_err(|error| format!("write capture telemetry {}: {error}", path.display()))
}

fn capture_metadata(
    info: &vector_range::draw::BackendInfo,
    width: u32,
    height: u32,
    reference: bool,
    hfov: f32,
    ads: f32,
    reload_phase: Option<f32>,
) -> serde_json::Value {
    let mut metadata = serde_json::json!({
        "capture": if reference { "native offscreen viewmodel" } else { "native window" },
        "width": width,
        "height": height,
        "requested": info.requested,
        "backend": info.backend,
        "adapter": info.adapter,
    });
    if reference {
        metadata["hfov"] = serde_json::json!(hfov);
        metadata["ads"] = serde_json::json!(ads);
        metadata["reload_phase"] = serde_json::json!(reload_phase);
    }
    metadata
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn capture_metadata_preserves_reference_values_and_escapes_adapter_names() {
        let info = vector_range::draw::BackendInfo {
            requested: "dx12".into(),
            backend: "Dx12".into(),
            adapter: "Adapter \"name\"\nline".into(),
        };
        let metadata = capture_metadata(&info, 960, 540, true, 90., 0.5, None);
        let parsed: serde_json::Value = serde_json::from_str(&metadata.to_string()).unwrap();
        assert_eq!(parsed["width"], 960);
        assert_eq!(parsed["height"], 540);
        assert_eq!(parsed["hfov"], 90.);
        assert_eq!(parsed["ads"], 0.5);
        assert_eq!(parsed["reload_phase"], serde_json::Value::Null);
        assert_eq!(parsed["adapter"], info.adapter);
        assert_eq!(parsed["backend"], "Dx12");
        assert_eq!(parsed["requested"], "dx12");
    }

    #[test]
    fn telemetry_write_errors_are_not_reported_as_completed_captures() {
        let temporary = std::env::temp_dir().join(format!(
            "rust-duty-capture-write-test-{}",
            std::process::id()
        ));
        std::fs::write(&temporary, b"file blocks directory").unwrap();
        let result = write_sidecar(temporary.join("frame.json"), "{}");
        std::fs::remove_file(temporary).unwrap();
        assert!(result.unwrap_err().contains("create capture directory"));
    }
}
