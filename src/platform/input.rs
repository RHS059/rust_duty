//! Backend-neutral physical input accumulated between presentation frames.
//!
//! A press and release in the same frame retain both edges. Focus boundaries
//! discard the whole frame, including the click that returned focus. Sampling
//! never advances simulation or changes gameplay latches.

use std::collections::HashSet;

/// Physical keys used by gameplay, menus, and developer hotkeys.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum KeyCode {
    A,
    C,
    D,
    E,
    F,
    M,
    Q,
    R,
    S,
    V,
    W,
    X,
    Z,
    Key2,
    Space,
    Enter,
    Escape,
    Tab,
    LeftShift,
    RightShift,
    LeftControl,
    RightControl,
    LeftAlt,
    RightAlt,
    LeftSuper,
    RightSuper,
    Up,
    Down,
    Left,
    Right,
    Home,
    End,
    PageUp,
    PageDown,
    LeftBracket,
    RightBracket,
    Minus,
    Equal,
    F1,
    F2,
    F5,
    F6,
    F7,
    F8,
    F9,
    F10,
    F11,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum MouseButton {
    Left,
    Right,
    Middle,
    Other(u16),
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct FocusState {
    pub unfocused: bool,
    /// At least one native focus transition occurred since the previous frame.
    /// This remains true if focus was lost and regained between two frames.
    pub changed: bool,
    pub native_supported: bool,
}

#[derive(Clone, Debug, Default)]
pub struct InputFrame {
    pub(crate) keys_down: HashSet<KeyCode>,
    pub(crate) keys_pressed: HashSet<KeyCode>,
    pub(crate) keys_released: HashSet<KeyCode>,
    pub(crate) mouse_down: HashSet<MouseButton>,
    pub(crate) mouse_pressed: HashSet<MouseButton>,
    pub(crate) mouse_released: HashSet<MouseButton>,
    /// Relative motion in physical pixels: positive right and down. Backends
    /// normalize their native convention here, before gameplay sensitivity.
    pub mouse_delta: [f32; 2],
    /// Absolute cursor position in logical window pixels, for UI hit testing.
    pub mouse_position: [f32; 2],
    pub focus: FocusState,
}

impl InputFrame {
    pub fn is_key_down(&self, key: KeyCode) -> bool {
        self.keys_down.contains(&key)
    }
    pub fn is_key_pressed(&self, key: KeyCode) -> bool {
        self.keys_pressed.contains(&key)
    }
    pub fn is_key_released(&self, key: KeyCode) -> bool {
        self.keys_released.contains(&key)
    }
    pub fn is_mouse_button_down(&self, button: MouseButton) -> bool {
        self.mouse_down.contains(&button)
    }
    pub fn is_mouse_button_pressed(&self, button: MouseButton) -> bool {
        self.mouse_pressed.contains(&button)
    }
    pub fn is_mouse_button_released(&self, button: MouseButton) -> bool {
        self.mouse_released.contains(&button)
    }

    /// Discard gameplay input at pause/reset/resume boundaries without losing
    /// native focus information or the cursor location used by the menu.
    pub fn clear(&mut self) {
        self.keys_down.clear();
        self.mouse_down.clear();
        self.clear_edges();
    }

    fn clear_edges(&mut self) {
        self.keys_pressed.clear();
        self.keys_released.clear();
        self.mouse_pressed.clear();
        self.mouse_released.clear();
        self.mouse_delta = [0.; 2];
    }
}

/// Feed native events in their original order, then call `take_frame` exactly
/// once per presentation frame, including while paused or asset-blocked.
#[derive(Clone, Debug, Default)]
pub struct InputAccumulator {
    frame: InputFrame,
}

impl InputAccumulator {
    fn accepts_events(&self) -> bool {
        !self.frame.focus.unfocused && !self.frame.focus.changed
    }

    pub fn key_event(&mut self, key: KeyCode, down: bool, repeat: bool) {
        if !self.accepts_events() {
            return;
        }
        if down {
            // A repeat after clear/refocus must not restore a stale hold.
            if !repeat && self.frame.keys_down.insert(key) {
                self.frame.keys_pressed.insert(key);
            }
        } else if self.frame.keys_down.remove(&key) {
            self.frame.keys_released.insert(key);
        }
    }

    pub fn mouse_button_event(&mut self, button: MouseButton, down: bool) {
        if !self.accepts_events() {
            return;
        }
        if down {
            if self.frame.mouse_down.insert(button) {
                self.frame.mouse_pressed.insert(button);
            }
        } else if self.frame.mouse_down.remove(&button) {
            self.frame.mouse_released.insert(button);
        }
    }

    pub fn mouse_motion(&mut self, dx: f32, dy: f32) {
        if self.accepts_events() {
            self.frame.mouse_delta[0] += dx;
            self.frame.mouse_delta[1] += dy;
        }
    }

    pub fn cursor_moved(&mut self, x: f32, y: f32) {
        self.frame.mouse_position = [x, y];
    }

    pub fn focus_event(&mut self, focused: bool) {
        self.frame.focus.native_supported = true;
        if self.frame.focus.unfocused == focused {
            self.frame.focus.unfocused = !focused;
            self.frame.focus.changed = true;
            self.clear();
        }
    }

    /// Also clear the caller's already-sampled frame and gameplay latches at a
    /// pause/reset/resume boundary. This accumulator cannot invalidate a clone.
    pub fn clear(&mut self) {
        self.frame.clear();
    }

    pub fn take_frame(&mut self) -> InputFrame {
        let frame = self.frame.clone();
        self.frame.clear_edges();
        self.frame.focus.changed = false;
        frame
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn taps_keep_both_edges_without_a_hold_and_edges_expire() {
        let mut input = InputAccumulator::default();
        input.key_event(KeyCode::Enter, true, false);
        input.key_event(KeyCode::Enter, false, false);
        input.mouse_button_event(MouseButton::Left, true);
        input.mouse_button_event(MouseButton::Left, false);
        let frame = input.take_frame();
        assert!(frame.is_key_pressed(KeyCode::Enter));
        assert!(frame.is_key_released(KeyCode::Enter));
        assert!(!frame.is_key_down(KeyCode::Enter));
        assert!(frame.is_mouse_button_pressed(MouseButton::Left));
        assert!(frame.is_mouse_button_released(MouseButton::Left));
        assert!(!frame.is_mouse_button_down(MouseButton::Left));
        let next = input.take_frame();
        assert!(!next.is_key_pressed(KeyCode::Enter));
        assert!(!next.is_key_released(KeyCode::Enter));
        assert!(!next.is_mouse_button_pressed(MouseButton::Left));
        assert!(!next.is_mouse_button_released(MouseButton::Left));
    }

    #[test]
    fn repeats_and_duplicate_downs_preserve_holds_without_new_edges() {
        let mut input = InputAccumulator::default();
        input.key_event(KeyCode::W, true, false);
        input.mouse_button_event(MouseButton::Left, true);
        input.take_frame();
        input.key_event(KeyCode::W, true, true);
        input.key_event(KeyCode::W, true, false);
        input.mouse_button_event(MouseButton::Left, true);
        let frame = input.take_frame();
        assert!(frame.is_key_down(KeyCode::W));
        assert!(!frame.is_key_pressed(KeyCode::W));
        assert!(frame.is_mouse_button_down(MouseButton::Left));
        assert!(!frame.is_mouse_button_pressed(MouseButton::Left));
    }

    #[test]
    fn focus_loss_and_return_discard_holds_edges_and_motion() {
        let mut input = InputAccumulator::default();
        input.key_event(KeyCode::W, true, false);
        input.key_event(KeyCode::LeftShift, true, false);
        input.mouse_button_event(MouseButton::Left, true);
        input.mouse_motion(12., -4.);
        input.focus_event(false);
        let lost = input.take_frame();
        assert!(lost.focus.unfocused && lost.focus.changed && lost.focus.native_supported);
        assert!(!lost.is_key_down(KeyCode::W));
        assert!(!lost.is_key_pressed(KeyCode::LeftShift));
        assert!(!lost.is_mouse_button_down(MouseButton::Left));
        assert_eq!(lost.mouse_delta, [0.; 2]);
        for focus in [false, true] {
            input.focus_event(focus);
            input.key_event(KeyCode::Enter, true, false);
            input.mouse_button_event(MouseButton::Left, true);
            input.mouse_motion(1., 2.);
            let frame = input.take_frame();
            assert!(!frame.is_key_pressed(KeyCode::Enter));
            assert!(!frame.is_mouse_button_pressed(MouseButton::Left));
            assert_eq!(frame.mouse_delta, [0.; 2]);
        }
        input.key_event(KeyCode::W, true, true);
        assert!(!input.take_frame().is_key_down(KeyCode::W));
        input.key_event(KeyCode::W, false, false);
        input.key_event(KeyCode::W, true, false);
        assert!(input.take_frame().is_key_pressed(KeyCode::W));
    }

    #[test]
    fn loss_and_return_between_frames_still_report_a_boundary() {
        let mut input = InputAccumulator::default();
        input.focus_event(false);
        input.focus_event(true);
        input.mouse_button_event(MouseButton::Left, true);
        let frame = input.take_frame();
        assert!(frame.focus.changed && !frame.focus.unfocused);
        assert!(!frame.is_mouse_button_pressed(MouseButton::Left));
        assert!(!input.take_frame().focus.changed);
    }

    #[test]
    fn clear_rejects_repeats_and_motion_is_consumed_once() {
        let mut input = InputAccumulator::default();
        input.key_event(KeyCode::W, true, false);
        input.clear();
        input.key_event(KeyCode::W, true, true);
        assert!(!input.take_frame().is_key_down(KeyCode::W));
        input.cursor_moved(10., 20.);
        input.mouse_motion(2., -3.);
        input.mouse_motion(1., 4.);
        let frame = input.take_frame();
        assert_eq!(frame.mouse_delta, [3., 1.]);
        assert_eq!(frame.mouse_position, [10., 20.]);
        let next = input.take_frame();
        assert_eq!(next.mouse_delta, [0.; 2]);
        assert_eq!(next.mouse_position, [10., 20.]);
    }
}
