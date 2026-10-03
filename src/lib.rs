//! Original deterministic simulation. No original-game source or assets are used.
pub mod settings;
pub mod sim;

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

pub mod authored_walk_presentation;
