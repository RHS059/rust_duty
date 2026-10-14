//! Fixed-timing input scripts for native traversal/weapon-action captures.
//! Input only: no pose, velocity, timer or animation-clock overrides. The same
//! script at the same timestamps gives before/after comparisons once authored
//! clips replace the placeholders.
use crate::sim::Input;
use glam::{vec2, vec3, Vec2, Vec3};

pub const SEQUENCES: [&str; 4] = [
    "gameplay-slide",
    "gameplay-hang",
    "gameplay-obstruct",
    "gameplay-sway",
];

/// Start feet position and yaw in the shipped range.
pub fn start(sequence: &str) -> Option<(Vec3, f32)> {
    let north = -std::f32::consts::FRAC_PI_2;
    match sequence {
        "gameplay-slide" | "gameplay-sway" => Some((vec3(0., 0., 9.), north)),
        "gameplay-hang" => Some((vec3(-24., 0., 5. + crate::sim::RADIUS + 0.3), north)),
        "gameplay-obstruct" => Some((vec3(17., 0., -38.), north)),
        _ => None,
    }
}

pub fn duration(sequence: &str) -> f32 {
    match sequence {
        "gameplay-slide" => 5.5,
        "gameplay-hang" => 4.5,
        "gameplay-obstruct" => 4.0,
        _ => 4.0,
    }
}

pub fn input(sequence: &str, t: f64) -> Input {
    let forward = vec2(0., 1.);
    let within = |a: f64, b: f64| (a..b).contains(&t);
    match sequence {
        "gameplay-slide" => Input {
            movement: if within(0.25, 2.2) || within(2.6, 3.6) {
                forward
            } else {
                Vec2::ZERO
            },
            sprint: within(0.25, 1.0) || within(2.6, 3.4),
            crouch: within(1.0, 2.4),
            prone: within(3.4, 4.6),
            ..Input::default()
        },
        "gameplay-hang" => Input {
            movement: if within(0.25, 1.0) {
                forward
            } else {
                Vec2::ZERO
            },
            jump: within(0.25, 0.26) || within(2.0, 2.01),
            sidearm: within(1.5, 1.51),
            ..Input::default()
        },
        "gameplay-obstruct" => Input {
            movement: if within(0.25, 1.6) {
                forward
            } else if within(2.6, 3.0) {
                -forward
            } else {
                Vec2::ZERO
            },
            fire: within(1.8, 2.0),
            ..Input::default()
        },
        _ => Input::default(),
    }
}

/// Scripted view yaw rate for `gameplay-sway` (radians/second, camera space:
/// positive turns left). Fixed timing for comparison with the reference clip.
pub fn sway_yaw_rate(t: f64) -> f32 {
    let quarter = std::f32::consts::FRAC_PI_2;
    if (0.5..1.0).contains(&t) {
        quarter
    } else if (1.6..2.1).contains(&t) {
        -quarter
    } else {
        0.
    }
}

pub fn segment(sequence: &str, t: f64) -> &'static str {
    let at = |marks: &[(f64, &'static str)]| {
        marks
            .iter()
            .rev()
            .find(|(start, _)| t >= *start)
            .map_or("ready", |(_, name)| *name)
    };
    match sequence {
        "gameplay-slide" => at(&[
            (0.25, "sprint"),
            (1.0, "slide"),
            (2.4, "recover"),
            (2.6, "sprint"),
            (3.4, "dive"),
            (4.6, "prone_recover"),
        ]),
        "gameplay-hang" => at(&[
            (0.25, "jump_catch"),
            (1.5, "sidearm_request"),
            (2.0, "pull_up"),
        ]),
        "gameplay-obstruct" => at(&[(0.25, "approach"), (1.8, "fire_at_wall"), (2.6, "back_off")]),
        _ => at(&[
            (0.5, "turn_left"),
            (1.0, "settle"),
            (1.6, "turn_right"),
            (2.1, "settle"),
        ]),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        action::ActionSlot,
        settings::Settings,
        sim::{Action, Simulation, FIXED_DT},
    };

    /// Replays a script and returns the final simulation plus every tick's slot.
    fn replay(sequence: &str, mut each: impl FnMut(&Simulation)) -> Simulation {
        let mut s = Simulation::new();
        let (pos, yaw) = start(sequence).unwrap();
        s.player.position = pos;
        s.player.yaw = yaw;
        let cfg = Settings::default();
        while s.time < duration(sequence) as f64 {
            let t = s.time;
            s.update(input(sequence, t), &cfg, FIXED_DT);
            each(&s);
        }
        s
    }

    #[test]
    fn slide_script_slides_then_dives() {
        let (mut slid, mut dived) = (false, false);
        let s = replay("gameplay-slide", |s| {
            slid |= matches!(s.player.action, Action::Slide(_));
            dived |= matches!(s.player.action, Action::Dive(_));
        });
        assert!(slid && dived);
        // Prone is released at 4.6 s: the existing stance system stands back up.
        assert!(!s.player.prone && !s.player.crouched);
    }

    #[test]
    fn hang_script_catches_then_pulls_up() {
        let (mut hung, mut pulled) = (false, false);
        let s = replay("gameplay-hang", |s| {
            hung |= matches!(s.player.action, Action::Hang(_));
            pulled |= s.action_pose().slot == Some(ActionSlot::PullUp);
        });
        assert!(hung && pulled);
        assert!((s.player.position.y - 2.7).abs() < 1e-4);
    }

    #[test]
    fn obstruct_script_lowers_then_recovers() {
        let mut lowered = false;
        let s = replay("gameplay-obstruct", |s| {
            lowered |= s.player.obstruction.fire_blocked
        });
        assert!(lowered);
        assert_eq!(s.player.obstruction.amount, 0.);
    }
}
