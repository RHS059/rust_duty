//! Backend-neutral CPU text and feature-gated native GPU rendering.
pub mod text;

#[cfg(feature = "wgpu-runtime")]
mod arena;
#[cfg(feature = "wgpu-runtime")]
mod backend;
#[cfg(feature = "wgpu-runtime")]
mod capture;
#[cfg(feature = "wgpu-runtime")]
mod device;
#[cfg(feature = "wgpu-runtime")]
mod frame;
#[cfg(feature = "wgpu-runtime")]
mod lines;
#[cfg(feature = "wgpu-runtime")]
mod mesh;
#[cfg(feature = "wgpu-runtime")]
mod plan;
#[cfg(feature = "wgpu-runtime")]
pub mod runtime;
#[cfg(feature = "wgpu-runtime")]
mod sprite2d;
#[cfg(feature = "wgpu-runtime")]
mod target;

#[cfg(feature = "wgpu-runtime")]
pub use backend::WgpuRenderer;
#[cfg(feature = "wgpu-runtime")]
pub use device::BackendSelection;
