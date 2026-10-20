//! Focus-aware input from the winit runtime and explicit diagnostic snapshots.
//!
//! Native input accumulation owns held state and focus transitions. Diagnostic
//! frames enter above the same gameplay handlers and never synthesize focus.

use crate::platform::input::{InputFrame, KeyCode as Key, MouseButton as Button};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct FocusState {
    pub unfocused: bool,
    /// A native loss or return. The return frame discards its input too, so
    /// clicking to bring the game forward cannot also resume it.
    pub changed: bool,
    /// The native runtime reported an actual focus event.
    pub native_supported: bool,
}

impl FocusState {
    /// Keep the native level distinct from a one-frame interruption. Reporting
    /// a return edge as still unfocused delays SessionController's own refocus
    /// bookkeeping and would swallow a deliberate press on the following frame.
    pub fn apply_to_session_input(
        self,
        mut input: crate::session::SessionInput,
        capture: bool,
    ) -> crate::session::SessionInput {
        input.window_unfocused = !capture && self.unfocused;
        input.blocked |= !capture && self.changed;
        input
    }
}

pub struct FocusInput {
    focus: FocusState,
    // Explicit diagnostic snapshots only; None preserves ordinary platform input.
    app_edge_frame: Option<InputFrame>,
}

fn native_frame() -> InputFrame {
    #[cfg(feature = "wgpu-runtime")]
    {
        crate::platform::window::snapshot_input()
    }
    #[cfg(not(feature = "wgpu-runtime"))]
    {
        InputFrame::default()
    }
}

impl Default for FocusInput {
    fn default() -> Self {
        Self::new()
    }
}

impl FocusInput {
    /// Call after the native window is initialized, on its render thread.
    pub fn new() -> Self {
        Self {
            focus: native_frame().focus.into(),
            app_edge_frame: None,
        }
    }

    /// Call once at the start of every render frame, including startup and menus.
    pub fn sample(&mut self) -> FocusState {
        self.app_edge_frame = None;
        self.focus = native_frame().focus.into();
        self.focus
    }

    /// Pause/reset boundaries clear held keys and already-sampled diagnostic input.
    pub fn clear(&mut self) {
        if let Some(frame) = &mut self.app_edge_frame {
            frame.clear();
        }
        #[cfg(feature = "wgpu-runtime")]
        crate::platform::window::clear_input();
    }

    /// Real focus remains authoritative and is never synthesized.
    pub fn install_app_edge_frame(&mut self, mut frame: InputFrame) -> Result<(), String> {
        if self.focus.unfocused || self.focus.changed {
            return Err("app-edge fixture interrupted by actual focus boundary".into());
        }
        frame.focus = crate::platform::input::FocusState {
            unfocused: self.focus.unfocused,
            changed: self.focus.changed,
            native_supported: self.focus.native_supported,
        };
        self.app_edge_frame = Some(frame);
        Ok(())
    }

    /// Snapshot the frame for the backend-neutral intent/control bridge.
    pub fn frame(&self) -> InputFrame {
        self.app_edge_frame.clone().unwrap_or_else(native_frame)
    }

    pub fn is_key_down(&self, key: Key) -> bool {
        self.frame().is_key_down(key)
    }

    pub fn is_key_pressed(&self, key: Key) -> bool {
        self.frame().is_key_pressed(key)
    }

    pub fn is_mouse_button_down(&self, button: Button) -> bool {
        self.frame().is_mouse_button_down(button)
    }

    pub fn is_mouse_button_pressed(&self, button: Button) -> bool {
        self.frame().is_mouse_button_pressed(button)
    }
}

