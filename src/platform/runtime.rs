//! Runtime services shared by legacy and winit application loops.
//!
//! Rendering and simulation have no ownership here. Select the active window
//! runtime without touching Macroquad globals when running under winit.

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

pub fn get_time() -> f64 {
    #[cfg(feature = "wgpu-runtime")]
    if wgpu_active() {
        return super::window::get_time();
    }
    macroquad::time::get_time()
}

pub fn get_fps() -> i32 {
    #[cfg(feature = "wgpu-runtime")]
    if wgpu_active() {
        return super::window::get_fps();
    }
    macroquad::time::get_fps()
}

pub fn screen_width() -> f32 {
    #[cfg(feature = "wgpu-runtime")]
    if wgpu_active() {
        return super::window::screen_width();
    }
    macroquad::window::screen_width()
}

pub fn screen_height() -> f32 {
    #[cfg(feature = "wgpu-runtime")]
    if wgpu_active() {
        return super::window::screen_height();
    }
    macroquad::window::screen_height()
}

pub fn mouse_position() -> (f32, f32) {
    #[cfg(feature = "wgpu-runtime")]
    if wgpu_active() {
        return super::window::mouse_position();
    }
    macroquad::input::mouse_position()
}

pub fn mouse_delta_position() -> glam::Vec2 {
    #[cfg(feature = "wgpu-runtime")]
    if wgpu_active() {
        return super::window::mouse_delta_position();
    }
    macroquad::input::mouse_delta_position()
}

pub fn set_cursor_grab(grab: bool) {
    #[cfg(feature = "wgpu-runtime")]
    if wgpu_active() {
        super::window::set_cursor_grab(grab);
        return;
    }
    macroquad::input::set_cursor_grab(grab);
}

pub fn show_mouse(show: bool) {
    #[cfg(feature = "wgpu-runtime")]
    if wgpu_active() {
        super::window::show_mouse(show);
        return;
    }
    macroquad::input::show_mouse(show);
}

pub fn set_fullscreen(fullscreen: bool) {
    #[cfg(feature = "wgpu-runtime")]
    if wgpu_active() {
        super::window::set_fullscreen(fullscreen);
        return;
    }
    macroquad::window::set_fullscreen(fullscreen);
}

pub async fn next_frame() -> Result<(), String> {
    #[cfg(feature = "wgpu-runtime")]
    if wgpu_active() {
        super::window::next_frame().await;
        return Ok(());
    }
    #[cfg(feature = "legacy-macroquad")]
    {
        crate::legacy_macroquad::runtime::finish_frame()?;
        macroquad::window::next_frame().await;
        crate::legacy_macroquad::runtime::start_frame()
    }
    #[cfg(not(feature = "legacy-macroquad"))]
    Err("no active window runtime".into())
}

/// Physical capture extent, independent of the logical UI coordinate system.
pub fn framebuffer_size() -> (u32, u32) {
    #[cfg(feature = "wgpu-runtime")]
    if wgpu_active() {
        return super::window::framebuffer_size();
    }
    let (width, height) = macroquad::miniquad::window::screen_size();
    (width as u32, height as u32)
}
