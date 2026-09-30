//! Original deterministic simulation. No original-game source or assets are used.
pub mod settings;
pub mod sim;

pub mod control;

pub mod clock;

pub mod asset;
include!(concat!(env!("OUT_DIR"), "/weapon_embed.rs"));

pub mod asset_path;

pub mod session;