impl From<crate::platform::input::FocusState> for FocusState {
    fn from(focus: crate::platform::input::FocusState) -> Self {
        Self {
            unfocused: focus.unfocused,
            changed: focus.changed,
            native_supported: focus.native_supported,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn loss_and_return_between_frames_pauses_then_next_frame_can_resume() {
        use crate::platform::input::InputAccumulator;
        use crate::session::{SessionController, SessionInput};
        let mut input = InputAccumulator::default();
        let mut session = SessionController::default();
        session.set_active(true);
        input.focus_event(false);
        input.focus_event(true);
        let focus = FocusState::from(input.take_frame().focus);
        assert!(!focus.unfocused && focus.changed);
        let transition = session.step(focus.apply_to_session_input(SessionInput::default(), false));
        assert!(transition.paused && !transition.active);
        input.key_event(crate::platform::input::KeyCode::Enter, true, false);
        let next_frame = input.take_frame();
        let next = FocusState::from(next_frame.focus);
        let resumed = session.step(next.apply_to_session_input(
            SessionInput {
                enter_pressed: next_frame.is_key_pressed(Key::Enter),
                enter_down: next_frame.is_key_down(Key::Enter),
                ..SessionInput::default()
            },
            false,
        ));
        assert!(resumed.resumed && resumed.active);
    }

    #[test]
    fn separate_refocus_frame_rejects_return_click_but_next_frame_resumes() {
        use crate::platform::input::InputAccumulator;
        use crate::session::{SessionController, SessionInput};
        for resume_with_enter in [false, true] {
            let mut input = InputAccumulator::default();
            let mut session = SessionController::default();
            session.set_active(true);
            input.focus_event(false);
            let lost = FocusState::from(input.take_frame().focus);
            assert!(
                session
                    .step(lost.apply_to_session_input(SessionInput::default(), false))
                    .paused
            );
            input.focus_event(true);
            input.mouse_button_event(crate::platform::input::MouseButton::Left, true);
            let returned = input.take_frame();
            assert!(!returned.is_mouse_button_pressed(crate::platform::input::MouseButton::Left));
            let focus = FocusState::from(returned.focus);
            assert!(
                !session
                    .step(focus.apply_to_session_input(SessionInput::default(), false))
                    .active
            );
            if resume_with_enter {
                input.key_event(Key::Enter, true, false);
            } else {
                input.mouse_button_event(Button::Left, false);
                input.mouse_button_event(Button::Left, true);
            }
            let next_frame = input.take_frame();
            let next = FocusState::from(next_frame.focus);
            let resumed = session.step(next.apply_to_session_input(
                SessionInput {
                    enter_pressed: next_frame.is_key_pressed(Key::Enter),
                    enter_down: next_frame.is_key_down(Key::Enter),
                    click_pressed: next_frame.is_mouse_button_pressed(Button::Left),
                    click_down: next_frame.is_mouse_button_down(Button::Left),
                    ..SessionInput::default()
                },
                false,
            ));
            assert!(resumed.resumed && resumed.active);
        }
    }

    #[test]
    fn deterministic_capture_ignores_native_focus_without_ignoring_asset_blocks() {
        use crate::session::SessionInput;
        let focus = FocusState {
            unfocused: true,
            changed: true,
            native_supported: true,
        };
        let input = focus.apply_to_session_input(SessionInput::default(), true);
        assert!(!input.window_unfocused && !input.blocked);
        let blocked = focus.apply_to_session_input(
            SessionInput {
                blocked: true,
                ..SessionInput::default()
            },
            true,
        );
        assert!(blocked.blocked);
    }

    #[test]
    fn neutral_queries_preserve_modifier_sides_and_mouse_buttons() {
        use crate::platform::input::InputAccumulator;
        let mut events = InputAccumulator::default();
        events.key_event(Key::LeftControl, true, false);
        events.key_event(Key::F11, true, false);
        events.mouse_button_event(Button::Right, true);
        let mut input = FocusInput::new();
        input.install_app_edge_frame(events.take_frame()).unwrap();
        assert!(input.is_key_down(Key::LeftControl));
        assert!(input.is_key_pressed(Key::LeftControl));
        assert!(!input.is_key_down(Key::RightControl));
        assert!(input.is_key_pressed(Key::F11));
        assert!(input.is_mouse_button_down(Button::Right));
        assert!(input.is_mouse_button_pressed(Button::Right));
        assert!(!input.is_mouse_button_down(Button::Left));
        assert!(!input.is_mouse_button_pressed(Button::Other(4)));
        input.clear();
        assert!(!input.is_key_down(Key::LeftControl));
        assert!(!input.is_mouse_button_pressed(Button::Right));
    }

    #[test]
    fn diagnostics_cannot_replace_an_actual_focus_boundary() {
        for focus in [
            FocusState { unfocused: true, changed: false, native_supported: true },
            FocusState { unfocused: false, changed: true, native_supported: true },
        ] {
            let mut input = FocusInput { focus, app_edge_frame: None };
            assert!(input.install_app_edge_frame(Default::default()).is_err());
        }
    }

    #[test]
    fn native_focus_conversion_preserves_every_flag() {
        for unfocused in [false, true] {
            for changed in [false, true] {
                for native_supported in [false, true] {
                    let focus = FocusState::from(crate::platform::input::FocusState {
                        unfocused, changed, native_supported,
                    });
                    assert_eq!(focus, FocusState { unfocused, changed, native_supported });
                }
            }
        }
    }
}
