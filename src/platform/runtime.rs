//! Runtime services for the winit application loop.
//!
//! CPU-only builds retain this API but cannot create or impersonate a window.

#[cfg(feature = "wgpu-runtime")]
pub use super::window::{
    framebuffer_size, get_fps, get_time, mouse_delta_position, mouse_position,
    screen_height, screen_width, set_cursor_grab, set_fullscreen, show_mouse,
};

pub fn wgpu_active() -> bool {
    #[cfg(feature = "wgpu-runtime")]
    {
        super::window::is_active()
    }
    #[cfg(not(feature = "wgpu-runtime"))]
    {
        false
    }
}

pub async fn next_frame() -> Result<(), String> {
    #[cfg(feature = "wgpu-runtime")]
    if wgpu_active() {
        super::window::next_frame().await;
        return Ok(());
    }
    Err("no active window runtime".into())
}

#[cfg(not(feature = "wgpu-runtime"))]
mod unavailable {
    fn no_window() -> ! {
        panic!("window services require the wgpu-runtime feature")
    }
    pub fn get_time() -> f64 {
        no_window()
    }
    pub fn get_fps() -> i32 {
        no_window()
    }
    pub fn screen_width() -> f32 {
        no_window()
    }
    pub fn screen_height() -> f32 {
        no_window()
    }
    pub fn mouse_position() -> (f32, f32) {
        no_window()
    }
    pub fn mouse_delta_position() -> glam::Vec2 {
        no_window()
    }
    pub fn framebuffer_size() -> (u32, u32) {
        no_window()
    }
    pub fn set_cursor_grab(_grab: bool) {
        no_window()
    }
    pub fn show_mouse(_show: bool) {
        no_window()
    }
    pub fn set_fullscreen(_fullscreen: bool) {
        no_window()
    }
}

#[cfg(not(feature = "wgpu-runtime"))]
pub use unavailable::*;
