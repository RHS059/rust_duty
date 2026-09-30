use crate::settings::Settings;
use macroquad::math::{vec2, vec3, Vec2, Vec3};
pub const FIXED_DT: f32 = 1. / 120.;
pub const MAGAZINE: u32 = 30;
pub const RADIUS: f32 = 0.381;
pub const SPRINT_DURATION: f32 = 4.;

#[derive(Debug, Clone, Copy)]
pub struct Aabb {
    pub min: Vec3,
    pub max: Vec3,
}
impl Aabb {
    pub fn from_center(center: Vec3, size: Vec3) -> Self {
        Self {
            min: center - size * 0.5,
            max: center + size * 0.5,
        }
    }
    pub fn center(self) -> Vec3 {
        (self.min + self.max) * 0.5
    }
    pub fn size(self) -> Vec3 {
        self.max - self.min
    }
    pub fn overlaps(self, b: Self) -> bool {
        self.min.x < b.max.x
            && self.max.x > b.min.x
            && self.min.y < b.max.y
            && self.max.y > b.min.y
            && self.min.z < b.max.z
            && self.max.z > b.min.z
    }
    /// Slab ray test; returns first positive intersection, including rays starting inside.
    pub fn ray(self, origin: Vec3, direction: Vec3, limit: f32) -> Option<f32> {
        let mut near: f32 = 0.;
        let mut far = limit;
        for axis in 0..3 {
            if direction[axis].abs() < 1e-7 {
                if origin[axis] < self.min[axis] || origin[axis] > self.max[axis] {
                    return None;
                }
            } else {
                let a = (self.min[axis] - origin[axis]) / direction[axis];
                let b = (self.max[axis] - origin[axis]) / direction[axis];
                near = near.max(a.min(b));
                far = far.min(a.max(b));
                if near > far {
                    return None;
                }
            }
        }
        if far < 0. {
            None
        } else {
            Some(near)
        }
    }
}
#[derive(Clone)]
pub struct Block {
    pub bounds: Aabb,
    pub kind: u8,
}
#[derive(Clone, Copy)]
pub struct Ramp {
    pub x: f32,
    pub z: f32,
    pub width: f32,
    pub length: f32,
    pub height: f32,
}
impl Ramp {
    pub fn slope(self) -> f32 {
        self.height / self.length
    }
    pub fn surface(self, x: f32, z: f32) -> Option<f32> {
        if x >= self.x - self.width * 0.5
            && x <= self.x + self.width * 0.5
            && z <= self.z
            && z >= self.z - self.length
        {
            Some((self.z - z) * self.slope())
        } else {
            None
        }
    }
    pub fn ray(self, origin: Vec3, dir: Vec3, limit: f32) -> Option<f32> {
        let planes = [
            (Vec3::X, self.x + self.width * 0.5),
            (-Vec3::X, -self.x + self.width * 0.5),
            (Vec3::Z, self.z),
            (-Vec3::Z, -self.z + self.length),
            (-Vec3::Y, 0.),
            (vec3(0., 1., self.slope()), self.slope() * self.z),
        ];
        let mut enter: f32 = 0.;
        let mut exit = limit;
        for (n, b) in planes {
            let available = b - n.dot(origin);
            let rate = n.dot(dir);
            if rate.abs() < 1e-7 {
                if available < 0. {
                    return None;
                }
            } else if rate > 0. {
                exit = exit.min(available / rate);
            } else {
                enter = enter.max(available / rate);
            }
            if enter > exit {
                return None;
            }
        }
        if exit < 0. {
            None
        } else {
            Some(enter)
        }
    }
}
#[derive(Clone)]
pub struct Target {
    pub bounds: Aabb,
    pub health: f32,
    pub respawn: f32,
    pub flash: f32,
}
#[derive(Default, Clone, Copy)]
pub struct Input {
    pub movement: Vec2,
    pub jump: bool,
    pub crouch: bool,
    pub prone: bool,
    pub sprint: bool,
    pub ads: bool,
    pub fire: bool,
    pub reload: bool,
}
#[derive(Clone, Copy)]
pub struct Shot {
    pub time: f64,
    pub direction: Vec3,
    pub spread_degrees: f32,
    pub start: Vec3,
    pub end: Vec3,
    pub hit_target: bool,
    pub headshot: bool,
}
#[derive(Default)]
pub struct Stats {
    pub shots: u32,
    pub hits: u32,
    pub kills: u32,
    pub headshots: u32,
    pub distance: f32,
}
pub struct Player {
    pub position: Vec3,
    pub velocity: Vec3,
    pub yaw: f32,
    pub pitch: f32,
    pub grounded: bool,
    pub crouched: bool,
    pub prone: bool,
    pub stance_override: bool,
    pub stance_progress: f32,
    pub eye_from: f32,
    pub stance_duration: f32,
    pub eye_height: f32,
    pub sprinting: bool,
    pub stamina: f32,
    pub sprint_recovery: f32,
    pub ads: f32,
    pub recoil: Vec2,
    pub recoil_velocity: Vec2,
    pub ammo: u32,
    pub reserve: u32,
    pub reload_left: f32,
    pub cooldown: f32,
    pub sprint_out: f32,
    pub bloom: f32,
    pub shot_kick: f32,
    pub landing_kick: f32,
    pub previous_grounded: bool,
    pub jump_held: bool,
    pub sprint_exhausted: bool,
    pub reload_credited: bool,
    pub reload_held: bool,
    pub reload_empty: bool,
    pub reload_total: f32,
    pub reload_credit_at: f64,
    pub reload_ready_at: f64,
    pub next_shot_at: f64,
    pub firing_sequence: bool,
    pub last_shot_at: f64,
    pub last_jump_at: f64,
    pub air_speed_limit: f32,
}
impl Default for Player {
    fn default() -> Self {
        Self {
            position: vec3(0., 0., 9.),
            velocity: Vec3::ZERO,
            yaw: -std::f32::consts::FRAC_PI_2,
            pitch: 0.,
            grounded: true,
            crouched: false,
            prone: false,
            stance_override: false,
            stance_progress: 1.,
            eye_from: 1.524,
            stance_duration: 0.2,
            eye_height: 1.524,
            sprinting: false,
            stamina: SPRINT_DURATION,
            sprint_recovery: 0.,
            ads: 0.,
            recoil: Vec2::ZERO,
            recoil_velocity: Vec2::ZERO,
            ammo: MAGAZINE,
            reserve: 90,
            reload_left: 0.,
            cooldown: 0.,
            sprint_out: 0.,
            bloom: 0.,
            shot_kick: 0.,
            landing_kick: 0.,
            previous_grounded: true,
            jump_held: false,
            sprint_exhausted: false,
            reload_credited: false,
            reload_held: false,
            reload_empty: false,
            reload_total: 0.,
            reload_credit_at: 0.,
            reload_ready_at: 0.,
            next_shot_at: 0.,
            firing_sequence: false,
            last_shot_at: -10.,
            last_jump_at: -10.,
            air_speed_limit: 5.0673,
        }
    }
}
impl Player {
    pub fn eye(&self) -> Vec3 {
        self.position + vec3(0., self.eye_height - self.landing_kick, 0.)
    }
    pub fn direction(&self) -> Vec3 {
        direction(self.yaw + self.recoil.y, self.pitch + self.recoil.x)
    }
    pub fn height(&self) -> f32 {
        if self.prone {
            0.762
        } else if self.crouched {
            1.27
        } else {
            1.778
        }
    }
    pub fn bounds_at(&self, pos: Vec3) -> Aabb {
        Aabb {
            min: pos - vec3(RADIUS, 0., RADIUS),
            max: pos + vec3(RADIUS, self.height(), RADIUS),
        }
    }
    pub fn speed(&self) -> f32 {
        vec2(self.velocity.x, self.velocity.z).length()
    }
}
pub fn direction(yaw: f32, pitch: f32) -> Vec3 {
    vec3(
        yaw.cos() * pitch.cos(),
        pitch.sin(),
        yaw.sin() * pitch.cos(),
    )
}
fn approach(current: f32, target: f32, step: f32) -> f32 {
    current + (target - current).clamp(-step, step)
}

