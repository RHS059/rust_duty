use crate::world_draw::palette::{ACCENT, INK};
use crate::{authored_viewmodel, weapon_model};
use vector_range::draw::facade::*;
use vector_range::scene_lighting::SceneLighting;
use vector_range::{
    muzzle_fx::MuzzleFx, settings::Settings, sim::Simulation, weapon_sway::LayerOffset,
};

/// Explicit, render-only experiment for the normal authored-manifest route.
/// Controller/simulation updates occur before this draw boundary in app.rs.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum RenderDiagnostic {
    Visible,
    Hidden,
    TargetOnly,
}
impl RenderDiagnostic {
    pub(crate) fn from_args(args: &[String]) -> Result<Option<Self>, String> {
        let mut value = None;
        for arg in args.iter().take_while(|arg| arg.as_str() != "--") {
            if arg == "--diagnostic-viewmodel-render"
                || arg.starts_with("--diagnostic-viewmodel-render=")
            {
                if value.is_some() {
                    return Err("duplicate --diagnostic-viewmodel-render".into());
                }
                value =
                    Some(match arg.as_str() {
                        "--diagnostic-viewmodel-render=visible" => Self::Visible,
                        "--diagnostic-viewmodel-render=hidden" => Self::Hidden,
                        "--diagnostic-viewmodel-render=target-only" => Self::TargetOnly,
                        _ => return Err(
                            "--diagnostic-viewmodel-render requires visible, hidden or target-only"
                                .into(),
                        ),
                    });
            }
        }
        Ok(value)
    }

    pub(crate) fn check_route(
        self,
        loaded: bool,
        explicit_manifest: bool,
        locomotion: bool,
        fixed_time: bool,
    ) -> Result<(), String> {
        if !loaded || !explicit_manifest || !locomotion || fixed_time {
            return Err("viewmodel render diagnostic requires the loaded explicit authored animation manifest and its live locomotion controller".into());
        }
        Ok(())
    }

    pub(crate) fn name(self) -> &'static str {
        match self {
            Self::Visible => "visible",
            Self::Hidden => "hidden",
            Self::TargetOnly => "target-only",
        }
    }

    pub(crate) fn record_scene(self, scene: &mut serde_json::Value) {
        scene["viewmodel_render_diagnostic"] = serde_json::json!({
            "schema":"rust-duty-viewmodel-render-isolation/v1",
            "mode":self.name(),
            "viewmodel_submitted":self == Self::Visible,
            "target_clear_and_composite":self != Self::Hidden,
            "scope":"authored_manifest_layer_including_prepare_clear_and_composite",
        });
    }
}

pub(crate) fn submit_weapon_layer(mode: Option<RenderDiagnostic>, draw: impl FnOnce()) {
    if mode == Some(RenderDiagnostic::Hidden) {
        // weapon() normally restores this while compositing. HUD/warnings must
        // keep their screen-space camera even when the entire layer is skipped.
        set_default_camera();
    } else {
        draw();
    }
}

/// Same-binary control for the native authored main-target path.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum TargetDiagnostic {
    Direct,
    Offscreen,
}
impl TargetDiagnostic {
    pub(crate) fn from_args(args: &[String]) -> Result<Option<Self>, String> {
        let mut value = None;
        for arg in args.iter().take_while(|arg| arg.as_str() != "--") {
            if arg == "--diagnostic-viewmodel-target"
                || arg.starts_with("--diagnostic-viewmodel-target=")
            {
                if value.is_some() {
                    return Err("duplicate --diagnostic-viewmodel-target".into());
                }
                value = Some(match arg.as_str() {
                    "--diagnostic-viewmodel-target=direct" => Self::Direct,
                    "--diagnostic-viewmodel-target=offscreen" => Self::Offscreen,
                    _ => {
                        return Err(
                            "--diagnostic-viewmodel-target requires direct or offscreen".into()
                        )
                    }
                });
            }
        }
        Ok(value)
    }
    pub(crate) fn name(self) -> &'static str {
        match self {
            Self::Direct => "direct",
            Self::Offscreen => "offscreen",
        }
    }
    pub(crate) fn record_scene(self, scene: &mut serde_json::Value) {
        scene["viewmodel_target_diagnostic"] = serde_json::json!({
            "schema":"rust-duty-viewmodel-target/v1","mode":self.name(),
            "opaque_order":if self==Self::Direct {"viewmodel_before_world"} else {"world_then_offscreen_layer"},
            "transparent_order":if self==Self::Direct {"whole_viewmodel_after_world"} else {"world_then_offscreen_layer"},
        });
        if self == Self::Direct && scene.get("viewmodel_render_diagnostic").is_some() {
            scene["viewmodel_render_diagnostic"]["target_clear_and_composite"] =
                serde_json::json!(false);
        }
    }
}

impl weapon_model::ResidentBatching {
    pub(crate) fn from_args(args: &[String]) -> Result<Option<Self>, String> {
        let mut value = None;
        for arg in args.iter().take_while(|arg| arg.as_str() != "--") {
            if arg == "--diagnostic-resident-batching"
                || arg.starts_with("--diagnostic-resident-batching=")
            {
                if value.is_some() {
                    return Err("duplicate --diagnostic-resident-batching".into());
                }
                value = Some(match arg.as_str() {
                    "--diagnostic-resident-batching=legacy" => Self::LegacyChunks,
                    "--diagnostic-resident-batching=coalesced" => Self::CoalescedParts,
                    _ => {
                        return Err(
                            "--diagnostic-resident-batching requires legacy or coalesced".into(),
                        )
                    }
                });
            }
        }
        Ok(value)
    }

