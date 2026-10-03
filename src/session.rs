//! Presentation-frame pause/resume state, independent of the renderer and OS.
//!
//! A slow render frame invalidates simulation time; it does not change whether
//! the player is playing. In particular, cursor recapture may itself produce a
//! slow frame on Windows, so making a hitch pause the game traps users in menus.

use crate::clock::FixedClock;

/// Sample once each render frame, including while paused or asset-blocked.
/// `pressed` preserves a quick press/release between frames, whereas `down`
/// detects a new physical press and prevents OS key repeat from toggling again.
#[derive(Clone, Copy, Debug, Default)]
pub struct SessionInput {
    pub esc_pressed: bool,
    pub esc_down: bool,
    pub enter_pressed: bool,
    pub enter_down: bool,
    pub click_pressed: bool,
    pub click_down: bool,
    /// May be a combined Alt/Super held state or a one-frame shortcut event.
    /// Only its rising edge pauses, so holding the modifier cannot undo resume.
    pub focus_shortcut_pressed: bool,
    /// Startup updates are unresolved or required assets are invalid. No input can resume play.
    pub blocked: bool,
    /// Unclamped elapsed presentation time, in seconds.
    pub dt: f64,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct SessionTransition {
    pub active: bool,
    /// Changed from paused to active on this frame.
    pub resumed: bool,
    /// Changed from active to paused on this frame.
    pub paused: bool,
    /// Clear the fixed clock and queued gameplay input, and skip catch-up.
    /// This does not, by itself, request a pause or change cursor capture.
    pub discard_timing: bool,
}

#[derive(Clone, Copy, Debug, Default)]
struct PressEdge {
    was_down: bool,
}

impl PressEdge {
    fn sample(&mut self, pressed: bool, down: bool) -> bool {
        let edge = (pressed || down) && !self.was_down;
        self.was_down = down;
        edge
    }
}

/// Defaults to the paused title/menu state. No platform callbacks are needed.
#[derive(Clone, Copy, Debug, Default)]
pub struct SessionController {
    active: bool,
    escape: PressEdge,
    enter: PressEdge,
    click: PressEdge,
    focus_was_down: bool,
}

impl SessionController {
    pub fn is_active(&self) -> bool {
        self.active
    }

    /// Initialization/capture override. Ordinary play should call `step` so its
    /// transition flags can reset gameplay input and update cursor capture.
    /// Button history is preserved to avoid fabricating held-button presses.
    pub fn set_active(&mut self, active: bool) {
        self.active = active;
    }

