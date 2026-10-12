//! Focus-aware input for the active native runtime or legacy Macroquad window.
//!
//! Macroquad 0.4.14's public input state retains held keys after focus loss,
//! and `clear_input_queue` only clears text. Its input subscriber does not
//! forward Miniquad window focus events. Query Windows directly and maintain
//! our own held state so a missed release cannot keep moving or firing.

use macroquad::miniquad::{EventHandler, KeyCode, KeyMods, MouseButton};
use std::collections::HashSet;

use crate::platform::input::{KeyCode as Key, MouseButton as Button};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct FocusState {
    pub unfocused: bool,
    /// A native loss or return. The return frame discards its input too, so
    /// clicking to bring the game forward cannot also resume it.
    pub changed: bool,
    /// Windows is currently supported. Other platforms retain the existing
    /// Alt/Super shortcut fallback; do not mistake that hint for OS focus.
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
    subscriber: Option<usize>,
    state: InputState,
    focus: FocusState,
}

impl Default for FocusInput {
    fn default() -> Self {
        Self::new()
    }
}

impl FocusInput {
    /// Call after the selected backend has initialized its window, on its render thread.
    pub fn new() -> Self {
        #[cfg(feature = "wgpu-runtime")]
        if crate::platform::window::is_active() {
            return Self {
                subscriber: None,
                state: InputState::default(),
                focus: crate::platform::window::snapshot_input().focus.into(),
            };
        }
        Self {
            subscriber: Some(macroquad::input::utils::register_input_subscriber()),
            state: InputState::default(),
            focus: FocusState::default(),
        }
    }

    /// Call once at the start of every render frame, even in startup and menus.
    /// Always drain the subscriber so events cannot queue across a pause.
    pub fn sample(&mut self) -> FocusState {
        #[cfg(feature = "wgpu-runtime")]
        if crate::platform::window::is_active() {
            self.focus = crate::platform::window::snapshot_input().focus.into();
            return self.focus;
        }
        let native = native_window_focused();
        let mut focus = self.state.begin_frame(native.unwrap_or(true));
        focus.native_supported = native.is_some();
        let subscriber = *self
            .subscriber
            .get_or_insert_with(macroquad::input::utils::register_input_subscriber);
        macroquad::input::utils::repeat_all_miniquad_input(&mut self.state, subscriber);
        self.focus = focus;
        focus
    }

    /// Pause/reset boundaries may call this as well as clearing gameplay
    /// latches. Held keys must be released and deliberately pressed again.
    pub fn clear(&mut self) {
        #[cfg(feature = "wgpu-runtime")]
        if crate::platform::window::is_active() {
            crate::platform::window::clear_input();
            return;
        }
        self.state.clear();
    }

