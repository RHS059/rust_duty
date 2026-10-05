//! Pure presentation-to-simulation controls and one-shot intent bridge.
//!
//! Sample toggles once per render frame; read their intent for every fixed step.
//! Gameplay eligibility, stance clearance, and transition timing stay in Simulation.

/// Toggle is the normal player-facing mode; Hold preserves the original controls.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum ControlMode {
    #[default]
    Toggle,
    Hold,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum DesiredStance {
    #[default]
    Standing,
    Crouched,
    Prone,
}

/// A physical button's state in one presentation frame. `pressed` also captures
/// a short tap that was released before that frame was rendered.
#[derive(Clone, Copy, Debug, Default)]
pub struct ButtonInput {
    pub pressed: bool,
    pub down: bool,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct ControlSample {
    pub ads: ButtonInput,
    /// Instant crouch key (C).
    pub crouch: ButtonInput,
    pub prone: ButtonInput,
    pub sprint: ButtonInput,
    /// Left Ctrl: crouch alone, cant modifier with X. The two never overlap.
    pub ctrl: ButtonInput,
    /// X: toggles cant only while Ctrl is held.
    pub cant: ButtonInput,
    pub lean_left: ButtonInput,
    pub lean_right: ButtonInput,
    /// Presentation-frame time in seconds (hold-mode Ctrl chord window).
    pub time: f64,
}

/// Hold-mode Ctrl counts as crouch only after this long without X.
pub const CTRL_CHORD_WINDOW: f64 = 0.15;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct ControlIntent {
    pub ads: bool,
    pub stance: DesiredStance,
}
impl ControlIntent {
    pub fn crouch(self) -> bool {
        self.stance == DesiredStance::Crouched
    }
    pub fn prone(self) -> bool {
        self.stance == DesiredStance::Prone
    }
}

#[derive(Clone, Copy, Debug)]
struct ButtonGate {
    armed: bool,
    was_down: bool,
}
impl Default for ButtonGate {
    fn default() -> Self {
        Self {
            armed: true,
            was_down: false,
        }
    }
}
impl ButtonGate {
    fn clear(&mut self) {
        self.armed = false;
    }
    /// Returns (new press, held). Reject auto-repeat while a button stays down,
    /// and require release after a reset or a button press used while resuming.
    fn sample(&mut self, input: ButtonInput, accept_input: bool) -> (bool, bool) {
        if !input.pressed && !input.down {
            self.armed = true;
        } else if !accept_input {
            self.armed = false;
        }
        let pressed = accept_input && self.armed && input.pressed && !self.was_down;
        let held = accept_input && self.armed && input.down;
        self.was_down = input.down;
        (pressed, held)
    }
}

#[derive(Clone, Copy, Debug, Default)]
pub struct ControlState {
    mode: ControlMode,
    intent: ControlIntent,
    ads: ButtonGate,
    crouch: ButtonGate,
    prone: ButtonGate,
    sprint: ButtonGate,
    ctrl: ButtonGate,
    cant_key: ButtonGate,
    lean_left: ButtonGate,
    lean_right: ButtonGate,
    /// Ctrl hold start, and whether X was used during this hold.
    ctrl_since: Option<f64>,
    ctrl_chorded: bool,
    lean: i8,
    cant: bool,
}
impl ControlState {
    pub fn new(mode: ControlMode) -> Self {
        Self {
            mode,
            ..Self::default()
        }
    }
    pub fn mode(&self) -> ControlMode {
        self.mode
    }
    /// Clear persistent desires on reset, pause, resume, or focus loss. Buttons
    /// held across that boundary cannot restore them until released and pressed.
    pub fn clear(&mut self) {
        self.intent = ControlIntent::default();
        self.ads.clear();
        self.crouch.clear();
        self.prone.clear();
        self.sprint.clear();
        self.ctrl.clear();
        self.cant_key.clear();
        self.lean_left.clear();
        self.lean_right.clear();
        self.ctrl_since = None;
        self.ctrl_chorded = false;
        self.lean = 0;
        self.cant = false;
    }
    /// Call exactly once per presentation frame, including frames with no fixed
    /// step. No toggle operation belongs inside the fixed-step loop.
    pub fn sample(&mut self, sample: ControlSample, accept_input: bool) {
        let (ads_press, ads_hold) = self.ads.sample(sample.ads, accept_input);
        let (crouch_press, crouch_hold) = self.crouch.sample(sample.crouch, accept_input);
        let (prone_press, prone_hold) = self.prone.sample(sample.prone, accept_input);
        let (sprint_press, _) = self.sprint.sample(sample.sprint, accept_input);
        let (ctrl_press, ctrl_hold) = self.ctrl.sample(sample.ctrl, accept_input);
        let (cant_press, _) = self.cant_key.sample(sample.cant, accept_input);
        let (left_press, left_hold) = self.lean_left.sample(sample.lean_left, accept_input);
        let (right_press, right_hold) = self.lean_right.sample(sample.lean_right, accept_input);
        if !accept_input {
            self.intent = ControlIntent::default();
            self.ctrl_since = None;
            self.lean = 0;
            self.cant = false;
            return;
        }
        // Ctrl alone is crouch; Ctrl+X toggles cant. A hold that used X never crouches.
        if ctrl_press {
            self.ctrl_since = Some(sample.time);
            self.ctrl_chorded = false;
        }
        if ctrl_hold && cant_press {
            self.cant = !self.cant;
            self.ctrl_chorded = true;
        }
        let ctrl_released = self.ctrl_since.is_some() && !ctrl_hold;
        let ctrl_crouch_press = ctrl_released && !self.ctrl_chorded;
        let ctrl_crouch_hold = ctrl_hold
            && !self.ctrl_chorded
            && self
                .ctrl_since
                .is_some_and(|since| sample.time - since >= CTRL_CHORD_WINDOW);
        if !ctrl_hold {
            self.ctrl_since = None;
        }
        let crouch_press = crouch_press || ctrl_crouch_press;
        let crouch_hold = crouch_hold || ctrl_crouch_hold;
        match self.mode {
            ControlMode::Toggle => {
                if ads_press {
                    self.intent.ads = !self.intent.ads;
                }
                // A fresh sprint press cancels toggle ADS. ADS can subsequently
                // be pressed while Shift is held to aim and end the sprint.
                if sprint_press {
                    self.intent.ads = false;
                }
                // If both stance keys arrive together, prone wins deterministically.
                let requested = if prone_press {
                    Some(DesiredStance::Prone)
                } else if crouch_press {
                    Some(DesiredStance::Crouched)
                } else {
                    None
                };
                if let Some(stance) = requested {
                    self.intent.stance = if self.intent.stance == stance {
                        DesiredStance::Standing
                    } else {
                        stance
                    };
                }
                // Lean toggles; the other side switches directly.
                for (pressed, side) in [(left_press, -1), (right_press, 1)] {
                    if pressed {
                        self.lean = if self.lean == side { 0 } else { side };
                    }
                }
            }
            ControlMode::Hold => {
                self.intent.ads = ads_hold;
                self.intent.stance = if prone_hold {
                    DesiredStance::Prone
                } else if crouch_hold {
                    DesiredStance::Crouched
                } else {
                    DesiredStance::Standing
                };
                self.lean = right_hold as i8 - left_hold as i8;
            }
        }
    }
    /// Desired lean: -1 left, 0 none, 1 right. Simulation decides how far.
    pub fn lean(&self) -> i8 {
        self.lean
    }
    /// Desired hip cant. Simulation suppresses it while aiming.
    pub fn cant(&self) -> bool {
        self.cant
    }
    /// Apply when the latched jump is consumed, before composing that step's
    /// simulation input. Space exits a toggled lower stance without re-entering
    /// it next tick; Simulation still decides when standing/jumping is possible.
    pub fn request_jump(&mut self) {
        if self.mode == ControlMode::Toggle {
            self.intent.stance = DesiredStance::Standing;
        }
    }
    pub fn intent(&self) -> ControlIntent {
        self.intent
    }
}

#[derive(Clone, Copy, Debug)]
pub struct IntentLatch {
    jump: bool,
    reload: bool,
    fire: bool,
    armed: bool,
}
#[derive(Clone, Copy, Debug, Default)]
pub struct StepIntent {
    pub jump: bool,
    pub reload: bool,
    pub fire: bool,
}
impl Default for IntentLatch {
    fn default() -> Self {
        Self {
            jump: false,
            reload: false,
            fire: false,
            armed: true,
        }
    }
}
impl IntentLatch {
    /// Reset, pause and resume invalidate one-shot work and require a released trigger.
    pub fn clear(&mut self) {
        *self = Self {
            armed: false,
            ..Self::default()
        };
    }
    pub fn sample(
        &mut self,
        jump: bool,
        reload: bool,
        fire_pressed: bool,
        fire_down: bool,
        accept_edges: bool,
    ) {
        if !fire_pressed && !fire_down {
            self.armed = true;
        }
        if accept_edges {
            self.jump |= jump;
            self.reload |= reload;
            self.fire |= fire_pressed && self.armed;
        }
    }
    pub fn take(&mut self, fire_down: bool) -> StepIntent {
        let out = StepIntent {
            jump: self.jump,
            reload: self.reload,
            fire: self.armed && (self.fire || fire_down),
        };
        self.jump = false;
        self.reload = false;
        self.fire = false;
        out
    }
}
/// One-shot traversal/weapon-action intents sampled once per render frame and
/// consumed by the next fixed step. Tactical sprint is a sprint double-tap:
/// a fresh press within `double_tap` seconds of the previous fresh press.
#[derive(Clone, Copy, Debug, Default)]
pub struct ActionLatch {
    tactical_sprint: bool,
    mount: bool,
    sidearm: bool,
    sprint: ButtonGate,
    mount_gate: ButtonGate,
    sidearm_gate: ButtonGate,
    last_sprint_press: Option<f64>,
}
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct ActionIntent {
    pub tactical_sprint: bool,
    pub mount: bool,
    pub sidearm: bool,
}
impl ActionLatch {
    /// Pause, resume, reset and focus loss drop pending intents and require release.
    pub fn clear(&mut self) {
        self.tactical_sprint = false;
        self.mount = false;
        self.sidearm = false;
        self.last_sprint_press = None;
        self.sprint.clear();
        self.mount_gate.clear();
        self.sidearm_gate.clear();
    }
    #[allow(clippy::too_many_arguments)]
    pub fn sample(
        &mut self,
        sprint: ButtonInput,
        mount: ButtonInput,
        sidearm: ButtonInput,
        now: f64,
        double_tap: f32,
        accept_input: bool,
    ) {
        let (sprint_press, _) = self.sprint.sample(sprint, accept_input);
        let (mount_press, _) = self.mount_gate.sample(mount, accept_input);
        let (sidearm_press, _) = self.sidearm_gate.sample(sidearm, accept_input);
        if !accept_input {
            return;
        }
        if sprint_press {
            if self
                .last_sprint_press
                .is_some_and(|last| now - last <= f64::from(double_tap))
            {
                self.tactical_sprint = true;
                self.last_sprint_press = None;
            } else {
                self.last_sprint_press = Some(now);
            }
        }
        self.mount |= mount_press;
        self.sidearm |= sidearm_press;
    }
    pub fn take(&mut self) -> ActionIntent {
        let out = ActionIntent {
            tactical_sprint: self.tactical_sprint,
            mount: self.mount,
            sidearm: self.sidearm,
        };
        self.tactical_sprint = false;
        self.mount = false;
        self.sidearm = false;
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn tap(down: bool) -> ButtonInput {
        ButtonInput {
            pressed: down,
            down,
        }
    }
    #[test]
    fn sprint_double_tap_requests_tactical_sprint_once() {
        let mut l = ActionLatch::default();
        let none = ButtonInput::default();
        l.sample(tap(true), none, none, 0.0, 0.3, true);
        l.sample(tap(false), none, none, 0.1, 0.3, true);
        assert!(!l.take().tactical_sprint);
        l.sample(tap(true), none, none, 0.2, 0.3, true);
        assert!(l.take().tactical_sprint);
        assert!(!l.take().tactical_sprint, "consumed once");
        // Too slow: a second press after the window is a fresh first tap.
        l.sample(tap(false), none, none, 0.3, 0.3, true);
        l.sample(tap(true), none, none, 1.0, 0.3, true);
        l.sample(tap(false), none, none, 1.1, 0.3, true);
        l.sample(tap(true), none, none, 1.5, 0.3, true);
        assert!(!l.take().tactical_sprint);
    }
    #[test]
    fn held_mount_and_sidearm_do_not_repeat_and_clear_requires_release() {
        let mut l = ActionLatch::default();
        let none = ButtonInput::default();
        l.sample(none, tap(true), tap(true), 0., 0.3, true);
        let i = l.take();
        assert!(i.mount && i.sidearm);
        for t in 1..10 {
            l.sample(none, tap(true), tap(true), t as f64, 0.3, true);
            assert_eq!(l.take(), ActionIntent::default());
        }
        l.clear();
        l.sample(none, tap(false), tap(false), 11., 0.3, true);
        l.sample(none, tap(true), none, 12., 0.3, true);
        assert!(l.take().mount);
    }
    #[test]
    fn short_click_is_retained_until_a_simulation_step() {
        let mut l = IntentLatch::default();
        l.sample(false, false, true, false, true);
        l.sample(false, false, false, false, true);
        assert!(l.take(false).fire);
        assert!(!l.take(false).fire);
    }
    #[test]
    fn held_trigger_survives_multiple_simulation_steps() {
        let mut l = IntentLatch::default();
        l.sample(false, false, true, true, true);
        for _ in 0..20 {
            assert!(l.take(true).fire);
        }
    }
    #[test]
    fn reset_while_firing_requires_release_and_repress() {
        let mut l = IntentLatch::default();
        l.sample(true, true, true, true, true);
        l.clear();
        l.sample(false, false, false, true, true);
        for _ in 0..30 {
            let i = l.take(true);
            assert!(!i.fire && !i.jump && !i.reload);
        }
        l.sample(false, false, false, false, true);
        assert!(!l.take(false).fire);
        l.sample(false, false, true, true, true);
        assert!(l.take(true).fire);
    }
    #[test]
    fn resume_click_is_not_a_shot() {
        let mut l = IntentLatch::default();
        l.clear();
        l.sample(false, false, true, true, false);
        assert!(!l.take(true).fire);
        l.sample(false, false, false, false, true);
        assert!(!l.take(false).fire);
    }
}
