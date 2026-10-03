//! Fixed-tick ownership boundary for the authored locomotion path.
//!
//! This is an integration API, not a reload/ADS implementation. A higher-priority
//! owner receives the complete evaluated pose at the event time. Locomotion then
//! produces no renderable pose until that owner returns the exact authored ready
//! pose. Neither gameplay timers nor the simulation are modified here.
use crate::{
    authored_locomotion_path::{AuthoredLocomotionPath, AuthoredLocomotionPathConfig},
    sim::Simulation,
    viewmodel_animation::{AnimationError, AnimationSet, Result, ViewmodelPose},
};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PresentationAction {
    Reload,
    Ads,
    Mantle,
    Fire,
    Other,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct LocomotionInput {
    pub sprinting: bool,
    pub priority: Option<PresentationAction>,
}
impl LocomotionInput {
    /// Call after a committed simulation tick, before draining shot events.
    /// An already-active visual owner remains responsible after these signals
    /// end; it must explicitly return a matching ready pose.
    pub fn from_simulation(simulation: &Simulation) -> Self {
        let player = &simulation.player;
        let priority = if player.reload_left > 0. {
            Some(PresentationAction::Reload)
        } else if player.mantle.is_some() {
            Some(PresentationAction::Mantle)
        } else if player.ads > 0. {
            Some(PresentationAction::Ads)
        } else if player.shot_kick > 0. {
            Some(PresentationAction::Fire)
        } else {
            None
        };
        Self {
            sprinting: player.sprinting,
            priority,
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
struct ActorBinding {
    name: String,
    mesh_indices: Vec<usize>,
    inverse_rest_global: [f32; 16],
}

/// Exact ordered bindings and the matching skin/rigid companion checksums.
/// These are compatibility checks, not cryptographic file authentication.
#[derive(Clone, Debug, PartialEq)]
pub struct PoseBindings {
    companion_checksums: (u32, u32),
    bones: Vec<(String, Option<usize>)>,
    actors: Vec<ActorBinding>,
}
impl PoseBindings {
    pub fn from_animation(animation: &AnimationSet) -> Self {
        Self {
            companion_checksums: animation.companion_checksums(),
            bones: animation
                .bones()
                .iter()
                .map(|bone| (bone.name.clone(), bone.parent))
                .collect(),
            actors: animation
                .actors()
                .iter()
                .map(|actor| ActorBinding {
                    name: actor.name.clone(),
                    mesh_indices: actor.mesh_indices.clone(),
                    inverse_rest_global: actor.inverse_rest_global.to_cols_array(),
                })
                .collect(),
        }
    }

    pub fn matches(&self, animation: &AnimationSet) -> bool {
        self.companion_checksums == animation.companion_checksums()
            && self.bones.len() == animation.bones().len()
            && self.actors.len() == animation.actors().len()
            && self
                .bones
                .iter()
                .zip(animation.bones())
                .all(|((name, parent), bone)| name == &bone.name && parent == &bone.parent)
            && self.actors.iter().zip(animation.actors()).all(|(a, b)| {
                a.name == b.name
                    && a.mesh_indices == b.mesh_indices
                    && a.inverse_rest_global == b.inverse_rest_global.to_cols_array()
            })
    }

    fn require_match(&self, animation: &AnimationSet) -> Result<()> {
        if self.matches(animation) {
            Ok(())
        } else {
            Err(AnimationError(
                "authored presentation binding mismatch".into(),
            ))
        }
    }
}

#[derive(Clone, Debug)]
pub struct PoseHandoff {
    id: u64,
    simulation_time: f64,
    action: PresentationAction,
    pose: ViewmodelPose,
    bindings: PoseBindings,
}
impl PoseHandoff {
    pub fn id(&self) -> u64 {
        self.id
    }
    pub fn simulation_time(&self) -> f64 {
        self.simulation_time
    }
    pub fn action(&self) -> PresentationAction {
        self.action
    }
    pub fn pose(&self) -> &ViewmodelPose {
        &self.pose
    }
    pub fn bindings(&self) -> &PoseBindings {
        &self.bindings
    }
    /// The receiving owner must render this complete pose at weight zero. Same
    /// dimensions alone are insufficient: companion and ordered bindings match.
    pub fn validate_receiver(&self, animation: &AnimationSet) -> Result<()> {
        self.bindings.require_match(animation)?;
        animation.blend_poses(&self.pose, &self.pose, 0.)?;
        Ok(())
    }
}

#[derive(Clone, Debug)]
pub struct AuthoredLocomotionAdapter {
    path: AuthoredLocomotionPath,
    bindings: PoseBindings,
    ready: ViewmodelPose,
    last_time: f64,
    input: LocomotionInput,
    epoch: u64,
    handoff: Option<PoseHandoff>,
}
impl AuthoredLocomotionAdapter {
    pub fn new(
        animation: &AnimationSet,
        config: AuthoredLocomotionPathConfig,
        time: f64,
    ) -> Result<Self> {
        let path = AuthoredLocomotionPath::new(animation, config, time)?;
        Ok(Self {
            ready: path.pose().clone(),
            path,
            bindings: PoseBindings::from_animation(animation),
            last_time: time,
            input: LocomotionInput::default(),
            epoch: 0,
            handoff: None,
        })
    }

    /// `step_start` is captured immediately before Simulation::update; the
    /// simulation passed here is its committed result. Actions are accepted at
    /// step_start in this game, before update increments simulation.time. This
    /// avoids a one-tick-late handoff and includes the first sprint interval.
    /// The receiving owner gets the event time and can evaluate its own pose at
    /// simulation.time without delaying the already-committed gameplay action.
    pub fn committed_step(
        &mut self,
        animation: &AnimationSet,
        step_start: f64,
        simulation: &Simulation,
    ) -> Result<Option<PoseHandoff>> {
        if step_start != self.last_time || simulation.time < step_start {
            return Err(AnimationError(
                "step must begin at the last committed tick".into(),
            ));
        }
        let mut next = self.clone();
        let input = LocomotionInput::from_simulation(simulation);
        let event = next.committed_tick(animation, step_start, input)?;
        next.committed_tick(animation, simulation.time, input)?;
        *self = next;
        Ok(event)
    }

    /// Advance the previous locomotion intent to this event time before
    /// accepting new intent. A priority event never waits for an exit or settle.
    /// Only the first event hands off; repeated ticks cannot restart that owner.
    /// Pauses use the same simulation timestamp. Clock rewinds require reset().
    /// Every error leaves this adapter unchanged.
    pub fn committed_tick(
        &mut self,
        animation: &AnimationSet,
        time: f64,
        input: LocomotionInput,
    ) -> Result<Option<PoseHandoff>> {
        self.bindings.require_match(animation)?;
        self.require_time(time)?;
        if self.handoff.is_some() {
            self.last_time = time;
            self.input = input;
            return Ok(None);
        }
        let mut next = self.clone();
        let result = if let Some(action) = input.priority {
            // Preserve the previously committed intent, including its phase and
            // rate, through the exact event timestamp. Do not request an exit.
            next.path
                .update(animation, time, self.input.sprinting, true)?;
            next.epoch = next_epoch(next.epoch)?;
            let handoff = PoseHandoff {
                id: next.epoch,
                simulation_time: time,
                action,
                pose: next.path.pose().clone(),
                bindings: next.bindings.clone(),
            };
            next.handoff = Some(handoff.clone());
            Some(handoff)
        } else {
            next.path.update(animation, time, input.sprinting, true)?;
            None
        };
        next.last_time = time;
        next.input = input;
        *self = next;
        Ok(result)
    }

    /// Exactly one render owner: None means the receiving owner must render.
    /// Reading the pose never advances animation or changes input history.
    pub fn pose(&self) -> Option<&ViewmodelPose> {
        self.handoff.is_none().then(|| self.path.pose())
    }
    pub fn pending_handoff(&self) -> Option<&PoseHandoff> {
        self.handoff.as_ref()
    }
    pub fn simulation_time(&self) -> f64 {
        self.last_time
    }
    pub fn bindings(&self) -> &PoseBindings {
        &self.bindings
    }
    pub fn ready_pose(&self) -> &ViewmodelPose {
        &self.ready
    }

    /// Reacquire only at the last committed tick, after the other owner has
    /// displayed this same complete ready pose. A measured authored return path
    /// belongs to that owner. This API never crossfades incompatible poses.
    /// Transform equality is exact (quaternion sign may differ); sample_time is
    /// metadata and does not affect the rendered pose.
    pub fn return_ready(
        &mut self,
        animation: &AnimationSet,
        handoff_id: u64,
        time: f64,
        displayed_pose: &ViewmodelPose,
    ) -> Result<()> {
        self.bindings.require_match(animation)?;
        self.require_time(time)?;
        if time != self.last_time {
            return Err(AnimationError(
                "return needs the last committed tick".into(),
            ));
        }
        if self.handoff.as_ref().map(PoseHandoff::id) != Some(handoff_id) {
            return Err(AnimationError(
                "stale or absent presentation handoff".into(),
            ));
        }
        if self.input.priority.is_some() {
            return Err(AnimationError(
                "gameplay presentation still has priority".into(),
            ));
        }
        animation.blend_poses(displayed_pose, displayed_pose, 0.)?;
        if !same_displayed_pose(displayed_pose, &self.ready) {
            return Err(AnimationError(
                "return pose is not the authored ready pose".into(),
            ));
        }
        let mut next = self.clone();
        next.path.reset(animation, time)?;
        next.path
            .update(animation, time, next.input.sprinting, true)?;
        next.handoff = None;
        *self = next;
        Ok(())
    }

    /// Explicit simulation/world reset, not an automatic action cancellation.
    /// Invalidates all prior handoff IDs so delayed owners cannot reacquire.
    pub fn reset(&mut self, animation: &AnimationSet, time: f64) -> Result<()> {
        self.bindings.require_match(animation)?;
        let mut next = self.clone();
        next.path.reset(animation, time)?;
        next.epoch = next_epoch(next.epoch)?;
        next.last_time = time;
        next.input = LocomotionInput::default();
        next.handoff = None;
        *self = next;
        Ok(())
    }

    fn require_time(&self, time: f64) -> Result<()> {
        if time.is_finite() && time >= self.last_time && time >= 0. {
            Ok(())
        } else {
            Err(AnimationError(
                "adapter time must be finite, nonnegative and monotonic; reset explicitly".into(),
            ))
        }
    }
}
fn next_epoch(epoch: u64) -> Result<u64> {
    epoch
        .checked_add(1)
        .ok_or_else(|| AnimationError("presentation handoff ID exhausted".into()))
}
fn same_displayed_pose(a: &ViewmodelPose, b: &ViewmodelPose) -> bool {
    a.bone_locals.len() == b.bone_locals.len()
        && a.actor_globals.len() == b.actor_globals.len()
        && a.actor_visible == b.actor_visible
        && a.bone_locals
            .iter()
            .chain(&a.actor_globals)
            .zip(b.bone_locals.iter().chain(&b.actor_globals))
            .all(|(a, b)| {
                a.translation == b.translation
                    && a.scale == b.scale
                    && (a.rotation == b.rotation || a.rotation == -b.rotation)
            })
}