    /// Snapshot the frame for the backend-neutral intent/control bridge.
    pub fn frame(&self) -> crate::platform::input::InputFrame {
        #[cfg(feature = "wgpu-runtime")]
        if crate::platform::window::is_active() {
            return crate::platform::window::snapshot_input();
        }
        use crate::platform::input::{InputFrame, KeyCode as Key, MouseButton as Button};
        let key = |key| match key {
            KeyCode::A => Some(Key::A),
            KeyCode::C => Some(Key::C),
            KeyCode::D => Some(Key::D),
            KeyCode::E => Some(Key::E),
            KeyCode::F => Some(Key::F),
            KeyCode::M => Some(Key::M),
            KeyCode::Q => Some(Key::Q),
            KeyCode::R => Some(Key::R),
            KeyCode::S => Some(Key::S),
            KeyCode::V => Some(Key::V),
            KeyCode::W => Some(Key::W),
            KeyCode::X => Some(Key::X),
            KeyCode::Z => Some(Key::Z),
            KeyCode::Key2 => Some(Key::Key2),
            KeyCode::Space => Some(Key::Space),
            KeyCode::Enter => Some(Key::Enter),
            KeyCode::Escape => Some(Key::Escape),
            KeyCode::Tab => Some(Key::Tab),
            KeyCode::LeftShift => Some(Key::LeftShift),
            KeyCode::RightShift => Some(Key::RightShift),
            KeyCode::LeftControl => Some(Key::LeftControl),
            KeyCode::RightControl => Some(Key::RightControl),
            KeyCode::LeftAlt => Some(Key::LeftAlt),
            KeyCode::RightAlt => Some(Key::RightAlt),
            KeyCode::LeftSuper => Some(Key::LeftSuper),
            KeyCode::RightSuper => Some(Key::RightSuper),
            KeyCode::Up => Some(Key::Up),
            KeyCode::Down => Some(Key::Down),
            KeyCode::Left => Some(Key::Left),
            KeyCode::Right => Some(Key::Right),
            KeyCode::Home => Some(Key::Home),
            KeyCode::End => Some(Key::End),
            KeyCode::PageUp => Some(Key::PageUp),
            KeyCode::PageDown => Some(Key::PageDown),
            KeyCode::LeftBracket => Some(Key::LeftBracket),
            KeyCode::RightBracket => Some(Key::RightBracket),
            KeyCode::Minus => Some(Key::Minus),
            KeyCode::Equal => Some(Key::Equal),
            KeyCode::F1 => Some(Key::F1),
            KeyCode::F2 => Some(Key::F2),
            KeyCode::F5 => Some(Key::F5),
            KeyCode::F6 => Some(Key::F6),
            KeyCode::F7 => Some(Key::F7),
            KeyCode::F8 => Some(Key::F8),
            KeyCode::F9 => Some(Key::F9),
            KeyCode::F10 => Some(Key::F10),
            KeyCode::F11 => Some(Key::F11),
            _ => None,
        };
        let button = |button| match button {
            MouseButton::Left => Some(Button::Left),
            MouseButton::Right => Some(Button::Right),
            MouseButton::Middle => Some(Button::Middle),
            _ => None,
        };
        let mouse = macroquad::input::mouse_delta_position();
        let position = macroquad::input::mouse_position();
        InputFrame {
            keys_down: self
                .state
                .keys_down
                .iter()
                .copied()
                .filter_map(key)
                .collect(),
            keys_pressed: self
                .state
                .keys_pressed
                .iter()
                .copied()
                .filter_map(key)
                .collect(),
            keys_released: self
                .state
                .keys_released
                .iter()
                .copied()
                .filter_map(key)
                .collect(),
            mouse_released: self
                .state
                .mouse_released
                .iter()
                .copied()
                .filter_map(button)
                .collect(),
            mouse_down: self
                .state
                .mouse_down
                .iter()
                .copied()
                .filter_map(button)
                .collect(),
            mouse_pressed: self
                .state
                .mouse_pressed
                .iter()
                .copied()
                .filter_map(button)
                .collect(),
            mouse_delta: [
                -mouse.x * macroquad::window::screen_width() * 0.5,
                -mouse.y * macroquad::window::screen_height() * 0.5,
            ],
            mouse_position: [position.0, position.1],
            focus: crate::platform::input::FocusState {
                unfocused: self.focus.unfocused,
                changed: self.focus.changed,
                native_supported: self.focus.native_supported,
            },
        }
    }

    pub fn is_key_down(&self, key: Key) -> bool {
        #[cfg(feature = "wgpu-runtime")]
        if crate::platform::window::is_active() {
            return crate::platform::window::snapshot_input().is_key_down(key);
        }
        self.state.keys_down.contains(&legacy_key(key))
    }

    pub fn is_key_pressed(&self, key: Key) -> bool {
        #[cfg(feature = "wgpu-runtime")]
        if crate::platform::window::is_active() {
            return crate::platform::window::snapshot_input().is_key_pressed(key);
        }
        self.state.keys_pressed.contains(&legacy_key(key))
    }

    pub fn is_mouse_button_down(&self, button: Button) -> bool {
        #[cfg(feature = "wgpu-runtime")]
        if crate::platform::window::is_active() {
            return crate::platform::window::snapshot_input().is_mouse_button_down(button);
        }
        legacy_button(button).is_some_and(|button| self.state.mouse_down.contains(&button))
    }

