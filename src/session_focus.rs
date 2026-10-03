//! Native focus and a resettable view of Macroquad's input event stream.
//!
//! Macroquad 0.4.14's public input state retains held keys after focus loss,
//! and `clear_input_queue` only clears text. Its input subscriber does not
//! forward Miniquad window focus events. Query Windows directly and maintain
//! our own held state so a missed release cannot keep moving or firing.

use macroquad::miniquad::{EventHandler, KeyCode, KeyMods, MouseButton};
use std::collections::HashSet;

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

pub struct FocusInput {
    subscriber: usize,
    state: InputState,
}

impl Default for FocusInput {
    fn default() -> Self {
        Self::new()
    }
}

impl FocusInput {
    /// Call after Macroquad has initialized its window, on its render thread.
    pub fn new() -> Self {
        Self {
            subscriber: macroquad::input::utils::register_input_subscriber(),
            state: InputState::default(),
        }
    }

    /// Call once at the start of every render frame, even in startup and menus.
    /// Always drain the subscriber so events cannot queue across a pause.
    pub fn sample(&mut self) -> FocusState {
        let native = native_window_focused();
        let mut focus = self.state.begin_frame(native.unwrap_or(true));
        focus.native_supported = native.is_some();
        macroquad::input::utils::repeat_all_miniquad_input(&mut self.state, self.subscriber);
        focus
    }

    /// Pause/reset boundaries may call this as well as clearing gameplay
    /// latches. Held keys must be released and deliberately pressed again.
    pub fn clear(&mut self) {
        self.state.clear();
    }

    pub fn is_key_down(&self, key: KeyCode) -> bool {
        self.state.keys_down.contains(&key)
    }

    pub fn is_key_pressed(&self, key: KeyCode) -> bool {
        self.state.keys_pressed.contains(&key)
    }

    pub fn is_mouse_button_down(&self, button: MouseButton) -> bool {
        self.state.mouse_down.contains(&button)
    }

    pub fn is_mouse_button_pressed(&self, button: MouseButton) -> bool {
        self.state.mouse_pressed.contains(&button)
    }
}

struct InputState {
    focused: bool,
    accept_events: bool,
    keys_down: HashSet<KeyCode>,
    keys_pressed: HashSet<KeyCode>,
    mouse_down: HashSet<MouseButton>,
    mouse_pressed: HashSet<MouseButton>,
}

impl Default for InputState {
    fn default() -> Self {
        Self {
            focused: true,
            accept_events: true,
            keys_down: HashSet::new(),
            keys_pressed: HashSet::new(),
            mouse_down: HashSet::new(),
            mouse_pressed: HashSet::new(),
        }
    }
}

impl InputState {
    fn clear(&mut self) {
        self.keys_down.clear();
        self.keys_pressed.clear();
        self.mouse_down.clear();
        self.mouse_pressed.clear();
    }

    fn begin_frame(&mut self, focused: bool) -> FocusState {
        let changed = self.focused != focused;
        self.focused = focused;
        self.keys_pressed.clear();
        self.mouse_pressed.clear();
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
        self.keys_down.remove(&key);
    }

    fn mouse_button_down_event(&mut self, button: MouseButton, _x: f32, _y: f32) {
        if self.accept_events && self.mouse_down.insert(button) {
            self.mouse_pressed.insert(button);
        }
    }

    fn mouse_button_up_event(&mut self, button: MouseButton, _x: f32, _y: f32) {
        self.mouse_down.remove(&button);
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