    pub fn step(&mut self, input: SessionInput) -> SessionTransition {
        // Consume every button even while paused or blocked. Holding a button
        // across a boundary cannot later turn into a fresh resume request.
        let escape = self.escape.sample(input.esc_pressed, input.esc_down);
        let enter = self.enter.sample(input.enter_pressed, input.enter_down);
        let click = self.click.sample(input.click_pressed, input.click_down);
        let focus = input.focus_shortcut_pressed && !self.focus_was_down;
        self.focus_was_down = input.focus_shortcut_pressed;

        let was_active = self.active;
        self.active = if input.blocked {
            false
        } else if was_active {
            // A click/Enter while already playing is not a resume request and
            // must not cancel Escape (e.g. when pausing while firing).
            !(escape || focus)
        } else {
            // Explicit resume wins a simultaneous focus notification. Focus
            // and elapsed time are not allowed to immediately undo it.
            escape || enter || click
        };

        let resumed = !was_active && self.active;
        let paused = was_active && !self.active;
        let invalid_time =
            !input.dt.is_finite() || !(0.0..=FixedClock::MAX_FRAME).contains(&input.dt);
        SessionTransition {
            active: self.active,
            resumed,
            paused,
            discard_timing: resumed || paused || input.blocked || invalid_time,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn idle() -> SessionInput {
        SessionInput {
            dt: 1.0 / 60.0,
            ..SessionInput::default()
        }
    }

    fn escape() -> SessionInput {
        SessionInput {
            esc_pressed: true,
            esc_down: true,
            ..idle()
        }
    }

    fn enter() -> SessionInput {
        SessionInput {
            enter_pressed: true,
            enter_down: true,
            ..idle()
        }
    }

    fn click() -> SessionInput {
        SessionInput {
            click_pressed: true,
            click_down: true,
            ..idle()
        }
    }

    fn running() -> SessionController {
        let mut session = SessionController::default();
        session.set_active(true);
        session
    }

    #[test]
    fn default_is_paused_without_a_transition() {
        let mut session = SessionController::default();
        assert!(!session.is_active());
        assert_eq!(session.step(idle()), SessionTransition::default());
    }

    #[test]
    fn capture_can_start_active() {
        let mut session = running();
        assert!(session.is_active());
        assert_eq!(
            session.step(idle()),
            SessionTransition {
                active: true,
                ..SessionTransition::default()
            }
        );
    }

    #[test]
    fn escape_resumes_from_menu_and_pauses_after_release() {
        let mut session = SessionController::default();
        let start = session.step(escape());
        assert!(start.active && start.resumed && start.discard_timing);
        assert!(!start.paused);
        session.step(idle());
        let stop = session.step(escape());
        assert!(!stop.active && stop.paused && stop.discard_timing);
        assert!(!stop.resumed);
    }

    #[test]
    fn enter_resumes_and_never_toggles_active_play() {
        let mut session = SessionController::default();
        assert!(session.step(enter()).resumed);
        session.step(idle());
        let next = session.step(enter());
        assert!(next.active && !next.resumed && !next.paused);
    }

    #[test]
    fn click_resumes_and_never_toggles_active_play() {
        let mut session = SessionController::default();
        assert!(session.step(click()).resumed);
        session.step(idle());
        assert_eq!(
            session.step(click()),
            SessionTransition {
                active: true,
                ..SessionTransition::default()
            }
        );
    }

    #[test]
    fn held_escape_does_not_retoggle() {
        let mut session = running();
        assert!(session.step(escape()).paused);
        for _ in 0..120 {
            let state = session.step(SessionInput {
                esc_down: true,
                ..idle()
            });
            assert!(!state.active && !state.resumed && !state.paused);
        }
        session.step(idle());
        assert!(session.step(escape()).resumed);
    }

    #[test]
    fn escape_auto_repeat_does_not_retoggle() {
        let mut session = running();
        session.step(escape());
        for _ in 0..120 {
            assert!(!session.step(escape()).active);
        }
    }

    #[test]
    fn quick_escape_taps_work_without_a_held_frame() {
        let mut session = SessionController::default();
        let tap = SessionInput {
            esc_pressed: true,
            esc_down: false,
            ..idle()
        };
        assert!(session.step(tap).resumed);
        assert!(session.step(tap).paused);
        assert!(session.step(tap).resumed);
    }

    #[test]
    fn quick_enter_and_click_taps_resume() {
        for tap in [
            SessionInput {
                enter_pressed: true,
                ..idle()
            },
            SessionInput {
                click_pressed: true,
                ..idle()
            },
        ] {
            let mut session = SessionController::default();
            assert!(session.step(tap).resumed);
        }
    }

    #[test]
    fn rising_down_recovers_a_missing_pressed_event() {
        let mut session = SessionController::default();
        assert!(
            session
                .step(SessionInput {
                    esc_down: true,
                    ..idle()
                })
                .resumed
        );
    }

    #[test]
    fn resume_frame_hitch_does_not_cancel_resume() {
        for action in [escape(), enter(), click()] {
            let mut session = SessionController::default();
            let state = session.step(SessionInput { dt: 2.0, ..action });
            assert!(state.active && state.resumed && state.discard_timing);
            assert!(!state.paused);
        }
    }

    #[test]
    fn cursor_recapture_hitch_on_next_frame_does_not_repause() {
        let mut session = SessionController::default();
        session.step(enter());
        let state = session.step(SessionInput { dt: 0.8, ..idle() });
        assert!(state.active && state.discard_timing);
        assert!(!state.paused && !state.resumed);
        assert!(session.step(idle()).active);
    }

    #[test]
    fn persistently_low_fps_never_pauses_play() {
        let mut session = running();
        for _ in 0..120 {
            let state = session.step(SessionInput { dt: 0.5, ..idle() });
            assert!(state.active && state.discard_timing);
            assert!(!state.paused);
        }
    }

    #[test]
    fn invalid_elapsed_time_discards_without_pausing() {
        for dt in [-0.01, f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
            let mut session = running();
            let state = session.step(SessionInput { dt, ..idle() });
            assert!(state.active && state.discard_timing && !state.paused);
        }
    }

    #[test]
    fn exact_frame_budget_is_valid() {
        let mut session = running();
        let state = session.step(SessionInput {
            dt: FixedClock::MAX_FRAME,
            ..idle()
        });
        assert!(state.active && !state.discard_timing);
    }

    #[test]
    fn focus_shortcut_pauses_once() {
        let mut session = running();
        let shortcut = SessionInput {
            focus_shortcut_pressed: true,
            ..idle()
        };
        assert!(session.step(shortcut).paused);
        assert_eq!(session.step(shortcut), SessionTransition::default());
    }

    #[test]
    fn explicit_resume_wins_simultaneous_focus_and_hitch() {
        for action in [escape(), enter(), click()] {
            let mut session = SessionController::default();
            let state = session.step(SessionInput {
                focus_shortcut_pressed: true,
                dt: 0.9,
                ..action
            });
            assert!(state.active && state.resumed && state.discard_timing);
            assert!(
                session
                    .step(SessionInput {
                        focus_shortcut_pressed: true,
                        ..idle()
                    })
                    .active
            );
        }
    }

    #[test]
    fn held_focus_modifier_does_not_cancel_later_resume() {
        let mut session = running();
        session.step(SessionInput {
            focus_shortcut_pressed: true,
            ..idle()
        });
        assert!(
            session
                .step(SessionInput {
                    focus_shortcut_pressed: true,
                    ..enter()
                })
                .resumed
        );
        for _ in 0..20 {
            assert!(
                session
                    .step(SessionInput {
                        focus_shortcut_pressed: true,
                        ..idle()
                    })
                    .active
            );
        }
        session.step(idle());
        assert!(
            session
                .step(SessionInput {
                    focus_shortcut_pressed: true,
                    ..idle()
                })
                .paused
        );
    }

    #[test]
    fn pause_while_firing_is_not_overridden_by_click() {
        let mut session = running();
        let state = session.step(SessionInput {
            click_pressed: true,
            click_down: true,
            ..escape()
        });
        assert!(state.paused && !state.active && !state.resumed);
    }

    #[test]
    fn enter_held_across_pause_requires_release() {
        let mut session = running();
        session.step(enter());
        assert!(
            session
                .step(SessionInput {
                    enter_pressed: true,
                    enter_down: true,
                    ..escape()
                })
                .paused
        );
        assert!(!session.step(enter()).active);
        session.step(idle());
        assert!(session.step(enter()).resumed);
    }

    #[test]
    fn mouse_held_across_focus_pause_requires_release() {
        let mut session = running();
        session.step(click());
        assert!(
            session
                .step(SessionInput {
                    focus_shortcut_pressed: true,
                    ..click()
                })
                .paused
        );
        assert!(!session.step(click()).active);
        session.step(idle());
        assert!(session.step(click()).resumed);
    }

    #[test]
    fn missing_or_corrupt_asset_blocks_every_resume_action() {
        for action in [escape(), enter(), click()] {
            let mut session = SessionController::default();
            let state = session.step(SessionInput {
                blocked: true,
                ..action
            });
            assert!(!state.active && !state.resumed && !state.paused);
            assert!(state.discard_timing);
        }
    }

    #[test]
    fn blocking_an_active_session_pauses_immediately() {
        let mut session = running();
        let blocked = SessionInput {
            blocked: true,
            ..idle()
        };
        assert!(session.step(blocked).paused);
        let next = session.step(blocked);
        assert!(!next.active && !next.paused && next.discard_timing);
    }

    #[test]
    fn resolving_asset_block_does_not_resume_a_held_button() {
        for action in [escape(), enter(), click()] {
            let mut session = SessionController::default();
            session.step(SessionInput {
                blocked: true,
                ..action
            });
            assert!(!session.step(action).active);
            session.step(idle());
            assert!(session.step(action).resumed);
        }
    }

    #[test]
    fn resolving_asset_block_allows_a_new_quick_tap() {
        let mut session = SessionController::default();
        session.step(SessionInput {
            blocked: true,
            enter_pressed: true,
            enter_down: false,
            ..idle()
        });
        assert!(
            session
                .step(SessionInput {
                    enter_pressed: true,
                    enter_down: false,
                    ..idle()
                })
                .resumed
        );
    }

    #[test]
    fn many_pause_resume_cycles_stay_resumable() {
        let mut session = running();
        for cycle in 0..100 {
            session.step(idle());
            assert!(session.step(escape()).paused);
            session.step(idle());
            let action = [escape(), enter(), click()][cycle % 3];
            assert!(session.step(SessionInput { dt: 0.7, ..action }).resumed);
            assert!(session.step(SessionInput { dt: 0.7, ..idle() }).active);
            assert!(session.step(idle()).active);
        }
    }

    #[test]
    fn simultaneous_resume_buttons_emit_only_one_transition() {
        let mut session = SessionController::default();
        let state = session.step(SessionInput {
            enter_pressed: true,
            enter_down: true,
            click_pressed: true,
            click_down: true,
            ..escape()
        });
        assert!(state.active && state.resumed && !state.paused);
        assert!(
            session
                .step(SessionInput {
                    esc_down: true,
                    enter_down: true,
                    click_down: true,
                    ..idle()
                })
                .active
        );
    }

    #[test]
    fn set_active_preserves_held_button_history() {
        let mut session = running();
        session.step(enter());
        session.set_active(false);
        assert!(!session.step(enter()).active);
        session.step(idle());
        assert!(session.step(enter()).resumed);
    }
}
