//! Physical-frame bindings for the existing presentation-to-simulation bridge.
//!
//! These methods only map inputs. Callers retain ownership of pause/reset
//! clearing, edge acceptance, frame timestamps, and fixed-step consumption.

use crate::control::{ActionLatch, ButtonInput, ControlSample, IntentLatch};
use crate::platform::input::{InputFrame, KeyCode, MouseButton};

impl InputFrame {
    pub fn key_button(&self, key: KeyCode) -> ButtonInput {
        ButtonInput {
            pressed: self.is_key_pressed(key),
            down: self.is_key_down(key),
        }
    }

    pub fn mouse_button(&self, button: MouseButton) -> ButtonInput {
        ButtonInput {
            pressed: self.is_mouse_button_pressed(button),
            down: self.is_mouse_button_down(button),
        }
    }

    pub fn control_sample(&self, time: f64) -> ControlSample {
        ControlSample {
            ads: self.mouse_button(MouseButton::Right),
            crouch: self.key_button(KeyCode::C),
            prone: self.key_button(KeyCode::Z),
            sprint: self.key_button(KeyCode::LeftShift),
            ctrl: self.key_button(KeyCode::LeftControl),
            cant: self.key_button(KeyCode::X),
            lean_left: self.key_button(KeyCode::Q),
            lean_right: self.key_button(KeyCode::E),
            time,
        }
    }

    pub fn sample_intents(&self, latch: &mut IntentLatch, accept_edges: bool) {
        latch.sample(
            self.is_key_pressed(KeyCode::Space),
            self.is_key_pressed(KeyCode::R),
            self.is_mouse_button_pressed(MouseButton::Left),
            self.is_mouse_button_down(MouseButton::Left),
            accept_edges,
        );
    }

    pub fn sample_actions(
        &self,
        latch: &mut ActionLatch,
        time: f64,
        double_tap: f32,
        accept_input: bool,
    ) {
        latch.sample(
            self.key_button(KeyCode::LeftShift),
            self.key_button(KeyCode::V),
            self.key_button(KeyCode::Key2),
            time,
            double_tap,
            accept_input,
        );
    }

    /// Strafe and forward axes, matching the legacy down-or-pressed rule so a
    /// movement tap between presentation frames is not lost. Not normalized.
    pub fn movement_axes(&self) -> [f32; 2] {
        let active = |key| (self.is_key_down(key) || self.is_key_pressed(key)) as u8 as f32;
        [
            active(KeyCode::D) - active(KeyCode::A),
            active(KeyCode::W) - active(KeyCode::S),
        ]
    }