pub struct Simulation {
    pub player: Player,
    pub blocks: Vec<Block>,
    pub targets: Vec<Target>,
    pub ramps: Vec<Ramp>,
    pub stats: Stats,
    pub events: Vec<Shot>,
    pub time: f64,
    spread_seed: u32,
    recoil_seed: u32,
}
impl Default for Simulation {
    fn default() -> Self {
        Self::new()
    }
}
impl Simulation {
    pub fn new() -> Self {
        let mut blocks = Vec::new();
        let mut block = |c, s, kind| {
            blocks.push(Block {
                bounds: Aabb::from_center(c, s),
                kind,
            })
        };
        block(vec3(0., -0.25, -20.), vec3(64., 0.5, 68.), 0);
        block(vec3(-32., 2., -20.), vec3(0.5, 4., 68.), 1);
        block(vec3(32., 2., -20.), vec3(0.5, 4., 68.), 1);
        block(vec3(0., 2., -54.), vec3(64., 4., 0.5), 1);
        block(vec3(0., 2., 14.), vec3(64., 4., 0.5), 1);
        block(vec3(-6., 0.6, -4.), vec3(2., 1.2, 5.), 2);
        block(vec3(6., 0.6, -4.), vec3(2., 1.2, 5.), 2);
        block(vec3(-10., 0.3, 3.), vec3(2., 0.6, 2.), 3);
        block(vec3(-10., 0.6, 0.), vec3(2., 1.2, 2.), 3);
        block(vec3(-10., 0.9, -3.), vec3(2., 1.8, 2.), 3);
        // A walkable staircase tests grounded step-up independently of jump arcs.
        for i in 0..5 {
            let h = (i + 1) as f32 * 0.24;
            block(vec3(10., h * 0.5, 4. - i as f32), vec3(2.5, h, 1.), 3);
        }
        block(vec3(10., 1.65, -4.), vec3(3., 0.6, 4.), 2); // crouch clearance bay
        block(vec3(8.25, 0.65, -4.), vec3(0.5, 1.3, 4.), 2);
        block(vec3(11.75, 0.65, -4.), vec3(0.5, 1.3, 4.), 2);
        block(vec3(4., 0.45, -16.), vec3(4., 0.9, 1.), 2);
        block(vec3(22., 1.013, -4.), vec3(3., 0.4, 5.), 2);
        block(vec3(20.25, 0.45, -4.), vec3(0.5, 0.9, 5.), 2);
        block(vec3(23.75, 0.45, -4.), vec3(0.5, 0.9, 5.), 2);
        // Reference-unit step threshold fixtures, isolated from the timing lane.
        for (i, units) in [10., 17., 18., 19., 25.].iter().enumerate() {
            let height = units * 0.0254;
            block(
                vec3(-22. + i as f32 * 2.5, height * 0.5, -10.),
                vec3(1.6, height, 2.),
                3,
            );
        }
        let mut targets: Vec<Target> = [-12., -7., 0., 7., 12.]
            .iter()
            .enumerate()
            .map(|(i, x)| Target {
                bounds: Aabb::from_center(
                    vec3(*x, 1.3, -24. - (i % 2) as f32 * 5.),
                    vec3(0.8, 1.9, 0.25),
                ),
                health: 100.,
                respawn: 0.,
                flash: 0.,
            })
            .collect();
        for (x, z) in [(26., -1.), (26., -16.), (26., -41.)] {
            targets.push(Target {
                bounds: Aabb::from_center(vec3(x, 1.3, z), vec3(0.8, 1.9, 0.25)),
                health: 100.,
                respawn: 0.,
                flash: 0.,
            });
        }
        blocks.push(Block {
            bounds: Aabb::from_center(vec3(17., 2., -40.), vec3(8., 4., 0.3)),
            kind: 1,
        });
        Self {
            player: Player::default(),
            blocks,
            targets,
            ramps: vec![
                Ramp {
                    x: -22.,
                    z: -18.,
                    width: 3.,
                    length: 5.,
                    height: 5. * 30_f32.to_radians().tan(),
                },
                Ramp {
                    x: -15.,
                    z: -18.,
                    width: 3.,
                    length: 4.,
                    height: 4.,
                },
                Ramp {
                    x: -8.,
                    z: -18.,
                    width: 3.,
                    length: 4.,
                    height: 4. * 50_f32.to_radians().tan(),
                },
            ],
            stats: Stats::default(),
            events: Vec::new(),
            time: 0.,
            spread_seed: 0x91e10da5,
            recoil_seed: 0xa735813c,
        }
    }
    fn random(seed: &mut u32) -> f32 {
        *seed ^= *seed << 13;
        *seed ^= *seed >> 17;
        *seed ^= *seed << 5;
        (*seed as f64 / u32::MAX as f64) as f32
    }
    pub fn reset(&mut self) {
        *self = Self::new();
    }
    fn begin_reload(&mut self, cfg: &Settings) {
        let p = &mut self.player;
        p.reload_empty = p.ammo == 0;
        p.reload_total = if p.reload_empty {
            cfg.empty_reload_time
        } else {
            cfg.reload_time
        };
        p.reload_left = p.reload_total;
        p.reload_credit_at = self.time
            + if p.reload_empty {
                cfg.empty_reload_credit
            } else {
                cfg.reload_credit
            } as f64;
        p.reload_ready_at = self.time + p.reload_total as f64;
        p.reload_credited = false;
        p.sprint_out = 0.;
        p.firing_sequence = false;
    }
    pub fn spread_degrees(&self, cfg: &Settings) -> f32 {
        let p = &self.player;
        let movement = (p.speed() / cfg.walk_speed).clamp(0., 1.);
        let hip = cfg.hip_spread
            * (if p.prone {
                0.80 / 1.60
            } else if p.crouched {
                1.15 / 1.60
            } else {
                1.
            })
            + movement
            + if p.grounded { 0. } else { 1.8 }
            + p.bloom;
        let aimed = cfg.ads_spread + movement * 0.06 + if p.grounded { 0. } else { 0.35 };
        hip + (aimed - hip) * p.ads
    }
    pub fn update(&mut self, input: Input, cfg: &Settings, dt: f32) {
        // Process non-shot milestones before new action requests at this timestamp.
        for t in &mut self.targets {
            t.flash = (t.flash - dt).max(0.);
            if t.respawn > 0. {
                t.respawn = (t.respawn - dt).max(0.);
                if t.respawn == 0. {
                    t.health = 100.;
                }
            }
        }
        let p = &mut self.player;
        if p.reload_left > 0. {
            if !p.reload_credited && self.time + 1e-7 >= p.reload_credit_at {
                let n = (MAGAZINE - p.ammo).min(p.reserve);
                p.ammo += n;
                p.reserve -= n;
                p.reload_credited = true;
            }
            p.reload_left = (p.reload_ready_at - self.time).max(0.) as f32;
            if p.reload_left < 1e-6 {
                p.reload_left = 0.;
            }
        }
        let can_sprint = !p.crouched
            && !p.prone
            && input.sprint
            && input.movement.y > 0.83
            && p.grounded
            && !input.crouch
            && !input.prone
            && !input.ads
            && !input.fire
            && !p.sprint_exhausted
            && p.stamina >= 1.;
        if p.reload_left > 0. && !p.reload_empty && can_sprint {
            p.reload_left = 0.;
            p.reload_credit_at = 0.;
            p.reload_ready_at = 0.;
        }
        let valid_reload = input.reload
            && !p.reload_held
            && p.reload_left == 0.
            && p.ammo < MAGAZINE
            && p.reserve > 0;
        p.reload_held = input.reload;
        if valid_reload {
            self.begin_reload(cfg);
        }
        self.move_player(input, cfg, dt);
        let p = &mut self.player;
        if valid_reload {
            p.sprint_out = 0.;
        }
        p.cooldown = (p.next_shot_at - self.time).max(0.) as f32;
        p.shot_kick = (p.shot_kick - dt / 0.12).max(0.);
        if self.time - p.last_shot_at >= 0.1 {
            p.bloom = (p.bloom - dt * 4.).max(0.);
        }
        p.landing_kick = (p.landing_kick - dt * 0.8).max(0.);
        if self.time - p.last_shot_at >= 0.12 {
            p.recoil *= (-cfg.recoil_return * dt).exp();
            if p.recoil.length() < 0.00005 {
                p.recoil = Vec2::ZERO;
            }
        }
        let ads_target = if input.ads && !p.sprinting && p.reload_left == 0. {
            1.
        } else {
            0.
        };
        p.ads = approach(
            p.ads,
            ads_target,
            dt / if ads_target > p.ads {
                cfg.ads_time
            } else {
                cfg.ads_out_time
            },
        );
        let fire_eligible =
            input.fire && !p.sprinting && p.sprint_out <= 1e-6 && p.reload_left <= 0.;
        if !fire_eligible {
            p.firing_sequence = false;
        }
        if fire_eligible && self.time + 1e-7 >= p.next_shot_at {
            if p.ammo > 0 {
                self.fire(cfg);
            } else if p.reserve > 0 {
                self.begin_reload(cfg);
            }
        }
        self.player.sprint_out = (self.player.sprint_out - dt).max(0.);
        self.time += dt as f64;
    }
    fn move_player(&mut self, input: Input, cfg: &Settings, dt: f32) {
        let p = &mut self.player;
        if input.jump && !p.jump_held && p.crouched {
            p.stance_override = true;
        }
        if !input.crouch && !input.prone {
            p.stance_override = false;
        }
        let current = if p.prone {
            2_i32
        } else if p.crouched {
            1
        } else {
            0
        };
        let desired = if p.stance_override {
            0
        } else if input.prone {
            2
        } else if input.crouch {
            1
        } else {
            0
        };
        if current != desired && p.stance_progress >= 1. {
            let proposed = current + (desired - current).signum();
            let height = match proposed {
                2 => 0.762,
                1 => 1.27,
                _ => 1.778,
            };
            let bounds = Aabb {
                min: p.position - vec3(RADIUS, 0., RADIUS) + Vec3::Y * 0.002,
                max: p.position + vec3(RADIUS, height, RADIUS),
            };
            if proposed > current || !self.blocks.iter().any(|b| bounds.overlaps(b.bounds)) {
                p.crouched = proposed > 0;
                p.prone = proposed == 2;
                p.eye_from = p.eye_height;
                p.stance_progress = 0.;
                p.stance_duration = if current == 2 || proposed == 2 {
                    0.4
                } else {
                    0.2
                };
            }
        }
        p.stance_progress = (p.stance_progress + dt / p.stance_duration).min(1.);
        let blend = p.stance_progress * p.stance_progress * (3. - 2. * p.stance_progress);
        let target_eye = if p.prone {
            0.2794
        } else if p.crouched {
            1.016
        } else {
            1.524
        };
        p.eye_height = p.eye_from + (target_eye - p.eye_from) * blend;
        // Prevent a shrinking camera from crossing a low ceiling during its eased transition.
        for b in &self.blocks {
            if p.position.x + RADIUS > b.bounds.min.x
                && p.position.x - RADIUS < b.bounds.max.x
                && p.position.z + RADIUS > b.bounds.min.z
                && p.position.z - RADIUS < b.bounds.max.z
                && b.bounds.min.y > p.position.y
            {
                p.eye_height = p
                    .eye_height
                    .min((b.bounds.min.y - p.position.y - 0.08).max(0.1));
            }
        }
        let was_sprinting = p.sprinting;
        if !input.sprint {
            p.sprint_exhausted = false;
        }
        if p.stamina <= 0.00001 {
            p.sprint_exhausted = true;
        }
        p.sprinting = input.sprint
            && input.movement.y > 0.83
            && p.grounded
            && !input.jump
            && !p.crouched
            && !input.ads
            && !input.fire
            && p.reload_left <= 0.
            && p.stamina > 0.00001
            && (was_sprinting || p.stamina >= 1.)
            && !p.sprint_exhausted;
        if p.sprinting {
            p.stamina = (p.stamina - dt).max(0.);
            p.sprint_recovery = 0.;
        } else {
            p.sprint_recovery = (p.sprint_recovery - dt).max(0.);
            if p.sprint_recovery == 0. {
                p.stamina = (p.stamina + dt).min(SPRINT_DURATION);
            }
        }
        if was_sprinting && !p.sprinting {
            p.sprint_out = cfg.sprint_out_time;
        }
        let forward = vec3(p.yaw.cos(), 0., p.yaw.sin());
        let right = forward.cross(Vec3::Y);
        let wish = (right * input.movement.x + forward * input.movement.y).normalize_or_zero();
        let base_speed = if p.prone {
            cfg.walk_speed * 0.15
        } else if p.crouched {
            cfg.crouch_speed
        } else if p.sprinting {
            cfg.sprint_speed
        } else {
            cfg.walk_speed
        };
        // A normalized direction keeps diagonals bounded while blending forward/side/back intent.

        let directional_scale = if input.movement.y > 0. {
            1.
        } else if input.movement.x.abs() > 0. {
            0.8
        } else if input.movement.y < 0. {
            0.7
        } else {
            0.
        };
        let speed = base_speed * directional_scale * (1. - p.ads * 0.5);
        let launch = current == 0
            && input.jump
            && !p.jump_held
            && p.grounded
            && !p.crouched
            && self.time - p.last_jump_at >= 0.5;
        if launch {
            p.velocity.y = cfg.jump_speed;
            p.grounded = false;
            p.last_jump_at = self.time;
            p.air_speed_limit = p.speed().max(cfg.walk_speed) * 1.05;
        }
        if p.grounded {
            let horizontal = vec2(p.velocity.x, p.velocity.z);
            let current_speed = horizontal.length();
            let stop_control = 2.54_f32.min(base_speed); // 100 reference units/s at 0.0254 m/unit.
            let after_friction =
                (current_speed - current_speed.max(stop_control) * cfg.friction * dt).max(0.);
            let damped = if current_speed > 0. {
                horizontal * (after_friction / current_speed)
            } else {
                Vec2::ZERO
            };
            let target = vec2(wish.x, wish.z) * speed;
            let acceleration = if p.prone {
                cfg.acceleration * (19. / 9.)
            } else if p.crouched {
                cfg.acceleration * (12. / 9.)
            } else {
                cfg.acceleration
            };
            let result = if wish.length_squared() > 0. {
                damped + (target - damped).clamp_length_max(acceleration * base_speed * dt)
            } else {
                damped
            };
            p.velocity.x = result.x;
            p.velocity.z = result.y;
        } else {
            let along = p.velocity.dot(wish);
            let add = (speed - along)
                .max(0.)
                .min(cfg.air_acceleration * base_speed * dt);
            p.velocity += wish * add;
            let horizontal = vec2(p.velocity.x, p.velocity.z).clamp_length_max(p.air_speed_limit);
            p.velocity.x = horizontal.x;
            p.velocity.z = horizontal.y;
        }
        p.jump_held = input.jump;
        p.velocity.y -= cfg.gravity * dt;
        let old = p.position;
        for axis in [0, 2] {
            let delta = p.velocity[axis] * dt;
            p.position[axis] += delta;
            for b in &self.blocks {
                if p.bounds_at(p.position).overlaps(b.bounds) {
                    let step = b.bounds.max.y - p.position.y;
                    let candidate = vec3(p.position.x, b.bounds.max.y + 0.001, p.position.z);
                    if p.grounded
                        && step > 0.
                        && step <= if p.prone { 0.254 } else { 0.4572 }
                        && !self
                            .blocks
                            .iter()
                            .any(|o| p.bounds_at(candidate).overlaps(o.bounds))
                    {
                        p.position = candidate;
                    } else {
                        if delta > 0. {
                            p.position[axis] = b.bounds.min[axis] - RADIUS;
                        } else if delta < 0. {
                            p.position[axis] = b.bounds.max[axis] + RADIUS;
                        }
                        p.velocity[axis] = 0.;
                    }
                }
            }
        }
        // Analytic wedge support. Steep wedges block entry; walkable faces support feet.
        for ramp in &self.ramps {
            if let Some(surface) = ramp.surface(p.position.x, p.position.z) {
                if p.position.y < surface - 0.001 {
                    let old_surface = ramp.surface(old.x, old.z).unwrap_or(0.);
                    if ramp.slope() <= 1.0001 && p.grounded && surface - old_surface < 0.4572 {
                        let raised = vec3(p.position.x, surface, p.position.z);
                        if !self
                            .blocks
                            .iter()
                            .any(|b| p.bounds_at(raised + Vec3::Y * 0.002).overlaps(b.bounds))
                        {
                            p.position = raised;
                        }
                    } else if old.y < surface {
                        p.position.x = old.x;
                        p.position.z = old.z;
                        p.velocity.x = 0.;
                        p.velocity.z = 0.;
                    }
                } else if p.grounded && p.position.y - surface < 0.4572 {
                    p.position.y = surface;
                }
            }
        }
        p.previous_grounded = p.grounded;
        p.grounded = false;
        let dy = p.velocity.y * dt + 0.5 * cfg.gravity * dt * dt;
        p.position.y += dy;
        for b in &self.blocks {
            if p.bounds_at(p.position).overlaps(b.bounds) {
                if dy <= 0. {
                    p.position.y = b.bounds.max.y;
                    p.grounded = true;
                    if !p.previous_grounded {
                        p.velocity.x *= 0.65;
                        p.velocity.z *= 0.65;
                        p.landing_kick = (-p.velocity.y * 0.012).min(0.15);
                    }
                } else {
                    p.position.y = b.bounds.min.y - p.height();
                }
                p.velocity.y = 0.;
            }
        }
        for ramp in &self.ramps {
            if let Some(surface) = ramp.surface(p.position.x, p.position.z) {
                if ramp.slope() <= 1.0001 && p.position.y <= surface && p.velocity.y <= 0. {
                    p.position.y = surface;
                    p.grounded = true;
                    if !p.previous_grounded {
                        p.velocity.x *= 0.65;
                        p.velocity.z *= 0.65;
                        p.landing_kick = (-p.velocity.y * 0.012).min(0.15);
                    }
                    p.velocity.y = 0.;
                }
            }
        }
        self.stats.distance += vec2(p.position.x - old.x, p.position.z - old.z).length();
        if p.position.y < -10. {
            *p = Player::default();
        }
    }
    fn fire(&mut self, cfg: &Settings) {
        let jitter = vec2(
            Self::random(&mut self.recoil_seed) * 2. - 1.,
            Self::random(&mut self.recoil_seed) * 2. - 1.,
        );
        let u = Self::random(&mut self.spread_seed);
        let angle = Self::random(&mut self.spread_seed) * std::f32::consts::TAU;
        let spread_degrees = self.spread_degrees(cfg);
        let spread = spread_degrees.to_radians();
        let p = &self.player;
        let forward = p.direction();
        let right = forward.cross(Vec3::Y).normalize();
        let up = right.cross(forward);
        // Uniform solid angle: cos(theta) is uniformly distributed over the cone.
        let cos_theta = 1. - u * (1. - spread.cos());
        let sin_theta = (1. - cos_theta * cos_theta).max(0.).sqrt();
        let ray = (forward * cos_theta + (right * angle.cos() + up * angle.sin()) * sin_theta)
            .normalize();
        let start = p.eye();
        let mut distance = 150.;
        let mut hit = None;
        for b in &self.blocks {
            if let Some(d) = b.bounds.ray(start, ray, distance) {
                distance = d;
            }
        }
        for ramp in &self.ramps {
            if let Some(d) = ramp.ray(start, ray, distance) {
                distance = d;
            }
        }
        for (i, t) in self.targets.iter().enumerate() {
            if t.health > 0. {
                if let Some(d) = t.bounds.ray(start, ray, distance) {
                    distance = d;
                    hit = Some(i);
                }
            }
        }
        let mut end = start + ray * distance;
        // The logical muzzle must have a clear path out of nearby cover as well as an eye ray.
        let muzzle =
            start + forward * 0.85 + right * 0.14 * (1. - p.ads) - up * 0.15 * (1. - p.ads);
        let to_muzzle = muzzle - start;
        let muzzle_length = to_muzzle.length();
        let mut blocked = None;
        for b in &self.blocks {
            if let Some(d) = b
                .bounds
                .ray(start, to_muzzle / muzzle_length, muzzle_length)
            {
                blocked = Some(start + to_muzzle / muzzle_length * d);
                break;
            }
        }
        if blocked.is_none() {
            let path = end - muzzle;
            let length = path.length();
            if length > 0.001 {
                let direction = path / length;
                let mut nearest = length;
                for b in &self.blocks {
                    if let Some(d) = b.bounds.ray(muzzle, direction, nearest - 0.002) {
                        nearest = d;
                        blocked = Some(muzzle + direction * d);
                    }
                }
                for r in &self.ramps {
                    if let Some(d) = r.ray(muzzle, direction, nearest - 0.002) {
                        nearest = d;
                        blocked = Some(muzzle + direction * d);
                    }
                }
            }
        }
        if let Some(point) = blocked {
            end = point;
            hit = None;
        }
        let mut headshot = false;
        if let Some(i) = hit {
            let t = &mut self.targets[i];
            headshot = end.y > t.bounds.max.y - 0.38;
            t.health -= if headshot { 68. } else { 34. };
            t.flash = 0.12;
            self.stats.hits += 1;
            if headshot {
                self.stats.headshots += 1;
            }
            if t.health <= 0. {
                self.stats.kills += 1;
                t.respawn = 1.5;
            }
        }
        self.stats.shots += 1;
        self.events.push(Shot {
            time: self.time,
            direction: ray,
            spread_degrees,
            start,
            end,
            hit_target: hit.is_some(),
            headshot,
        });
        let p = &mut self.player;
        p.ammo -= 1;
        let interval = 60. / cfg.fire_rpm as f64;
        p.next_shot_at = if p.firing_sequence {
            p.next_shot_at + interval
        } else {
            self.time + interval
        };
        p.firing_sequence = true;
        p.last_shot_at = self.time;
        p.cooldown = (p.next_shot_at - self.time) as f32;
        let hip = cfg.recoil_pitch + jitter.x * 0.125;
        let aimed = cfg.recoil_pitch * (0.52 / 0.775) + jitter.x * 0.10;
        p.recoil.x =
            (p.recoil.x + (hip + (aimed - hip) * p.ads).to_radians()).min(6_f32.to_radians());
        p.recoil.y = (p.recoil.y + (jitter.y * (0.30 - 0.12 * p.ads)).to_radians())
            .clamp(-2_f32.to_radians(), 2_f32.to_radians());
        p.bloom = (p.bloom + 0.35 * (1. - p.ads)).min(2.4);
        p.shot_kick = 1.;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn run(s: &mut Simulation, i: Input, n: usize) {
        for _ in 0..n {
            s.update(i, &Settings::default(), FIXED_DT);
        }
    }
    #[test]
    fn ray_parallel_and_inside() {
        let b = Aabb::from_center(Vec3::ZERO, Vec3::splat(2.));
        assert_eq!(b.ray(vec3(3., 0., 0.), Vec3::Z, 100.), None);
        assert_eq!(b.ray(Vec3::ZERO, Vec3::X, 100.), Some(0.));
        assert_eq!(b.ray(vec3(3., 0., 0.), -Vec3::X, 100.), Some(2.));
        assert_eq!(b.ray(vec3(3., 0., 0.), Vec3::X, 100.), None);
    }
    #[test]
    fn walk_is_normalized() {
        let mut a = Simulation::new();
        let mut b = Simulation::new();
        run(
            &mut a,
            Input {
                movement: vec2(0., 1.),
                ..Input::default()
            },
            100,
        );
        run(
            &mut b,
            Input {
                movement: vec2(1., 1.),
                ..Input::default()
            },
            100,
        );
        assert!(b.player.speed() <= a.player.speed() + 0.001);
        assert!(b.player.speed() > a.player.speed() * 0.8);
    }
    #[test]
    fn jump_lands_and_cannot_repeat_in_air() {
        let mut s = Simulation::new();
        run(
            &mut s,
            Input {
                jump: true,
                ..Input::default()
            },
            1,
        );
        let v = s.player.velocity.y;
        run(
            &mut s,
            Input {
                jump: true,
                ..Input::default()
            },
            1,
        );
        assert!(s.player.velocity.y < v);
        run(&mut s, Input::default(), 180);
        assert!(s.player.grounded);
        assert!(s.player.position.y.abs() < 0.001);
    }
    #[test]
    fn walls_stop_player() {
        let mut s = Simulation::new();
        s.player.position = vec3(31., 0., 9.);
        run(
            &mut s,
            Input {
                movement: vec2(1., 0.),
                ..Input::default()
            },
            500,
        );
        assert!(s.player.position.x <= 31.75 - RADIUS + 0.001);
    }
    #[test]
    fn reload_conserves_ammunition() {
        let mut s = Simulation::new();
        s.player.ammo = 7;
        s.player.reserve = 10;
        run(
            &mut s,
            Input {
                reload: true,
                ..Input::default()
            },
            1,
        );
        run(&mut s, Input::default(), 300);
        assert_eq!(s.player.ammo, 17);
        assert_eq!(s.player.reserve, 0);
    }
    #[test]
    fn auto_fire_has_bounded_rate() {
        let mut s = Simulation::new();
        run(
            &mut s,
            Input {
                fire: true,
                ..Input::default()
            },
            120,
        );
        assert!((11..=12).contains(&s.stats.shots));
        assert_eq!(s.player.ammo, 30 - s.stats.shots);
    }
    #[test]
    fn target_obeys_occlusion() {
        let mut s = Simulation::new();
        s.player.position = vec3(0., 0., -10.);
        s.player.pitch = -0.08;
        s.blocks.push(Block {
            bounds: Aabb::from_center(vec3(0., 2., -16.), vec3(5., 4., 1.)),
            kind: 2,
        });
        s.targets[2].bounds = Aabb::from_center(vec3(0., 0.6, -24.), Vec3::splat(0.8));
        run(
            &mut s,
            Input {
                fire: true,
                ads: true,
                ..Input::default()
            },
            120,
        );
        assert_eq!(s.stats.hits, 0);
    }
    #[test]
    fn standing_is_blocked_by_low_ceiling() {
        let mut s = Simulation::new();
        s.player.position = vec3(10., 0., -4.);
        s.player.crouched = true;
        run(&mut s, Input::default(), 1);
        assert!(s.player.crouched);
    }
    #[test]
    fn deterministic_replay() {
        let mut a = Simulation::new();
        let mut b = Simulation::new();
        let input = Input {
            movement: vec2(0., 1.),
            fire: true,
            ..Input::default()
        };
        run(&mut a, input, 120);
        run(&mut b, input, 120);
        assert_eq!(a.player.position, b.player.position);
        assert_eq!(a.player.recoil, b.player.recoil);
    }
    #[test]
    fn staircase_is_walkable() {
        let mut s = Simulation::new();
        s.player.position = vec3(10., 0., 7.);
        run(
            &mut s,
            Input {
                movement: vec2(0., 1.),
                ..Input::default()
            },
            180,
        );
        assert!(s.player.position.y > 1.);
        assert!(s.player.position.z < 1.);
    }
    #[test]
    fn held_jump_is_not_auto_bunnyhop() {
        let mut s = Simulation::new();
        run(
            &mut s,
            Input {
                jump: true,
                ..Input::default()
            },
            180,
        );
        assert!(s.player.grounded);
        assert!(s.player.position.y.abs() < 0.001);
    }
    #[test]
    fn jump_apex_and_airtime_match_declared_tolerance() {
        let mut s = Simulation::new();
        let mut highest: f32 = 0.;
        let mut ticks = 0;
        s.update(
            Input {
                jump: true,
                ..Input::default()
            },
            &Settings::default(),
            FIXED_DT,
        );
        while !s.player.grounded && ticks < 240 {
            highest = highest.max(s.player.position.y);
            s.update(Input::default(), &Settings::default(), FIXED_DT);
            ticks += 1;
        }
        assert!((highest - 0.9906).abs() < 0.04, "apex {highest}");
        assert!((ticks as f32 * FIXED_DT - 0.6245).abs() < 0.03);
    }
    #[test]
    fn sprint_fire_transition_enforces_raise_delay() {
        let mut s = Simulation::new();
        run(
            &mut s,
            Input {
                movement: vec2(0., 1.),
                sprint: true,
                ..Input::default()
            },
            40,
        );
        assert!(s.player.sprinting);
        let fire = Input {
            movement: vec2(0., 1.),
            sprint: true,
            fire: true,
            ..Input::default()
        };
        run(&mut s, fire, 1);
        assert!(!s.player.sprinting);
        assert_eq!(s.stats.shots, 0);
        run(&mut s, fire, 30);
        assert!(s.stats.shots > 0);
    }
    #[test]
    fn reload_credits_before_ready_but_blocks_fire() {
        let mut s = Simulation::new();
        s.player.ammo = 2;
        run(
            &mut s,
            Input {
                reload: true,
                ..Input::default()
            },
            1,
        );
        run(
            &mut s,
            Input {
                fire: true,
                ..Input::default()
            },
            190,
        );
        assert_eq!(s.player.ammo, 30);
        assert!(s.player.reload_left > 0.);
        assert_eq!(s.stats.shots, 0);
    }
    #[test]
    fn sprint_exhaustion_does_not_oscillate_while_held() {
        let mut s = Simulation::new();
        let input = Input {
            sprint: true,
            movement: vec2(0., 1.),
            ..Input::default()
        };
        run(&mut s, input, 800);
        assert!(!s.player.sprinting);
        assert!(s.player.sprint_exhausted);
    }
    #[test]
    fn render_rates_feed_identical_fixed_step_results() {
        fn trace(fps: u32) -> Simulation {
            let mut sim = Simulation::new();
            let mut accumulator = 0_f64;
            let dt = 1_f64 / 120.;
            for _ in 0..fps * 2 {
                accumulator += 1_f64 / fps as f64;
                while accumulator + 1e-10 >= dt {
                    sim.update(
                        Input {
                            movement: vec2(0., 1.),
                            ..Input::default()
                        },
                        &Settings::default(),
                        FIXED_DT,
                    );
                    accumulator -= dt;
                }
            }
            sim
        }
        let a = trace(30);
        for fps in [60, 144] {
            let b = trace(fps);
            assert_eq!(a.player.position, b.player.position);
            assert_eq!(a.time, b.time);
        }
    }
    #[test]
    fn prone_clearance_keeps_camera_inside_tunnel() {
        let mut s = Simulation::new();
        run(
            &mut s,
            Input {
                prone: true,
                ..Input::default()
            },
            90,
        );
        assert!(s.player.prone);
        assert!((s.player.eye_height - 0.2794).abs() < 0.001);
        s.player.position = vec3(22., 0., -4.);
        run(&mut s, Input::default(), 120);
        assert!(s.player.prone);
        assert!(s.player.eye().y < 0.813);
    }
    #[test]
    fn lower_stance_jump_requests_stand_without_launching() {
        let mut s = Simulation::new();
        run(
            &mut s,
            Input {
                crouch: true,
                ..Input::default()
            },
            30,
        );
        run(
            &mut s,
            Input {
                jump: true,
                crouch: true,
                ..Input::default()
            },
            1,
        );
        assert!(s.player.grounded);
        assert!(!s.player.crouched);
        run(
            &mut s,
            Input {
                crouch: true,
                ..Input::default()
            },
            30,
        );
        assert!(!s.player.crouched);
    }
    #[test]
    fn ramps_walk_at_thirty_and_forty_five_but_not_fifty() {
        for (x, should_climb) in [(-22., true), (-15., true), (-8., false)] {
            let mut s = Simulation::new();
            s.player.position = vec3(x, 0., -17.);
            run(
                &mut s,
                Input {
                    movement: vec2(0., 1.),
                    ..Input::default()
                },
                100,
            );
            if should_climb {
                assert!(
                    s.player.position.y > 1.,
                    "x={x} pos={:?}",
                    s.player.position
                );
            } else {
                assert!(s.player.position.z >= -18.1);
                assert!(s.player.position.y < 0.1);
            }
        }
    }
    #[test]
    fn ramp_hitscan_does_not_use_invisible_bounding_box() {
        let r = Ramp {
            x: 0.,
            z: 0.,
            width: 4.,
            length: 4.,
            height: 4.,
        };
        assert!(r
            .ray(vec3(0., 5., -1.), -Vec3::Y, 10.)
            .is_some_and(|d| (d - 4.).abs() < 0.001));
        assert_eq!(r.ray(vec3(-3., 3., -1.), Vec3::X, 10.), None);
    }
    #[test]
    fn stance_speeds_include_prone_and_full_ads() {
        for (input, expected) in [
            (
                Input {
                    movement: vec2(0., 1.),
                    ..Input::default()
                },
                4.826,
            ),
            (
                Input {
                    movement: vec2(1., 0.),
                    ..Input::default()
                },
                4.826 * 0.8,
            ),
            (
                Input {
                    movement: vec2(0., -1.),
                    ..Input::default()
                },
                4.826 * 0.7,
            ),
            (
                Input {
                    movement: vec2(1., 1.),
                    ..Input::default()
                },
                4.826,
            ),
            (
                Input {
                    movement: vec2(1., -1.),
                    ..Input::default()
                },
                4.826 * 0.8,
            ),
            (
                Input {
                    movement: vec2(0., 1.),
                    crouch: true,
                    ..Input::default()
                },
                4.826 * 0.65,
            ),
            (
                Input {
                    movement: vec2(0., 1.),
                    prone: true,
                    ..Input::default()
                },
                4.826 * 0.15,
            ),
            (
                Input {
                    movement: vec2(0., 1.),
                    ads: true,
                    ..Input::default()
                },
                4.826 * 0.5,
            ),
        ] {
            let mut s = Simulation::new();
            run(&mut s, input, 120);
            assert!(
                (s.player.speed() - expected).abs() < expected * 0.01,
                "expected {expected}, got {}",
                s.player.speed()
            );
        }
    }
    #[test]
    fn blocked_standing_cannot_cancel_tactical_reload() {
        let mut s = Simulation::new();
        run(
            &mut s,
            Input {
                crouch: true,
                ..Input::default()
            },
            30,
        );
        s.player.position = vec3(10., 0., -4.);
        s.player.ammo = 7;
        run(
            &mut s,
            Input {
                crouch: true,
                reload: true,
                ..Input::default()
            },
            1,
        );
        run(
            &mut s,
            Input {
                movement: vec2(0., 1.),
                sprint: true,
                ..Input::default()
            },
            8,
        );
        assert!(s.player.crouched);
        assert!(!s.player.sprinting);
        assert!(s.player.reload_left > 0.);
        assert_eq!(s.player.ammo, 7);
    }
}