    pub(crate) fn name(self) -> &'static str {
        match self {
            Self::LegacyChunks => "legacy",
            Self::CoalescedParts => "coalesced",
        }
    }

    pub(crate) fn check_native_route(
        self,
        native: bool,
        reference: bool,
        capture: bool,
        visibility: Option<RenderDiagnostic>,
    ) -> Result<(), String> {
        if !native
            || reference
            || capture
            || matches!(
                visibility,
                Some(RenderDiagnostic::Hidden | RenderDiagnostic::TargetOnly)
            )
        {
            return Err("resident batching diagnostic requires native normal-play authored geometry without capture".into());
        }
        Ok(())
    }

    pub(crate) fn record_scene(self, scene: &mut serde_json::Value) {
        scene["resident_batching_diagnostic"] = serde_json::json!({
            "schema":"rust-duty-resident-batching/v1", "mode":self.name(),
            "scope":"same_part_resident_chunks", "triangle_order":"preserved",
        });
    }
}

pub(crate) fn resident_batching_policy(
    requested: Option<weapon_model::ResidentBatching>,
    native: bool,
    reference: bool,
    capture: bool,
) -> weapon_model::ResidentBatching {
    if native && !reference && !capture {
        requested.unwrap_or(weapon_model::ResidentBatching::CoalescedParts)
    } else {
        weapon_model::ResidentBatching::LegacyChunks
    }
}

pub(crate) fn direct_target_active(
    requested: Option<TargetDiagnostic>,
    visibility: Option<RenderDiagnostic>,
    native: bool,
    authored: bool,
    reference: bool,
    capture: bool,
) -> bool {
    let policy = requested.unwrap_or(if visibility.is_some() {
        TargetDiagnostic::Offscreen
    } else {
        TargetDiagnostic::Direct
    });
    policy == TargetDiagnostic::Direct
        && native
        && authored
        && !reference
        && !capture
        && !matches!(
            visibility,
            Some(RenderDiagnostic::Hidden | RenderDiagnostic::TargetOnly)
        )
}