    pub fn is_mouse_button_pressed(&self, button: Button) -> bool {
        #[cfg(feature = "wgpu-runtime")]
        if crate::platform::window::is_active() {
            return crate::platform::window::snapshot_input().is_mouse_button_pressed(button);
        }
        legacy_button(button).is_some_and(|button| self.state.mouse_pressed.contains(&button))
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

fn legacy_key(key: Key) -> KeyCode {
    match key {
        Key::A => KeyCode::A,
        Key::C => KeyCode::C,
        Key::D => KeyCode::D,
        Key::E => KeyCode::E,
        Key::F => KeyCode::F,
        Key::M => KeyCode::M,
        Key::Q => KeyCode::Q,
        Key::R => KeyCode::R,
        Key::S => KeyCode::S,
        Key::V => KeyCode::V,
        Key::W => KeyCode::W,
        Key::X => KeyCode::X,
        Key::Z => KeyCode::Z,
        Key::Key2 => KeyCode::Key2,
        Key::Space => KeyCode::Space,
        Key::Enter => KeyCode::Enter,
        Key::Escape => KeyCode::Escape,
        Key::Tab => KeyCode::Tab,
        Key::LeftShift => KeyCode::LeftShift,
        Key::RightShift => KeyCode::RightShift,
        Key::LeftControl => KeyCode::LeftControl,
        Key::RightControl => KeyCode::RightControl,
        Key::LeftAlt => KeyCode::LeftAlt,
        Key::RightAlt => KeyCode::RightAlt,
        Key::LeftSuper => KeyCode::LeftSuper,
        Key::RightSuper => KeyCode::RightSuper,
        Key::Up => KeyCode::Up,
        Key::Down => KeyCode::Down,
        Key::Left => KeyCode::Left,
        Key::Right => KeyCode::Right,
        Key::Home => KeyCode::Home,
        Key::End => KeyCode::End,
        Key::PageUp => KeyCode::PageUp,
        Key::PageDown => KeyCode::PageDown,
        Key::LeftBracket => KeyCode::LeftBracket,
        Key::RightBracket => KeyCode::RightBracket,
        Key::Minus => KeyCode::Minus,
        Key::Equal => KeyCode::Equal,
        Key::F1 => KeyCode::F1,
        Key::F2 => KeyCode::F2,
        Key::F5 => KeyCode::F5,
        Key::F6 => KeyCode::F6,
        Key::F7 => KeyCode::F7,
        Key::F8 => KeyCode::F8,
        Key::F9 => KeyCode::F9,
        Key::F10 => KeyCode::F10,
        Key::F11 => KeyCode::F11,
    }
}

fn legacy_button(button: Button) -> Option<MouseButton> {
    match button {
        Button::Left => Some(MouseButton::Left),
        Button::Right => Some(MouseButton::Right),
        Button::Middle => Some(MouseButton::Middle),
        Button::Other(_) => None,
    }
}

struct InputState {
    focused: bool,
    accept_events: bool,
    keys_down: HashSet<KeyCode>,
    keys_pressed: HashSet<KeyCode>,
    keys_released: HashSet<KeyCode>,
    mouse_down: HashSet<MouseButton>,
    mouse_pressed: HashSet<MouseButton>,
    mouse_released: HashSet<MouseButton>,
}

impl Default for InputState {
    fn default() -> Self {
        Self {
            focused: true,
            accept_events: true,
            keys_down: HashSet::new(),
            keys_pressed: HashSet::new(),
            keys_released: HashSet::new(),
            mouse_down: HashSet::new(),
            mouse_pressed: HashSet::new(),
            mouse_released: HashSet::new(),
        }
    }
}

impl InputState {
    fn clear(&mut self) {
        self.keys_down.clear();
        self.keys_pressed.clear();
        self.keys_released.clear();
        self.mouse_down.clear();
        self.mouse_pressed.clear();
        self.mouse_released.clear();
    }

    fn begin_frame(&mut self, focused: bool) -> FocusState {
        let changed = self.focused != focused;
        self.focused = focused;
        self.keys_pressed.clear();
        self.keys_released.clear();
        self.mouse_pressed.clear();
        self.mouse_released.clear();
        self.accept_events = focused && !changed;
        if !self.accept_events {
            self.clear();
        }
        FocusState {
            unfocused: !focused,
            changed,
            native_supported: false,
        }
    }
}

impl EventHandler for InputState {
    fn update(&mut self) {}
    fn draw(&mut self) {}

    fn key_down_event(&mut self, key: KeyCode, _modifiers: KeyMods, repeat: bool) {
        // A held key may still generate repeats after focus returns. A repeat
        // cannot recreate a key that was cleared at the interruption.
        if self.accept_events && !repeat && self.keys_down.insert(key) {
            self.keys_pressed.insert(key);
        }
    }

    fn key_up_event(&mut self, key: KeyCode, _modifiers: KeyMods) {
        if self.keys_down.remove(&key) && self.accept_events {
            self.keys_released.insert(key);
        }
    }

    fn mouse_button_down_event(&mut self, button: MouseButton, _x: f32, _y: f32) {
        if self.accept_events && self.mouse_down.insert(button) {
            self.mouse_pressed.insert(button);
        }
    }

    fn mouse_button_up_event(&mut self, button: MouseButton, _x: f32, _y: f32) {
        if self.mouse_down.remove(&button) && self.accept_events {
            self.mouse_released.insert(button);
        }
    }
}

#[cfg(target_os = "windows")]
fn native_window_focused() -> Option<bool> {
    use std::ffi::c_void;

    #[link(name = "user32")]
    extern "system" {
        fn GetForegroundWindow() -> *mut c_void;
        fn GetWindowThreadProcessId(window: *mut c_void, process_id: *mut u32) -> u32;
    }

    // Rust Duty owns one native game window. Reading the foreground owner
    // detects Alt-Tab, taskbar switches, minimization and click-away alike.
    // A null foreground (e.g. desktop transition) is conservatively unfocused.
    // No global input hook, new dependency, or cursor ownership change is used.
    let focused = unsafe {
        let foreground = GetForegroundWindow();
        if foreground.is_null() {
            false
        } else {
            let mut process_id = 0;
            GetWindowThreadProcessId(foreground, &mut process_id) != 0
                && process_id == std::process::id()
        }
    };
    Some(focused)
}

#[cfg(not(target_os = "windows"))]
fn native_window_focused() -> Option<bool> {
    None
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
    fn neutral_queries_preserve_legacy_modifier_sides_and_mouse_buttons() {
        let mut input = FocusInput {
            subscriber: None,
            state: InputState::default(),
            focus: FocusState::default(),
        };
        input
            .state
            .key_down_event(KeyCode::LeftControl, KeyMods::default(), false);
        input
            .state
            .key_down_event(KeyCode::F11, KeyMods::default(), false);
        input
            .state
            .mouse_button_down_event(MouseButton::Right, 0., 0.);
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
    fn native_focus_conversion_preserves_every_flag() {
        for unfocused in [false, true] {
            for changed in [false, true] {
                for native_supported in [false, true] {
                    let focus = FocusState::from(crate::platform::input::FocusState {
                        unfocused,
                        changed,
                        native_supported,
                    });
                    assert_eq!(
                        focus,
                        FocusState {
                            unfocused,
                            changed,
                            native_supported
                        }
                    );
                }
            }
        }
    }

    #[test]
    fn loss_clears_movement_modifiers_and_fire_without_release_events() {
        let mut input = InputState::default();
        input.key_down_event(KeyCode::W, KeyMods::default(), false);
        input.key_down_event(KeyCode::LeftShift, KeyMods::default(), false);
        input.mouse_button_down_event(MouseButton::Left, 0., 0.);
        let focus = input.begin_frame(false);
        assert!(focus.unfocused && focus.changed);
        assert!(input.keys_down.is_empty() && input.keys_pressed.is_empty());
        assert!(input.mouse_down.is_empty() && input.mouse_pressed.is_empty());
    }

    #[test]
    fn background_and_refocus_clicks_do_not_enter_the_input_state() {
        let mut input = InputState::default();
        for focused in [false, false, true] {
            input.begin_frame(focused);
            input.key_down_event(KeyCode::Enter, KeyMods::default(), false);
            input.mouse_button_down_event(MouseButton::Left, 0., 0.);
            assert!(input.keys_down.is_empty() && input.keys_pressed.is_empty());
            assert!(input.mouse_down.is_empty() && input.mouse_pressed.is_empty());
        }
        input.begin_frame(true);
        input.mouse_button_down_event(MouseButton::Left, 0., 0.);
        assert!(input.mouse_pressed.contains(&MouseButton::Left));
    }

    #[test]
    fn key_repeat_after_refocus_cannot_restore_stuck_movement_or_resume() {
        let mut input = InputState::default();
        input.key_down_event(KeyCode::W, KeyMods::default(), false);
        input.begin_frame(false);
        input.begin_frame(true);
        input.begin_frame(true);
        for key in [KeyCode::W, KeyCode::Enter, KeyCode::Escape] {
            input.key_down_event(key, KeyMods::default(), true);
        }
        assert!(input.keys_down.is_empty() && input.keys_pressed.is_empty());
        input.key_up_event(KeyCode::W, KeyMods::default());
        input.key_down_event(KeyCode::W, KeyMods::default(), false);
        assert!(input.keys_down.contains(&KeyCode::W));
        assert!(input.keys_pressed.contains(&KeyCode::W));
    }

    #[test]
    fn quick_taps_survive_and_pressed_edges_expire_each_frame() {
        let mut input = InputState::default();
        input.key_down_event(KeyCode::Enter, KeyMods::default(), false);
        input.key_up_event(KeyCode::Enter, KeyMods::default());
        input.mouse_button_down_event(MouseButton::Left, 0., 0.);
        input.mouse_button_up_event(MouseButton::Left, 0., 0.);
        assert!(input.keys_pressed.contains(&KeyCode::Enter));
        assert!(input.mouse_pressed.contains(&MouseButton::Left));
        assert!(input.keys_released.contains(&KeyCode::Enter));
        assert!(input.mouse_released.contains(&MouseButton::Left));
        assert!(input.keys_down.is_empty() && input.mouse_down.is_empty());
        input.begin_frame(true);
        assert!(input.keys_pressed.is_empty() && input.mouse_pressed.is_empty());
    }

    #[test]
    fn repeats_do_not_generate_presses_or_remove_valid_holds() {
        let mut input = InputState::default();
        input.key_down_event(KeyCode::W, KeyMods::default(), false);
        input.begin_frame(true);
        input.key_down_event(KeyCode::W, KeyMods::default(), true);
        assert!(input.keys_down.contains(&KeyCode::W));
        assert!(input.keys_pressed.is_empty());
        input.key_up_event(KeyCode::W, KeyMods::default());
        assert!(input.keys_down.is_empty());
    }
}
