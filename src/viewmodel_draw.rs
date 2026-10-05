use crate::world_draw::{ACCENT, INK};
use crate::{authored_viewmodel, weapon_model};
use vector_range::draw::facade::*;
use vector_range::scene_lighting::SceneLighting;
use vector_range::{
    muzzle_fx::MuzzleFx, settings::Settings, sim::Simulation, weapon_sway::LayerOffset,
};
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
            reference: args.iter().any(|a| a == "--reference-viewport"),
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
) {
    let lighting = SceneLighting::range().in_view(sim.player.direction());
    set_camera(&Camera3D {
        position: Vec3::ZERO,
        target: vec3(0., 0., -1.),
        up: Vec3::Y,
        fovy: h_fov_to_v(framing.hfov, aspect),
        render_target: Some(rt.clone()),
        aspect: Some(aspect),
        z_near: 0.01,
        z_far: 5.,
    });
    clear_background(if framing.reference {
        Color::new(0.14, 0.19, 0.24, 1.)
    } else {
        Color::new(0., 0., 0., 0.)
    });
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
        authored.set_cant(cant);
        // One rigid root for arms and weapon: sway/action layers keep grips attached.
        let root = vector_range::weapon_sway::compose(view_offset, layers);
        authored.draw(sim.time, lighting, root);
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