#[derive(Clone, Copy)]
pub(crate) struct ViewmodelFraming {
    pub(crate) hip: Vec3,
    pub(crate) ads: Vec3,
    pub(crate) hfov: f32,
    pub(crate) hip_rotation: Quat,
    pub(crate) ads_rotation: Quat,
    pub(crate) reference: bool,
    pub(crate) hand_modes: Option<[f32; 4]>,
    pub(crate) left_grip_override: Option<[f32; 3]>,
}
impl ViewmodelFraming {
    pub(crate) fn from_args(args: &[String]) -> Self {
        fn vector(args: &[String], prefix: &str, default: Vec3) -> Vec3 {
            args.iter()
                .find_map(|a| a.strip_prefix(prefix))
                .and_then(|s| {
                    let values = s
                        .split(',')
                        .map(str::parse::<f32>)
                        .collect::<Result<Vec<_>, _>>()
                        .ok()?;
                    (values.len() == 3 && values.iter().all(|v| v.is_finite() && v.abs() <= 5.))
                        .then(|| Vec3::new(values[0], values[1], values[2]))
                })
                .unwrap_or(default)
        }
        let hip_ypr = vector(args, "--viewmodel-hip-ypr=", vec3(0.04118, -0.01252, 0.));
        let ads_ypr = vector(args, "--viewmodel-ads-ypr=", Vec3::ZERO);
        let hand_modes = args
            .iter()
            .find_map(|a| a.strip_prefix("--hand-modes="))
            .and_then(|s| {
                let v = s
                    .split(',')
                    .map(str::parse::<f32>)
                    .collect::<Result<Vec<_>, _>>()
                    .ok()?;
                (v.len() == 4 && v.iter().all(|x| x.is_finite() && (0. ..=1.).contains(x)))
                    .then(|| [v[0], v[1], v[2], v[3]])
            });
        Self {
            reference: args
                .iter()
                .take_while(|arg| arg.as_str() != "--")
                .any(|arg| arg == "--reference-viewport"),
            hand_modes,
            left_grip_override: args
                .iter()
                .any(|a| a.starts_with("--left-grip="))
                .then(|| vector(args, "--left-grip=", Vec3::ZERO).to_array()),
            hip_rotation: Quat::from_euler(EulerRot::YXZ, hip_ypr.x, hip_ypr.y, hip_ypr.z),
            ads_rotation: Quat::from_euler(EulerRot::YXZ, ads_ypr.x, ads_ypr.y, ads_ypr.z),
            hip: vector(args, "--viewmodel-hip=", vec3(0.05930, -0.04831, -0.30806)),
            ads: vector(args, "--viewmodel-ads=", vec3(0., -0.03794, -0.2322)),
            hfov: args
                .iter()
                .find_map(|a| a.strip_prefix("--viewmodel-fov="))
                .and_then(|s| s.parse::<f32>().ok())
                .filter(|v| v.is_finite() && (45. ..=120.).contains(v))
                .unwrap_or(76.),
        }
    }
}
pub(crate) fn h_fov_to_v(h: f32, aspect: f32) -> f32 {
    2. * ((h.to_radians() * 0.5).tan() / aspect).atan()
}
pub(crate) fn locomotion_input(
    sim: &Simulation,
) -> vector_range::locomotion_presentation::LocomotionInput {
    vector_range::locomotion_presentation::LocomotionInput {
        sprint: if sim.player.sprinting || sim.player.mantle.is_some() {
            1.
        } else {
            0.
        },
        speed: sim.player.speed(),
        ads: sim.player.ads,
    }
}
fn set_viewmodel_camera(target: Option<RenderTarget>, aspect: f32, framing: ViewmodelFraming) {
    set_camera(&Camera3D {
        position: Vec3::ZERO,
        target: vec3(0., 0., -1.),
        up: Vec3::Y,
        fovy: h_fov_to_v(framing.hfov, aspect),
        render_target: target,
        aspect: Some(aspect),
        z_near: 0.01,
        z_far: 5.,
    });
}
fn draw_authored_layer(
    sim: &Simulation,
    authored: &mut authored_viewmodel::AuthoredViewmodel,
    lighting: SceneLighting,
    view_offset: Vec3,
    cant: f32,
    layers: &[LayerOffset],
) {
    authored.set_cant(cant);
    let root = vector_range::weapon_sway::compose(view_offset, layers);
    authored.draw(sim.time, lighting, root);
}
/// Main-target submission only: no color/depth clear and no composite. The app
/// chooses before-world for opaque poses, or whole-layer after-world for fades.
pub(crate) fn direct_weapon(
    sim: &Simulation,
    aspect: f32,
    authored: &mut authored_viewmodel::AuthoredViewmodel,
    cfg: &Settings,
    framing: ViewmodelFraming,
    layers: &[LayerOffset],
) {
    set_viewmodel_camera(None, aspect, framing);
    set_depth_range(0., 0.05);
    let lighting = SceneLighting::range().in_view(sim.player.direction());
    let view_offset = cfg.viewmodel_offset(authored.visual_ads_amount());
    let cant = sim.player.cant_visual() * cfg.action.cant_angle.to_radians();
    draw_authored_layer(sim, authored, lighting, view_offset, cant, layers);
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn weapon(
    sim: &Simulation,
    rt: &RenderTarget,
    aspect: f32,
    locomotion_state: &mut vector_range::locomotion_presentation::LocomotionPresentation,
    model: Option<&mut weapon_model::WeaponModel>,
    authored: Option<&mut authored_viewmodel::AuthoredViewmodel>,
    arms: Option<&mut vector_range::arms::ArmModel>,
    animation_state: &mut vector_range::view_animation::ViewAnimation,
    cfg: &Settings,
    walk_translation: vector_range::settings::WalkTranslation,
    framing: ViewmodelFraming,
    presentation_override: Option<f32>,
    muzzle_fx: &mut MuzzleFx,
    barrel_flash: bool,
    layers: &[LayerOffset],
    render_diagnostic: Option<RenderDiagnostic>,
) {
    let lighting = SceneLighting::range().in_view(sim.player.direction());
    set_viewmodel_camera(Some(rt.clone()), aspect, framing);
    clear_background(if framing.reference {
        Color::new(0.14, 0.19, 0.24, 1.)
    } else {
        Color::new(0., 0., 0., 0.)
    });
    if render_diagnostic == Some(RenderDiagnostic::TargetOnly) {
        // Use exactly the normal camera, target clear and full-screen composite.
        // Committed simulation/animation still advance in app.rs; only render
        // preparation and geometry submission below this boundary are omitted.
        composite_viewmodel(rt);
        return;
    }
    // Fade saved hip placement with the same visual transition that poses the
    // weapon. Input intent and gameplay readiness can lead the authored pose.
    let placement_aim = authored.as_ref().map_or_else(
        || {
            if model.is_some() {
                vector_range::reference_motion::visual_ads(sim.player.ads)
            } else {
                sim.player.ads
            }
        },
        |model| model.visual_ads_amount(),
    );
    let view_offset = cfg.viewmodel_offset(placement_aim);
    // Hip cant only: the simulation fades it out as ADS comes in.
    let cant = sim.player.cant_visual() * cfg.action.cant_angle.to_radians();
    if let Some(authored) = authored {
        // One rigid root for arms and weapon: sway/action layers keep grips attached.
        draw_authored_layer(sim, authored, lighting, view_offset, cant, layers);
        composite_viewmodel(rt);
        return;
    }
    // Legacy model paths take the layers' translation only.
    let view_offset = view_offset + layers.iter().map(|l| l.translation).sum::<Vec3>();
    let p = &sim.player;
    let motion = locomotion_state.sample(sim.time, locomotion_input(sim));
    // Legacy/procedural guns have a vertical-only walking component. Keep
    // their sprint, airborne, reload and absolute placement terms untouched.
    let walk_bob = if p.grounded && p.reload_left <= 0. && p.mantle.is_none() {
        motion.bob * (1. - motion.sprint)
    } else {
        0.
    };
    let bob = motion.bob + walk_bob * (walk_translation.gains().y - 1.);
    let reload = if p.reload_left > 0. {
        (p.reload_left * 2.5).sin().abs() * 0.15 + 0.12
    } else {
        0.
    };
    let o = vec3(
        if model.is_some() { 0.18 } else { 0.25 } * (1. - p.ads),
        (if model.is_some() { -0.19 } else { -0.25 }) * (1. - p.ads) - 0.041 * p.ads + bob
            - reload
            - motion.sprint * 0.13,
        -0.32 + p.shot_kick * 0.045,
    ) + view_offset;
    let mut muzzle_position = o + vec3(0., 0.01, -1.04);
    let mut barrel = -Vec3::Z;
    if let Some(model) = model {
        use vector_range::weapon_animation::AnimationInput;
        let progress = (p.reload_left > 0. && p.reload_total > 0.)
            .then(|| (1. - p.reload_left / p.reload_total).clamp(0., 1.));
        let completed =
            progress.is_none() && p.reload_ready_at > 0. && sim.time + 1e-6 >= p.reload_ready_at;
        let progress = if let Some(phase) = presentation_override {
            Some(phase)
        } else {
            animation_state.presentation_progress(
                progress,
                p.reload_total,
                p.reload_empty,
                completed,
                sim.time,
            )
        };
        let credit = if p.reload_empty {
            cfg.empty_reload_credit
        } else {
            cfg.reload_credit
        };
        let animation_input = AnimationInput {
            reload_progress: progress,
            reload_credit_fraction: if p.reload_total > 0. {
                credit / p.reload_total
            } else {
                0.542
            },
            empty_reload: p.reload_empty,
            ads: p.ads,
            recoil: p.shot_kick,
            sprint: motion.sprint,
        };
        let mut animation = animation_state.sample_input(animation_input, completed, sim.time);
        if let Some(grip) = framing.left_grip_override {
            animation.left_grip = grip;
        }
        if let Some(modes) = framing.hand_modes {
            animation.left_hand_blend = modes;
            animation.left_hand_orientation_xyzw = None;
            animation.left_hand_euler_yxz = [0.; 3];
        }
        let visual_ads = vector_range::reference_motion::visual_ads(p.ads);
        let base = framing.hip.lerp(framing.ads, visual_ads) + vec3(0., bob, 0.) + view_offset;
        let frame = vector_range::view_animation::WeaponFrame::with_orientation(
            base,
            framing.hip_rotation.slerp(framing.ads_rotation, visual_ads),
            &animation,
        );
        // Hip cant about the bore; IK hands below read this transform and follow.
        let transform =
            vector_range::weapon_sway::cant_about_bore(frame.matrix, model.muzzle, cant)
                * frame.matrix;
        muzzle_position = transform.transform_point3(model.muzzle);
        let barrel_local = frame.matrix.transform_vector3(-Vec3::Z);
        if barrel_local.length_squared() > 1e-8 {
            barrel = barrel_local.normalize();
        }
        let body_frame = Mat4::from_rotation_translation(
            framing.hip_rotation.slerp(framing.ads_rotation, visual_ads),
            base,
        );
        let hand_frames = animation_state
            .hand_presentation()
            .frames(body_frame, transform);
        if let Some(arms) = arms {
            if framing.hand_modes.is_some() || framing.left_grip_override.is_some() {
                arms.draw_with_hand_modes(
                    transform,
                    &animation,
                    animation.left_hand_blend,
                    lighting,
                );
            } else {
                arms.draw_with_weapon_ik(
                    &hand_frames.targets,
                    hand_frames.free_frame,
                    &animation,
                    hand_frames.free_hands,
                    hand_frames.influences,
                    animation.left_hand_blend,
                    lighting,
                );
            }
        }
        model.draw_pose_with_free_frame(
            transform,
            animation_state
                .hand_presentation()
                .held_magazine_matrix(body_frame, transform),
            &animation,
            lighting,
        );
    } else {
        let dark = Color::new(0.105, 0.14, 0.16, 1.);
        let steel = Color::new(0.25, 0.31, 0.33, 1.);
        let parts = [
            (vec3(0., -0.026, -0.27), vec3(0.115, 0.12, 0.43), dark),
            (vec3(0., -0.020, -0.59), vec3(0.094, 0.088, 0.24), steel),
            (vec3(0., 0.010, -0.82), vec3(0.029, 0.029, 0.26), dark),
            (vec3(0., 0.009, -0.96), vec3(0.049, 0.049, 0.07), steel),
            (vec3(0., -0.078, -0.04), vec3(0.094, 0.11, 0.16), steel),
            (vec3(0., -0.169, -0.21), vec3(0.070, 0.21, 0.12), dark),
            (vec3(0., -0.125, -0.04), vec3(0.064, 0.14, 0.07), dark),
            (vec3(0.061, -0.025, -0.25), vec3(0.004, 0.045, 0.13), ACCENT),
            (vec3(0., 0.040, -0.38), vec3(0.065, 0.010, 0.28), steel),
            (vec3(-0.027, 0.048, -0.20), vec3(0.014, 0.04, 0.019), dark),
            (vec3(0.027, 0.048, -0.20), vec3(0.014, 0.04, 0.019), dark),
            (vec3(0., 0.045, -0.77), vec3(0.008, 0.05, 0.014), INK),
            (
                vec3(-0.012, -0.123, -0.49),
                vec3(0.11, 0.07, 0.16),
                Color::new(0.48, 0.40, 0.30, 1.),
            ),
            (
                vec3(0.055, -0.18, 0.005),
                vec3(0.09, 0.13, 0.11),
                Color::new(0.48, 0.40, 0.30, 1.),
            ),
        ];
        let canted = vector_range::weapon_sway::cant_about_bore(
            Mat4::from_translation(o),
            vec3(0., 0.01, -1.04),
            cant,
        );
        with_model_matrix(canted, || {
            for (pos, size, color) in parts {
                lighting.draw_cube(o + pos, size, None, color);
                draw_cube_wires(o + pos, size, Color::new(0.035, 0.05, 0.06, 1.));
            }
            for i in 0..6 {
                lighting.draw_cube(
                    o + vec3(0., 0.047, -0.28 - i as f32 * 0.038),
                    vec3(0.073, 0.012, 0.014),
                    None,
                    dark,
                );
            }
        });
    }
    if barrel_flash {
        muzzle_fx.draw_barrel(muzzle_position, barrel);
    }
    composite_viewmodel(rt);
}
/// Composite the target using the backend-owned top-left orientation.
pub(crate) fn composite_viewmodel(rt: &RenderTarget) {
    set_default_camera();
    draw_texture_ex(
        &rt.texture,
        0.,
        0.,
        WHITE,
        DrawTextureParams {
            dest_size: Some(vec2(screen_width(), screen_height())),
            ..Default::default()
        },
    );
}

#[cfg(test)]
mod tests {
    use super::*;
    use vector_range::draw::Command;

    #[test]
    fn resident_batching_diagnostic_is_explicit_and_preserves_control_routes() {
        use weapon_model::ResidentBatching::{self, CoalescedParts, LegacyChunks};
        let parse = |args: &[&str]| {
            ResidentBatching::from_args(&args.iter().map(|s| (*s).to_owned()).collect::<Vec<_>>())
        };
        assert_eq!(parse(&[]).unwrap(), None);
        assert_eq!(
            parse(&["--diagnostic-resident-batching=legacy"]).unwrap(),
            Some(LegacyChunks)
        );
        assert_eq!(
            parse(&["--diagnostic-resident-batching=coalesced"]).unwrap(),
            Some(CoalescedParts)
        );
        assert_eq!(
            parse(&["--", "--diagnostic-resident-batching=bad"]).unwrap(),
            None
        );
        for args in [
            vec!["--diagnostic-resident-batching"],
            vec!["--diagnostic-resident-batching=bad"],
            vec![
                "--diagnostic-resident-batching=legacy",
                "--diagnostic-resident-batching=coalesced",
            ],
        ] {
            assert!(parse(&args).is_err());
        }
        for policy in [LegacyChunks, CoalescedParts] {
            assert!(policy
                .check_native_route(true, false, false, Some(RenderDiagnostic::Visible))
                .is_ok());
            for (native, reference, capture, visibility) in [
                (false, false, false, None),
                (true, true, false, None),
                (true, false, true, None),
                (true, false, false, Some(RenderDiagnostic::Hidden)),
                (true, false, false, Some(RenderDiagnostic::TargetOnly)),
            ] {
                assert!(policy
                    .check_native_route(native, reference, capture, visibility)
                    .is_err());
            }
            assert_eq!(
                resident_batching_policy(Some(policy), true, false, false),
                policy
            );
            assert_eq!(
                resident_batching_policy(Some(policy), false, false, false),
                LegacyChunks
            );
            assert_eq!(
                resident_batching_policy(Some(policy), true, true, false),
                LegacyChunks
            );
            assert_eq!(
                resident_batching_policy(Some(policy), true, false, true),
                LegacyChunks
            );
        }
        assert_eq!(
            resident_batching_policy(None, true, false, false),
            CoalescedParts
        );
        let mut scene = serde_json::json!({"world":"unchanged"});
        CoalescedParts.record_scene(&mut scene);
        assert_eq!(scene["resident_batching_diagnostic"]["mode"], "coalesced");
        assert_eq!(scene["world"], "unchanged");
    }

    #[test]
    fn direct_target_policy_is_explicit_and_preserves_capture_legacy_controls() {
        for (name, mode) in [
            ("direct", TargetDiagnostic::Direct),
            ("offscreen", TargetDiagnostic::Offscreen),
        ] {
            assert_eq!(
                TargetDiagnostic::from_args(&[format!("--diagnostic-viewmodel-target={name}")])
                    .unwrap(),
                Some(mode)
            );
        }
        for args in [
            vec!["--diagnostic-viewmodel-target"],
            vec!["--diagnostic-viewmodel-target=no"],
            vec![
                "--diagnostic-viewmodel-target=direct",
                "--diagnostic-viewmodel-target=offscreen",
            ],
        ] {
            assert!(TargetDiagnostic::from_args(
                &args.iter().map(|s| s.to_string()).collect::<Vec<_>>()
            )
            .is_err());
        }
        assert_eq!(
            TargetDiagnostic::from_args(&[
                "--".into(),
                "--diagnostic-viewmodel-target=direct".into()
            ])
            .unwrap(),
            None
        );
        assert!(direct_target_active(None, None, true, true, false, false));
        for (native, authored, reference, capture) in [
            (false, true, false, false),
            (true, false, false, false),
            (true, true, true, false),
            (true, true, false, true),
        ] {
            assert!(!direct_target_active(
                Some(TargetDiagnostic::Direct),
                None,
                native,
                authored,
                reference,
                capture
            ));
        }
        for mode in [
            RenderDiagnostic::Visible,
            RenderDiagnostic::Hidden,
            RenderDiagnostic::TargetOnly,
        ] {
            assert!(!direct_target_active(
                None,
                Some(mode),
                true,
                true,
                false,
                false
            ));
            assert_eq!(
                direct_target_active(
                    Some(TargetDiagnostic::Direct),
                    Some(mode),
                    true,
                    true,
                    false,
                    false
                ),
                mode == RenderDiagnostic::Visible
            );
        }
        assert!(!direct_target_active(
            Some(TargetDiagnostic::Offscreen),
            None,
            true,
            true,
            false,
            false
        ));
        let mut scene = serde_json::json!({});
        RenderDiagnostic::Visible.record_scene(&mut scene);
        TargetDiagnostic::Direct.record_scene(&mut scene);
        assert_eq!(
            scene["viewmodel_render_diagnostic"]["viewmodel_submitted"],
            true
        );
        assert_eq!(
            scene["viewmodel_render_diagnostic"]["target_clear_and_composite"],
            false
        );
        assert_eq!(scene["viewmodel_target_diagnostic"]["mode"], "direct");
    }

    #[test]
    fn direct_authored_recording_keeps_projection_pose_corners_and_hud_without_target_work() {
        let mut sim = Simulation::new();
        sim.player.cant = 0.5;
        let cfg = Settings::default();
        let framing = ViewmodelFraming::from_args(&[]);
        let target = RenderTarget::new(1440, 900, true).unwrap();
        let mut old_model = authored_viewmodel::direct_target_test_fixture();
        let mut direct_model = authored_viewmodel::direct_target_test_fixture();
        let mut locomotion =
            vector_range::locomotion_presentation::LocomotionPresentation::default();
        let mut animation = vector_range::view_animation::ViewAnimation::default();
        let mut effects = MuzzleFx::default();
        begin_frame(1920, 1080, 1.).unwrap();
        weapon(
            &sim,
            &target,
            16. / 9.,
            &mut locomotion,
            None,
            Some(&mut old_model),
            None,
            &mut animation,
            &cfg,
            vector_range::settings::WalkTranslation::default(),
            framing,
            None,
            &mut effects,
            false,
            &[],
            None,
        );
        let old = take_draw_list().unwrap();
        begin_frame(1920, 1080, 1.).unwrap();
        direct_weapon(&sim, 16. / 9., &mut direct_model, &cfg, framing, &[]);
        set_default_camera();
        draw_rectangle(1., 2., 3., 4., WHITE);
        let direct = take_draw_list().unwrap();
        assert!(!direct
            .commands
            .iter()
            .any(|c| matches!(c, Command::Clear(_) | Command::Sprite { .. })));
        let projection = old
            .commands
            .iter()
            .find_map(|c| match c {
                Command::Camera(c) if c.depth_test => Some(c.view_projection),
                _ => None,
            })
            .unwrap();
        let cameras = direct
            .commands
            .iter()
            .filter_map(|c| match c {
                Command::Camera(c) => Some(c),
                _ => None,
            })
            .collect::<Vec<_>>();
        assert!(cameras.iter().all(|c| c.target.is_none()));
        assert!(cameras.iter().any(|c| c.depth_test
            && c.depth_range == [0., 0.05]
            && c.view_projection == projection));
        let hud = cameras.last().unwrap();
        assert!(!hud.depth_test);
        assert_eq!(hud.depth_range, [0., 1.]);
        let meshes = |list: vector_range::draw::DrawList| {
            list.commands
                .into_iter()
                .filter_map(|c| match c {
                    Command::Mesh { mesh, model, blend } => {
                        Some((mesh.vertices, mesh.indices, model, blend))
                    }
                    _ => None,
                })
                .collect::<Vec<_>>()
        };
        let old = meshes(old);
        let direct = meshes(direct);
        assert_eq!(old.len(), 2);
        assert_eq!(old, direct);
    }

    #[test]
    fn diagnostic_is_explicit_closed_and_respects_separator() {
        let args = |items: &[&str]| items.iter().map(|s| (*s).to_owned()).collect::<Vec<_>>();
        assert_eq!(RenderDiagnostic::from_args(&[]).unwrap(), None);
        for (name, expected) in [
            ("visible", RenderDiagnostic::Visible),
            ("hidden", RenderDiagnostic::Hidden),
            ("target-only", RenderDiagnostic::TargetOnly),
        ] {
            assert_eq!(
                RenderDiagnostic::from_args(&[format!("--diagnostic-viewmodel-render={name}")])
                    .unwrap(),
                Some(expected)
            );
        }
        for items in [
            vec!["--diagnostic-viewmodel-render"],
            vec!["--diagnostic-viewmodel-render=no"],
            vec![
                "--diagnostic-viewmodel-render=hidden",
                "--diagnostic-viewmodel-render=visible",
            ],
        ] {
            assert!(RenderDiagnostic::from_args(&args(&items)).is_err());
        }
        assert_eq!(
            RenderDiagnostic::from_args(&args(&["--", "--diagnostic-viewmodel-render=hidden"]))
                .unwrap(),
            None
        );
    }

    #[test]
    fn diagnostic_requires_live_authored_manifest() {
        for mode in [
            RenderDiagnostic::Visible,
            RenderDiagnostic::Hidden,
            RenderDiagnostic::TargetOnly,
        ] {
            assert!(mode.check_route(true, true, true, false).is_ok());
            for inputs in [
                (false, true, true, false),
                (true, false, true, false),
                (true, true, false, false),
                (true, true, true, true),
            ] {
                assert!(mode
                    .check_route(inputs.0, inputs.1, inputs.2, inputs.3)
                    .is_err());
            }
        }
    }

    #[test]
    fn hidden_omits_the_layer_and_restores_hud_camera() {
        begin_frame(960, 540, 1.).unwrap();
        set_camera(&Camera3D {
            position: vec3(1., 2., 3.),
            target: Vec3::ZERO,
            ..Default::default()
        });
        submit_weapon_layer(Some(RenderDiagnostic::Hidden), || {
            panic!("hidden layer must not execute")
        });
        draw_rectangle(1., 2., 3., 4., WHITE);
        let frame = take_draw_list().unwrap();
        let camera = frame
            .commands
            .iter()
            .rev()
            .find_map(|command| match command {
                Command::Camera(camera) => Some(camera),
                _ => None,
            })
            .expect("hidden branch must restore the HUD camera");
        assert!(camera.target.is_none());
        assert_eq!(
            camera.view_projection,
            vector_range::draw::Camera::screen(960, 540).view_projection
        );
        assert_eq!(
            frame
                .commands
                .iter()
                .filter(|command| !matches!(command, Command::Camera(_)))
                .count(),
            1
        );
    }

    #[test]
    fn visible_and_default_submit_once_and_scene_has_explicit_mode() {
        for mode in [
            None,
            Some(RenderDiagnostic::Visible),
            Some(RenderDiagnostic::TargetOnly),
        ] {
            let mut calls = 0;
            submit_weapon_layer(mode, || calls += 1);
            assert_eq!(calls, 1);
        }
        let mut scene = serde_json::json!({"world":"unchanged"});
        RenderDiagnostic::Hidden.record_scene(&mut scene);
        assert_eq!(scene["world"], "unchanged");
        assert_eq!(
            scene["viewmodel_render_diagnostic"]["viewmodel_submitted"],
            false
        );
    }

    #[test]
    fn target_only_keeps_exact_camera_clear_composite_and_hud_without_geometry() {
        let sim = Simulation::new();
        let cfg = Settings::default();
        let target = RenderTarget::new(1440, 900, true).unwrap();
        let framing = ViewmodelFraming::from_args(&[]);
        let mut locomotion =
            vector_range::locomotion_presentation::LocomotionPresentation::default();
        let mut animation = vector_range::view_animation::ViewAnimation::default();
        let mut effects = MuzzleFx::default();
        let mut records = Vec::new();
        for mode in [
            Some(RenderDiagnostic::Visible),
            Some(RenderDiagnostic::TargetOnly),
        ] {
            begin_frame(1920, 1080, 1.).unwrap();
            weapon(
                &sim,
                &target,
                16. / 9.,
                &mut locomotion,
                None,
                None,
                None,
                &mut animation,
                &cfg,
                vector_range::settings::WalkTranslation::default(),
                framing,
                None,
                &mut effects,
                false,
                &[],
                mode,
            );
            draw_rectangle(1., 2., 3., 4., WHITE);
            records.push(take_draw_list().unwrap());
        }
        let target_only = &records[1].commands;
        assert_eq!(target_only.len(), 6);
        let [Command::Camera(_), Command::Camera(camera), Command::Clear(color), Command::Camera(screen), Command::Sprite {
            texture,
            destination,
            tint,
        }, Command::Rect { .. }] = target_only.as_slice()
        else {
            panic!("target-only must retain only target camera/clear and screen composite/HUD");
        };
        assert_eq!(*color, Color::TRANSPARENT);
        assert_eq!(
            camera.target.as_ref().unwrap().texture.id,
            target.texture.id
        );
        assert!(camera.depth_test);
        assert_eq!(texture.id, target.texture.id);
        assert_eq!(*destination, Rect::new(0., 0., 1920., 1080.));
        assert_eq!(*tint, WHITE);
        assert!(screen.target.is_none());
        assert!(!screen.depth_test);
        let visible = &records[0].commands;
        let Command::Camera(visible_camera) = &visible[1] else {
            panic!("missing normal target camera")
        };
        assert_eq!(camera.view_projection, visible_camera.view_projection);
        assert_eq!(
            camera.target.as_ref().unwrap().texture.id,
            visible_camera.target.as_ref().unwrap().texture.id
        );
        let Command::Clear(visible_clear) = &visible[2] else {
            panic!("missing normal target clear")
        };
        assert_eq!(color, visible_clear);
        let suffix = visible.len() - 3;
        let Command::Camera(visible_screen) = &visible[suffix] else {
            panic!("missing normal screen camera")
        };
        assert_eq!(screen.view_projection, visible_screen.view_projection);
        assert!(
            matches!(&visible[suffix+1], Command::Sprite {texture:t,destination:d,tint:c}
            if t.id == texture.id && d == destination && c == tint)
        );
        let mut scene = serde_json::json!({});
        RenderDiagnostic::TargetOnly.record_scene(&mut scene);
        assert_eq!(scene["viewmodel_render_diagnostic"]["mode"], "target-only");
        assert_eq!(
            scene["viewmodel_render_diagnostic"]["viewmodel_submitted"],
            false
        );
        assert_eq!(
            scene["viewmodel_render_diagnostic"]["target_clear_and_composite"],
            true
        );
    }

    #[test]
    fn procedural_weapon_records_cant_scope_then_composites_without_gpu_state() {
        let mut sim = Simulation::new();
        sim.player.cant = 0.7;
        let cfg = Settings::default();
        let target = RenderTarget::new(960, 540, true).unwrap();
        let mut locomotion =
            vector_range::locomotion_presentation::LocomotionPresentation::default();
        let mut animation = vector_range::view_animation::ViewAnimation::default();
        let mut effects = MuzzleFx::default();
        let parent = Mat4::from_rotation_translation(Quat::from_rotation_y(0.3), Vec3::Y);
        let canted = vector_range::weapon_sway::cant_about_bore(
            Mat4::from_translation(vec3(0.25, -0.25, -0.32)),
            vec3(0., 0.01, -1.04),
            0.7 * cfg.action.cant_angle.to_radians(),
        );
        begin_frame(960, 540, 1.).unwrap();
        with_model_matrix(parent, || {
            weapon(
                &sim,
                &target,
                960. / 540.,
                &mut locomotion,
                None,
                None,
                None,
                &mut animation,
                &cfg,
                vector_range::settings::WalkTranslation::default(),
                ViewmodelFraming::from_args(&[]),
                None,
                &mut effects,
                false,
                &[],
                None,
            );
            assert_eq!(current_model_matrix().unwrap(), parent);
        });
        assert_eq!(current_model_matrix().unwrap(), Mat4::IDENTITY);
        let list = take_draw_list().unwrap();
        let meshes: Vec<_> = list
            .commands
            .iter()
            .filter_map(|command| match command {
                Command::Mesh { model, blend, .. } => Some((model, blend)),
                _ => None,
            })
            .collect();
        assert_eq!(
            meshes.len(),
            20,
            "fourteen rifle parts and six rail segments"
        );
        for (model, blend) in meshes {
            assert_eq!(*model, parent * canted);
            assert_eq!(*blend, BlendMode::Alpha);
        }
        assert!(
            matches!(list.commands.last(), Some(Command::Sprite { texture, .. }) if texture.id == target.texture.id)
        );
    }

    #[test]
    fn viewmodel_composite_uses_window_extent_and_backend_target_orientation() {
        let target = RenderTarget::new(640, 360, true).unwrap();
        begin_frame(1920, 1080, 2.).unwrap();
        set_camera(&Camera3D {
            render_target: Some(target.clone()),
            ..Camera3D::default()
        });
        composite_viewmodel(&target);
        let list = take_draw_list().unwrap();
        let [Command::Camera(_), Command::Camera(offscreen), Command::Camera(screen), Command::Sprite {
            texture,
            destination,
            tint,
        }] = list.commands.as_slice()
        else {
            panic!("composition must switch to screen space and record one unflipped sprite");
        };
        assert_eq!(
            offscreen.target.as_ref().unwrap().texture.id,
            target.texture.id
        );
        assert!(screen.target.is_none());
        assert!(!screen.depth_test);
        assert_eq!(texture.id, target.texture.id);
        assert_eq!(*destination, Rect::new(0., 0., 1920., 1080.));
        assert_eq!(*tint, WHITE);
    }
}

#[cfg(test)]
mod calibrated_reference_defaults {
    use super::*;

    #[test]
    fn reference_viewport_obeys_the_launch_end_of_options_boundary() {
        assert!(
            !ViewmodelFraming::from_args(&[
                "--physical-1080p".into(),
                "--".into(),
                "--reference-viewport".into()
            ])
            .reference
        );
        assert!(
            ViewmodelFraming::from_args(&["--reference-viewport".into(), "--".into()]).reference
        );
    }
    #[test]
    fn production_defaults_match_documented_static_calibration() {
        let framing = ViewmodelFraming::from_args(&["--reference-viewport".into()]);
        assert!(framing.reference);
        assert_eq!(framing.hfov, 76.0);
        assert_eq!(framing.hip, vec3(0.05930, -0.04831, -0.30806));
        assert_eq!(framing.ads, vec3(0.0, -0.03794, -0.2322));
        assert_eq!(
            framing.hip_rotation,
            Quat::from_euler(EulerRot::YXZ, 0.04118, -0.01252, 0.0)
        );
        assert_eq!(framing.ads_rotation, Quat::IDENTITY);
        assert_eq!(framing.hand_modes, None);
        assert_eq!(framing.left_grip_override, None);
    }
}
