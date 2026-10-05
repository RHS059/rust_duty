//! Original deterministic simulation. No original-game source or assets are used.
/// The release identity assigned to this exact CI build; local builds use Cargo's version.
pub const BUILD_VERSION: &str = env!("RUST_DUTY_BUILD_VERSION");
/// Unique CI run and attempt, or an explicitly local compilation identifier.
pub const BUILD_NUMBER: &str = env!("RUST_DUTY_BUILD_NUMBER");
/// Human-facing identity. Do not pass this metadata label to the updater.
pub const BUILD_LABEL: &str = env!("RUST_DUTY_BUILD_LABEL");
pub mod settings;
pub mod sim;

pub mod action;

pub mod weapon_sway;

pub mod body_presentation;

pub mod traversal_replay;

pub mod control;

pub mod clock;

pub mod asset;
include!(concat!(env!("OUT_DIR"), "/weapon_embed.rs"));

pub mod asset_path;

pub mod session;

pub mod arms;
pub mod skinned_asset;
pub mod weapon_animation;

pub mod view_animation;

pub mod ammo_supply;
pub mod ammo_supply_view;

pub mod reference_motion;

pub mod weapon_ik;

pub mod locomotion_presentation;

pub mod viewmodel_animation;

pub mod authored_locomotion_path;

pub mod authored_locomotion_adapter;

pub mod animation_manifest;
pub mod authored_pose_return;
pub mod authored_reload;

pub mod authored_walk;

pub mod scene_lighting;

pub mod authored_ads;

pub mod layered_locomotion;

pub mod muzzle_fx;

pub mod authored_jump;

pub mod input_frame;
pub mod platform;

pub mod draw;
pub mod legacy_macroquad;
pub mod render;
