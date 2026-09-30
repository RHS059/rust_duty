//! Presentation-to-simulation one-shot intent bridge. Pure and unit-testable.
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
#[cfg(test)]
mod tests {
    use super::*;
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