    /// Preserve the existing held Alt/Super hint; SessionController owns its
    /// rising-edge policy. Native focus remains a separate authoritative signal.
    pub fn focus_shortcut_down(&self) -> bool {
        [
            KeyCode::LeftAlt,
            KeyCode::RightAlt,
            KeyCode::LeftSuper,
            KeyCode::RightSuper,
        ]
        .into_iter()
        .any(|key| self.is_key_down(key))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::control::{ActionIntent, ControlMode, ControlState, DesiredStance};
    use crate::platform::input::InputAccumulator;

    fn tap(input: &mut InputAccumulator, key: KeyCode) {
        input.key_event(key, true, false);
        input.key_event(key, false, false);
    }

    #[test]
    fn controls_preserve_taps_toggle_once_and_keep_prone_priority() {
        let mut input = InputAccumulator::default();
        let mut controls = ControlState::default();
        input.mouse_button_event(MouseButton::Right, true);
        input.mouse_button_event(MouseButton::Right, false);
        tap(&mut input, KeyCode::C);
        tap(&mut input, KeyCode::Z);
        let frame = input.take_frame();
        controls.sample(frame.control_sample(1.), true);
        assert!(controls.intent().ads);
        assert_eq!(controls.intent().stance, DesiredStance::Prone);
        controls.sample(input.take_frame().control_sample(2.), true);
        assert!(controls.intent().ads);
        assert_eq!(controls.intent().stance, DesiredStance::Prone);
    }

    #[test]
    fn ctrl_release_crouches_but_ctrl_x_only_cants() {
        let mut input = InputAccumulator::default();
        let mut controls = ControlState::default();
        input.key_event(KeyCode::LeftControl, true, false);
        controls.sample(input.take_frame().control_sample(0.), true);
        assert_eq!(controls.intent().stance, DesiredStance::Standing);
        input.key_event(KeyCode::LeftControl, false, false);
        controls.sample(input.take_frame().control_sample(0.1), true);
        assert_eq!(controls.intent().stance, DesiredStance::Crouched);

        let mut controls = ControlState::default();
        input.key_event(KeyCode::LeftControl, true, false);
        tap(&mut input, KeyCode::X);
        controls.sample(input.take_frame().control_sample(1.), true);
        assert!(controls.cant());
        input.key_event(KeyCode::LeftControl, false, false);
        controls.sample(input.take_frame().control_sample(1.1), true);
        assert_eq!(controls.intent().stance, DesiredStance::Standing);
        assert!(controls.cant());
    }

    #[test]
    fn hold_controls_and_lean_use_held_state_and_release() {
        let mut input = InputAccumulator::default();
        let mut controls = ControlState::new(ControlMode::Hold);
        input.mouse_button_event(MouseButton::Right, true);
        input.key_event(KeyCode::C, true, false);
        input.key_event(KeyCode::Q, true, false);
        controls.sample(input.take_frame().control_sample(0.), true);
        assert!(controls.intent().ads && controls.intent().crouch());
        assert_eq!(controls.lean(), -1);
        input.mouse_button_event(MouseButton::Right, false);
        input.key_event(KeyCode::C, false, false);
        input.key_event(KeyCode::Q, false, false);
        controls.sample(input.take_frame().control_sample(0.1), true);
        assert!(!controls.intent().ads && !controls.intent().crouch());
        assert_eq!(controls.lean(), 0);
    }

    #[test]
    fn one_shot_taps_wait_for_a_fixed_step_and_are_consumed_once() {
        let mut input = InputAccumulator::default();
        let mut intents = IntentLatch::default();
        tap(&mut input, KeyCode::Space);
        tap(&mut input, KeyCode::R);
        input.mouse_button_event(MouseButton::Left, true);
        input.mouse_button_event(MouseButton::Left, false);
        input.take_frame().sample_intents(&mut intents, true);
        // A presentation frame with no fixed step must not lose queued edges.
        input.take_frame().sample_intents(&mut intents, true);
        let first = intents.take(false);
        assert!(first.jump && first.reload && first.fire);
        let next = intents.take(false);
        assert!(!next.jump && !next.reload && !next.fire);
    }

    #[test]
    fn tactical_sprint_and_action_taps_reach_the_existing_latch() {
        let mut input = InputAccumulator::default();
        let mut actions = ActionLatch::default();
        tap(&mut input, KeyCode::LeftShift);
        input
            .take_frame()
            .sample_actions(&mut actions, 0., 0.3, true);
        assert!(!actions.take().tactical_sprint);
        tap(&mut input, KeyCode::LeftShift);
        tap(&mut input, KeyCode::V);
        tap(&mut input, KeyCode::Key2);
        input
            .take_frame()
            .sample_actions(&mut actions, 0.2, 0.3, true);
        assert_eq!(
            actions.take(),
            ActionIntent {
                tactical_sprint: true,
                mount: true,
                sidearm: true
            }
        );
        assert_eq!(actions.take(), ActionIntent::default());
    }

    #[test]
    fn rejected_edges_do_not_queue_actions_or_one_shots() {
        let mut input = InputAccumulator::default();
        let mut actions = ActionLatch::default();
        let mut intents = IntentLatch::default();
        for key in [KeyCode::Space, KeyCode::R, KeyCode::V, KeyCode::Key2] {
            tap(&mut input, key);
        }
        input.mouse_button_event(MouseButton::Left, true);
        input.mouse_button_event(MouseButton::Left, false);
        let frame = input.take_frame();
        frame.sample_actions(&mut actions, 0., 0.3, false);
        frame.sample_intents(&mut intents, false);
        assert_eq!(actions.take(), ActionIntent::default());
        let intent = intents.take(false);
        assert!(!intent.jump && !intent.reload && !intent.fire);
    }

    #[test]
    fn focus_boundary_clearing_prevents_queued_work_and_resume_fire() {
        let mut input = InputAccumulator::default();
        let mut controls = ControlState::default();
        let mut actions = ActionLatch::default();
        let mut intents = IntentLatch::default();
        for key in [KeyCode::Space, KeyCode::V, KeyCode::C] {
            tap(&mut input, key);
        }
        input.mouse_button_event(MouseButton::Left, true);
        let frame = input.take_frame();
        frame.sample_intents(&mut intents, true);
        frame.sample_actions(&mut actions, 0., 0.3, true);
        controls.sample(frame.control_sample(0.), true);
        assert!(controls.intent().crouch());

        input.focus_event(false);
        assert!(input.take_frame().focus.changed);
        // These resets belong to the session boundary, not the physical-input
        // mapper: pending work from earlier no-step frames must also be lost.
        controls.clear();
        actions.clear();
        intents.clear();
        assert_eq!(actions.take(), ActionIntent::default());
        let step = intents.take(false);
        assert!(!step.jump && !step.reload && !step.fire);
        assert_eq!(controls.intent().stance, DesiredStance::Standing);

        input.focus_event(true);
        input.mouse_button_event(MouseButton::Left, true);
        let returning = input.take_frame();
        assert!(returning.focus.changed);
        returning.sample_intents(&mut intents, false);
        assert!(
            !intents
                .take(returning.is_mouse_button_down(MouseButton::Left))
                .fire
        );
        input.mouse_button_event(MouseButton::Left, false);
        input.take_frame().sample_intents(&mut intents, true);
        input.mouse_button_event(MouseButton::Left, true);
        let deliberate = input.take_frame();
        deliberate.sample_intents(&mut intents, true);
        assert!(
            intents
                .take(deliberate.is_mouse_button_down(MouseButton::Left))
                .fire
        );
    }

    #[test]
    fn movement_taps_cancel_opposites_and_modifiers_stay_separate() {
        let mut input = InputAccumulator::default();
        tap(&mut input, KeyCode::W);
        tap(&mut input, KeyCode::D);
        assert_eq!(input.take_frame().movement_axes(), [1., 1.]);
        for key in [KeyCode::W, KeyCode::S, KeyCode::A, KeyCode::D] {
            input.key_event(key, true, false);
        }
        input.key_event(KeyCode::RightShift, true, false);
        input.key_event(KeyCode::LeftAlt, true, false);
        let frame = input.take_frame();
        assert_eq!(frame.movement_axes(), [0., 0.]);
        assert!(!frame.control_sample(0.).sprint.down);
        assert!(frame.focus_shortcut_down());
    }
}
