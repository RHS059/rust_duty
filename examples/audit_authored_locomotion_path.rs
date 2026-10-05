//! CPU audit of the actual locomotion pack, including interrupted transitions.
//! Output is measurement evidence, not a native-render or skin-contact pass.
use glam::{Mat4, Vec3};
use std::error::Error;
use vector_range::{
    authored_locomotion_path::{AuthoredLocomotionPath, AuthoredLocomotionPathConfig},
    viewmodel_animation::AnimationSet,
};

type Scenario = (&'static str, &'static [(f64, bool, bool)], f64);

fn main() -> Result<(), Box<dyn Error>> {
    let path = std::env::args()
        .nth(1)
        .ok_or("usage: audit_authored_locomotion_path FILE.vra")?;
    let (animation, _, _) = AnimationSet::load_with_companions(path)?;
    let index = |name: &str| {
        animation
            .bones()
            .iter()
            .position(|b| b.name == name)
            .ok_or_else(|| format!("missing audit bone {name}"))
    };
    let hands = [index("hand_l")?, index("hand_r")?];
    let elbows = [index("lowerarm_l")?, index("lowerarm_r")?];
    let shoulders = [index("upperarm_l")?, index("upperarm_r")?];
    let actor = animation
        .actors()
        .iter()
        .position(|a| a.name == "hk416_weapon")
        .ok_or("missing weapon actor")?;
    let ready = animation.sample_clamped("normal_ready", 0.)?;
    let ready_globals = animation.bone_globals(&ready, Mat4::IDENTITY)?;
    let anchors = hands.map(|i| ready.actor_globals[actor].matrix().inverse() * ready_globals[i]);
    let scenarios: [Scenario; 4] = [
        (
            "normal",
            &[(0., false, true), (0.5, true, true), (4.5, false, true)],
            5.5,
        ),
        (
            "rapid_reversals",
            &[
                (0., true, true),
                (0.125, false, true),
                (0.175, true, true),
                (0.3, false, true),
                (0.325, true, true),
                (0.6, false, true),
                (0.65, true, true),
                (1.5, false, true),
            ],
            2.5,
        ),
        (
            "ads_interrupt",
            &[
                (0., true, true),
                (0.8, true, false),
                (1.1, true, true),
                (2., false, true),
            ],
            2.5,
        ),
        (
            "reload_interrupt",
            &[
                (0., true, true),
                (0.6, true, false),
                (1.7, false, true),
                (2., true, true),
                (2.5, false, true),
            ],
            3.,
        ),
    ];
    let entry_duration = animation
        .clips()
        .iter()
        .find(|c| c.name == "normal_entry_connected")
        .ok_or("missing entry")?
        .duration() as f64;
    let loop_duration = animation
        .clips()
        .iter()
        .find(|c| c.name == "normal_loop")
        .ok_or("missing loop")?
        .duration() as f64;
    let mut schedules: Vec<_> = scenarios
        .into_iter()
        .map(|(name, events, duration)| (name.to_owned(), events.to_vec(), duration))
        .collect();
    for index in 0..70 {
        let at = entry_duration + loop_duration * (index as f64 + 0.5) / 70.;
        schedules.push((
            format!("phase_stop_{index:03}"),
            vec![(0., true, true), (at, false, true)],
            at + 0.7,
        ));
    }
    let mut fuzz = Vec::new();
    let mut seed = 739_u32;
    for index in 0..200 {
        seed = seed.wrapping_mul(1664525).wrapping_add(1013904223);
        fuzz.push((index as f64 * 0.025, seed & 1 != 0, seed & 7 != 0));
    }
    fuzz.push((5., false, true));
    schedules.push(("rapid_200_events".into(), fuzz, 6.));
    println!("scenario,time,state,side,anchor_position_error_mm,anchor_rotation_error_deg,wrist_step_mm,elbow_step_mm,shoulder_step_mm,wrist_angle_step_deg,playback_rate,lower_qx,lower_qy,lower_qz,lower_qw,hand_qx,hand_qy,hand_qz,hand_qw");
    for (name, events, duration) in schedules {
        let config = AuthoredLocomotionPathConfig {
            ready_clip: "normal_ready".into(),
            entry_clip: "normal_entry_connected".into(),
            loop_clip: "normal_loop".into(),
            exit_bridge_clips: (0..35)
                .map(|i| format!("normal_exit_bridge_{i:03}"))
                .collect(),
            exit_clip: "normal_exit".into(),
            settle_clip: "normal_settle".into(),
            rate_response_seconds: 0.05,
            residual_decay_seconds: 0.03,
        };
        let mut playback = AuthoredLocomotionPath::new(&animation, config, 0.)?;
        let mut event = 0;
        let mut input = (false, true);
        let mut previous = None;
        for tick in 0..=(duration * 240.) as u32 {
            let time = f64::from(tick) / 240.;
            while event < events.len() && events[event].0 <= time {
                let (at, sprint, enabled) = events[event];
                playback.update(&animation, at, sprint, enabled)?;
                input = (sprint, enabled);
                event += 1;
            }
            playback.update(&animation, time, input.0, input.1)?;
            let pose = playback.pose();
            let globals = animation.bone_globals(pose, Mat4::IDENTITY)?;
            let inv_actor = pose.actor_globals[actor].matrix().inverse();
            for side in 0..2 {
                let current = inv_actor * globals[hands[side]];
                let (_, rotation, translation) = current.to_scale_rotation_translation();
                let (_, expected_rotation, expected_translation) =
                    anchors[side].to_scale_rotation_translation();
                let angle = 2.
                    * rotation
                        .normalize()
                        .dot(expected_rotation.normalize())
                        .abs()
                        .clamp(-1., 1.)
                        .acos()
                        .to_degrees();
                let distance = translation.distance(expected_translation) * 1000.;
                let step = |index: usize| {
                    previous.as_ref().map_or(0., |old: &Vec<Mat4>| {
                        globals[index]
                            .w_axis
                            .truncate()
                            .distance(old[index].w_axis.truncate())
                            * 1000.
                    })
                };
                let (_, lower_q, _) = globals[elbows[side]].to_scale_rotation_translation();
                let (_, hand_q, _) = globals[hands[side]].to_scale_rotation_translation();
                let angular_step = previous.as_ref().map_or(0., |old: &Vec<Mat4>| {
                    let (_, prior_q, _) = old[hands[side]].to_scale_rotation_translation();
                    let mut difference =
                        (prior_q.normalize().conjugate() * hand_q.normalize()).normalize();
                    if difference.w < 0. {
                        difference = -difference;
                    }
                    2. * Vec3::new(difference.x, difference.y, difference.z)
                        .length()
                        .atan2(difference.w)
                        .to_degrees()
                });
                let quaternions = lower_q
                    .to_array()
                    .into_iter()
                    .chain(hand_q.to_array())
                    .map(|v| v.to_string())
                    .collect::<Vec<_>>()
                    .join(",");
                println!("{name},{time:.9},{:?},{side},{distance:.7},{angle:.7},{:.7},{:.7},{:.7},{angular_step:.7},{:.9},{quaternions}", playback.state(), step(hands[side]), step(elbows[side]), step(shoulders[side]), playback.playback_rate());
            }
            previous = Some(globals);
        }
    }
    Ok(())
}
