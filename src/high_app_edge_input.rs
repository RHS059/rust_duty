//! Opt-in app-input-edge diagnostic. Supplies only ordinary physical-control
//! snapshots. Never writes simulation, health, poses, velocities or source time.
use crate::platform::input::{InputAccumulator, InputFrame, KeyCode, MouseButton};
use crate::sim::Simulation;

pub const RECIPE: &str = "high-onto-app-input-edges/v1";
// Exact successful-manifest status derived from the pinned authored renderer and
// admitted combined manifest. This is not a configurable warning allowlist.
pub const REQUIRED_RENDER_STATUS: &str = "Authored WIP: empty reload, fire, mantle clips unavailable; reload pose crossfades; paired prone runtime remains opt-in WIP";
pub fn renderer_status_valid(warning: Option<&str>, renderer_failed: bool) -> bool {
    !renderer_failed && warning == Some(REQUIRED_RENDER_STATUS)
}

pub const MAX_SECONDS: f64 = 60.;
pub const MAX_RECORDS: u64 = 4_000;
pub const MAX_BYTES: usize = 5 * 1024 * 1024;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Case {
    Pause,
    Reset,
    DebugDeath,
}
impl Case {
    pub fn name(self) -> &'static str {
        match self {
            Self::Pause => "pause",
            Self::Reset => "reset",
            Self::DebugDeath => "debug-death",
        }
    }
    pub fn png_limit(self) -> u32 {
        if self == Self::Pause {
            6
        } else {
            3
        }
    }
}
#[derive(Debug)]
pub struct Options {
    pub case: Case,
    pub output: String,
    pub witness: String,
    pub contract: String,
}
impl Options {
    pub fn parse(args: &[String]) -> Result<Option<Self>, String> {
        if !args.iter().any(|a| a.starts_with("--app-edge")) {
            return Ok(None);
        }
        let prefixes = [
            "--app-edge-case=",
            "--app-edge-output=",
            "--app-edge-witness=",
            "--app-edge-contract=",
        ];
        if args.iter().any(|a| {
            (a.starts_with("--app-edge") && !prefixes.iter().any(|p| a.starts_with(*p)))
                || a.starts_with("--capture")
                || a.starts_with("--combined")
                || a.starts_with("--onehand")
                || a.starts_with("--viewmodel-")
                || a.starts_with("--weapon-asset")
                || a.starts_with("--arms-asset")
                || a.starts_with("--output")
                || a == "--demo"
                || a == "--reference-viewport"
                || a == "--procedural-weapon"
        }) {
            return Err(
                "app-edge fixture rejects all alternate capture, pose and asset routes".into(),
            );
        }
        for flag in ["--no-update", "--hold-controls", "--level=range"] {
            if args.iter().filter(|a| a.as_str() == flag).count() != 1 {
                return Err(format!("app-edge fixture requires exactly one {flag}"));
            }
        }
        if args.iter().filter(|a| a.starts_with("--level=")).count() != 1 {
            return Err("app-edge fixture requires exactly one shipped range".into());
        }
        let one = |prefix: &str| -> Result<String, String> {
            let values: Vec<_> = args.iter().filter_map(|a| a.strip_prefix(prefix)).collect();
            if values.len() != 1 || values[0].is_empty() {
                return Err(format!(
                    "app-edge fixture requires exactly one nonempty {prefix}"
                ));
            }
            Ok(values[0].into())
        };
        one("--animation-manifest=")?;
        one("--settings=")?;
        let case = match one("--app-edge-case=")?.as_str() {
            "pause" => Case::Pause,
            "reset" => Case::Reset,
            "debug-death" => Case::DebugDeath,
            _ => return Err("unknown app-edge case".into()),
        };
        let witness = one("--app-edge-witness=")?;
        let contract = one("--app-edge-contract=")?;
        for digest in [&witness, &contract] {
            crate::draw::frame_witness::parse_identity(digest)?;
            if digest.bytes().all(|b| b == b'0') {
                return Err("pending app-edge identity".into());
            }
        }
        Ok(Some(Self {
            case,
            output: one("--app-edge-output=")?,
            witness,
            contract,
        }))
    }
}
/// Diagnostic setup only: reuse Options::parse(args) from the application entry.
/// The caller validates all app-edge options before awaiting the level menu;
/// only that explicit fixture may skip the ordinary confirmation prompt.
pub fn starts_without_level_menu(args: &[String], app_edge: Option<&Options>) -> bool {
    if app_edge.is_some() {
        return true;
    }
    let menu_capture = args.iter().any(|a| a == "--capture-level-menu");
    !menu_capture
        && args
            .iter()
            .any(|a| a.starts_with("--capture") || a == "--demo")
}

pub fn start() -> (glam::Vec3, f32) {
    (glam::vec3(-8.6, 0., -3.), std::f32::consts::PI)
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Stage {
    Baseline,
    Request,
    Native,
    Paused,
    Resume,
    Tail,
    Cleared,
    Done,
}

pub struct Driver {
    case: Case,
    stage: Stage,
    input: InputAccumulator,
    request_issued: bool,
    pause_frames: u32,
    clear_frames: u32,
    tail_began: f64,
}
impl Driver {
    pub fn new(case: Case) -> Self {
        Self {
            case,
            stage: Stage::Baseline,
            input: InputAccumulator::default(),
            request_issued: false,
            pause_frames: 0,
            clear_frames: 0,
            tail_began: 0.,
        }
    }
    pub fn phase(&self) -> String {
        format!("{:?}", self.stage)
    }
    pub fn done(&self) -> bool {
        self.stage == Stage::Done
    }
    fn tap(&mut self, key: KeyCode) {
        self.input.key_event(key, true, false);
        self.input.key_event(key, false, false);
    }
    pub fn next(&mut self, sim: &Simulation, active: bool) -> Result<InputFrame, String> {
        if !sim.time.is_finite() || sim.time > 8. {
            return Err("app-edge simulation bound exceeded".into());
        }
        let high = sim.high_mantle_presentation();
        match self.stage {
            Stage::Baseline => {
                if !active || sim.time != 0. {
                    return Err("app-edge initial session/state differs".into());
                }
                self.stage = Stage::Request;
            }
            Stage::Request => {
                if !active || sim.player.dead() {
                    return Err("app-edge request interrupted".into());
                }
                if high.is_some() {
                    self.input.key_event(KeyCode::W, false, false);
                    self.stage = Stage::Native;
                } else if !self.request_issued {
                    self.input.key_event(KeyCode::W, true, false);
                    self.tap(KeyCode::Space);
                    self.request_issued = true;
                } else if sim.time > 0.5 {
                    return Err("ordinary jump/forward input did not accept high mantle".into());
                }
            }
            Stage::Native => {
                let h = high.ok_or("native high disappeared before interrupt")?;
                if !active || h.outgoing.is_some() || sim.player.dead() {
                    return Err("unexpected high interrupt before requested app edge".into());
                }
                if h.sample.seconds >= 0.45 {
                    if h.sample.seconds >= 0.80 {
                        return Err("native interrupt window missed".into());
                    }
                    match self.case {
                        Case::Pause => {
                            self.tap(KeyCode::Escape);
                            self.stage = Stage::Paused;
                        }
                        Case::Reset => {
                            self.tap(KeyCode::F2);
                            self.stage = Stage::Cleared;
                        }
                        Case::DebugDeath => {
                            self.tap(KeyCode::F9);
                            self.stage = Stage::Cleared;
                        }
                    }
                }
            }
            Stage::Paused => {
                if active
                    || high.is_none_or(|h| h.outgoing.is_none())
                    || sim.player.mantle.is_some()
                {
                    return Err("Escape did not execute ordinary pause/cancel".into());
                }
                self.pause_frames += 1;
                if self.pause_frames == 3 {
                    self.tap(KeyCode::Enter);
                    self.stage = Stage::Resume;
                }
            }
            Stage::Resume => {
                if !active || high.is_none() {
                    return Err("Enter did not resume cancelled high".into());
                }
                self.tail_began = sim.time;
                self.stage = Stage::Tail;
                self.input.key_event(KeyCode::D, true, false);
                self.input.mouse_button_event(MouseButton::Right, true);
            }
            Stage::Tail => {
                if !active || sim.player.dead() {
                    return Err("app-edge outgoing interrupted".into());
                }
                if sim.time - self.tail_began >= 0.75 {
                    if high.is_some() || sim.player.mantle.is_some() {
                        return Err("cancelled source retained after return".into());
                    }
                    self.stage = Stage::Done;
                }
            }
            Stage::Cleared => {
                if high.is_some()
                    || sim.player.mantle.is_some()
                    || !active
                    || sim.player.dead() != (self.case == Case::DebugDeath)
                {
                    return Err("ordinary F2/F9 did not clear native source".into());
                }
                self.clear_frames += 1;
                if self.clear_frames >= 3 {
                    self.stage = Stage::Done;
                }
            }
            Stage::Done => return Err("app-edge input requested after terminal frame".into()),
        }
        Ok(self.input.take_frame())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn args() -> Vec<String> {
        [
            "game",
            "--no-update",
            "--hold-controls",
            "--level=range",
            "--animation-manifest=private.cfg",
            "--settings=settings.cfg",
            "--app-edge-case=pause",
            "--app-edge-output=new",
            &format!("--app-edge-witness={}", "1".repeat(64)),
            &format!("--app-edge-contract={}", "2".repeat(64)),
        ]
        .iter()
        .map(|s| s.to_string())
        .collect()
    }
    #[test]
    fn app_edge_status_requires_exact_source_pinned_information() {
        assert!(renderer_status_valid(Some(REQUIRED_RENDER_STATUS), false));
        for status in [
            None,
            Some(""),
            Some("unknown"),
            Some("Authored WIP: fire, mantle clips unavailable"),
        ] {
            assert!(!renderer_status_valid(status, false));
        }
        let appended = format!("{REQUIRED_RENDER_STATUS}; high mantle inactive: failure");
        assert!(!renderer_status_valid(Some(&appended), false));
        assert!(!renderer_status_valid(Some(REQUIRED_RENDER_STATUS), true));
    }

    #[test]
    fn app_edge_guard_is_opt_in_and_rejects_mixed_modes() {
        assert!(Options::parse(&["game".into()]).unwrap().is_none());
        assert_eq!(Options::parse(&args()).unwrap().unwrap().case, Case::Pause);
        // Match the production parse-first startup and its shared menu predicate.
        let menu_route = |a: &[String]| {
            Options::parse(a).map(|options| starts_without_level_menu(a, options.as_ref()))
        };
        // All three valid fixtures reach startup without an OS Enter event.
        for (name, case) in [
            ("pause", Case::Pause),
            ("reset", Case::Reset),
            ("debug-death", Case::DebugDeath),
        ] {
            let mut a = args();
            a[6] = format!("--app-edge-case={name}");
            assert_eq!(Options::parse(&a).unwrap().unwrap().case, case);
            assert!(menu_route(&a).unwrap(), "{name}");
            assert_eq!(
                crate::city_level::LevelSelection::from_options(&a, Some("city")).unwrap(),
                crate::city_level::LevelSelection::Range
            );
        }
        for ordinary in [
            vec!["game"],
            vec!["game", "--level=range"],
            vec!["game", "--level=city", "--no-update"],
            vec!["game", "--hold-controls", "--level=range"],
            vec!["game", "--capture-level-menu"],
            vec!["game", "--capture-level-menu", "--demo"],
        ] {
            let a: Vec<String> = ordinary.iter().map(|s| s.to_string()).collect();
            assert!(!menu_route(&a).unwrap(), "{ordinary:?}");
        }
        // Preserve the pre-existing capture/demo menu behavior outside this fixture.
        for legacy in ["--capture-fixtures", "--capture-sequence=high", "--demo"] {
            let a = vec!["game".into(), legacy.into()];
            assert!(menu_route(&a).unwrap(), "{legacy}");
        }
        // Every required fixture argument is checked before choosing a menu route.
        for index in 1..args().len() {
            let mut a = args();
            a.remove(index);
            assert!(menu_route(&a).is_err(), "missing index {index}");
        }
        for invalid in [
            vec!["game", "--app-edge"],
            vec!["game", "--app-edge-case=pause", "--demo"],
            vec!["game", "--app-edge-unknown=x", "--capture-level-menu"],
        ] {
            let a: Vec<String> = invalid.iter().map(|s| s.to_string()).collect();
            assert!(menu_route(&a).is_err(), "{invalid:?}");
        }
        for bad in [
            "--capture-hz=30",
            "--capture-level-menu",
            "--output=legacy.png",
            "--app-edge-witness=bad",
            "--app-edge-contract=",
            "--onehand-observer=old",
            "--combined-deterministic",
            "--viewmodel-time=0",
            "--demo",
            "--reference-viewport",
            "--procedural-weapon",
            "--app-edge-case=reset",
            "--app-edge-unknown=x",
            "--level=city",
        ] {
            let mut a = args();
            a.push(bad.into());
            assert!(Options::parse(&a).is_err(), "{bad}");
            assert!(menu_route(&a).is_err(), "{bad}");
        }
    }
    #[test]
    fn app_edge_request_only_enters_the_existing_input_bridge() {
        let sim = Simulation::new();
        let mut d = Driver::new(Case::Pause);
        assert_eq!(d.next(&sim, true).unwrap().movement_axes(), [0., 0.]);
        let f = d.next(&sim, true).unwrap();
        assert_eq!(f.movement_axes(), [0., 1.]);
        assert!(f.is_key_pressed(KeyCode::Space) && f.is_key_released(KeyCode::Space));
        let mut intents = crate::control::IntentLatch::default();
        f.sample_intents(&mut intents, true);
        assert!(intents.take(false).jump);
        assert!(!intents.take(false).jump);
        assert!(sim.high_mantle_presentation().is_none() && sim.player.mantle.is_none());
        assert_eq!(sim.time, 0.);
    }
}
