//! Desktop winit runtime. The existing async application owns simulation and
//! yields at `next_frame`; this module only samples input and presents frames.

use super::input::{InputAccumulator, InputFrame, KeyCode, MouseButton};
use glam::Vec2;
use std::{
    cell::RefCell,
    future::Future,
    pin::Pin,
    sync::Arc,
    task::{Context, Poll, Waker},
    time::Instant,
};
use winit::{
    application::ApplicationHandler,
    dpi::{LogicalSize, PhysicalSize},
    event::{DeviceEvent, DeviceId, ElementState, WindowEvent},
    event_loop::{ActiveEventLoop, ControlFlow, EventLoop},
    keyboard::{KeyCode as NativeKey, PhysicalKey},
    window::{CursorGrabMode, Fullscreen, Window, WindowId},
};

/// Outcome of surface acquisition before consuming a presentation/input frame.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FrameStart {
    Ready,
    /// Recoverable surface timeout: retain queued input and do not poll the app.
    Skip,
}

/// Renderer integration boundary. Initialization receives an owned `Arc<Window>`
/// so a surface can retain it safely. Sizes passed to resize are physical pixels;
/// frame sizes are logical pixels, matching cursor coordinates and UI layout.
pub trait FrameHooks {
    fn resize(&mut self, width: u32, height: u32, scale_factor: f64) -> Result<(), String>;
    fn begin_frame(&mut self, width: f32, height: f32) -> Result<FrameStart, String>;
    fn end_frame(&mut self) -> Result<(), String>;
}

type HookFactory = Box<dyn FnOnce(Arc<Window>) -> Result<Box<dyn FrameHooks>, String>>;

struct State {
    window: Option<Arc<Window>>,
    input: InputAccumulator,
    frame: InputFrame,
    start: Instant,
    previous_frame: Instant,
    frame_time: f32,
    generation: u64,
    size: PhysicalSize<u32>,
    scale_factor: f64,
}

impl Default for State {
    fn default() -> Self {
        let now = Instant::now();
        Self {
            window: None,
            input: InputAccumulator::default(),
            frame: InputFrame::default(),
            start: now,
            previous_frame: now,
            frame_time: 0.,
            generation: 0,
            size: PhysicalSize::new(1, 1),
            scale_factor: 1.,
        }
    }
}

impl State {
    fn logical_size(&self) -> Vec2 {
        let size = self.size.to_logical::<f32>(self.scale_factor);
        Vec2::new(size.width, size.height)
    }
    fn start_frame(&mut self, start: FrameStart, now: Instant) -> bool {
        if start == FrameStart::Skip {
            return false;
        }
        self.advance_frame(now);
        true
    }
    fn advance_frame(&mut self, now: Instant) {
        self.frame_time = now.duration_since(self.previous_frame).as_secs_f32();
        self.previous_frame = now;
        self.generation = self.generation.wrapping_add(1);
        self.frame = self.input.take_frame();
    }
}

thread_local! { static STATE: RefCell<State> = RefCell::new(State::default()); }

/// Whether this thread is currently running the winit window runtime.
pub fn is_active() -> bool {
    STATE.with(|s| s.borrow().window.is_some())
}

pub fn snapshot_input() -> InputFrame {
    STATE.with(|s| s.borrow().frame.clone())
}

/// Clear both the native accumulator and the snapshot already visible to the app.
pub fn clear_input() {
    STATE.with(|s| {
        let mut s = s.borrow_mut();
        s.input.clear();
        s.frame.clear();
    });
}
pub fn get_time() -> f64 {
    STATE.with(|s| s.borrow().start.elapsed().as_secs_f64())
}
pub fn get_frame_time() -> f32 {
    STATE.with(|s| s.borrow().frame_time)
}
pub fn get_fps() -> i32 {
    let dt = get_frame_time();
    if dt > 0. {
        (1. / dt).round() as i32
    } else {
        0
    }
}
pub fn framebuffer_size() -> (u32, u32) {
    STATE.with(|s| {
        let size = s.borrow().size;
        (size.width, size.height)
    })
}
pub fn screen_width() -> f32 {
    STATE.with(|s| s.borrow().logical_size().x)
}
pub fn screen_height() -> f32 {
    STATE.with(|s| s.borrow().logical_size().y)
}
pub fn mouse_position() -> (f32, f32) {
    STATE.with(|s| {
        let p = s.borrow().frame.mouse_position;
        (p[0], p[1])
    })
}

fn normalized_mouse_delta(delta: [f32; 2], logical_size: Vec2) -> Vec2 {
    // The old app multiplies this reversed normalized delta by logical size / 2.
    // Keep raw device movement in physical units, with no additional DPI divide:
    // the composition must equal the physical delta at both 100% and 200% DPI.
    Vec2::new(
        -2. * delta[0] / logical_size.x.max(1.),
        -2. * delta[1] / logical_size.y.max(1.),
    )
}
pub fn mouse_delta_position() -> Vec2 {
    STATE.with(|s| {
        let s = s.borrow();
        normalized_mouse_delta(s.frame.mouse_delta, s.logical_size())
    })
}

pub fn set_cursor_grab(grab: bool) {
    STATE.with(|s| {
        if let Some(window) = &s.borrow().window {
            let result = if grab {
                // Locked provides raw relative motion; Windows commonly supports
                // Confined instead, so retain that supported fallback.
                window
                    .set_cursor_grab(CursorGrabMode::Locked)
                    .or_else(|_| window.set_cursor_grab(CursorGrabMode::Confined))
            } else {
                window.set_cursor_grab(CursorGrabMode::None)
            };
            if let Err(error) = result {
                eprintln!("Cursor grab unavailable: {error}");
            }
        }
    });
}
pub fn show_mouse(visible: bool) {
    STATE.with(|s| {
        if let Some(window) = &s.borrow().window {
            window.set_cursor_visible(visible);
        }
    });
}
pub fn set_fullscreen(fullscreen: bool) {
    STATE.with(|s| {
        if let Some(window) = &s.borrow().window {
            window.set_fullscreen(
                fullscreen.then(|| Fullscreen::Borderless(window.current_monitor())),
            );
        }
    });
}

/// A freshly awaited frame always yields, even if polled repeatedly in the same
/// redraw. It completes only when a subsequent presentation frame is sampled.
pub struct NextFrame {
    first_generation: Option<u64>,
}
pub fn next_frame() -> NextFrame {
    NextFrame {
        first_generation: None,
    }
}
impl Future for NextFrame {
    type Output = ();
    fn poll(mut self: Pin<&mut Self>, _cx: &mut Context<'_>) -> Poll<()> {
        let generation = STATE.with(|s| s.borrow().generation);
        match self.first_generation {
            Some(first) if first != generation => Poll::Ready(()),
            _ => {
                self.first_generation = Some(generation);
                Poll::Pending
            }
        }
    }
}

/// Run on the process main thread. No simulation or asynchronous app work is
/// polled outside RedrawRequested. The desktop renderer controls presentation
/// pacing (normally FIFO/vsync); event processing remains responsive while idle.
pub fn run(
    title: &str,
    width: u32,
    height: u32,
    make_hooks: impl FnOnce(Arc<Window>) -> Result<Box<dyn FrameHooks>, String> + 'static,
    future: impl Future<Output = Result<(), String>> + 'static,
) -> Result<(), String> {
    let event_loop = EventLoop::new().map_err(|e| e.to_string())?;
    event_loop.set_control_flow(ControlFlow::Wait);
    STATE.with(|s| *s.borrow_mut() = State::default());
    let mut runtime = Runtime {
        title: title.to_owned(),
        size: LogicalSize::new(width.max(1), height.max(1)),
        window: None,
        make_hooks: Some(Box::new(make_hooks)),
        hooks: None,
        future: Box::pin(future),
        error: None,
        suspended: false,
    };
    let result = event_loop.run_app(&mut runtime).map_err(|e| e.to_string());
    // Drop the surface before the final window references, and release the TLS
    // copy even after a renderer error or a native close request.
    runtime.hooks.take();
    STATE.with(|s| s.borrow_mut().window = None);
    result?;
    runtime.error.map_or(Ok(()), Err)
}

/// Submit the recorded final frame before its application result can exit the loop.
fn poll_and_submit(
    future: Pin<&mut dyn Future<Output = Result<(), String>>>,
    hooks: &mut dyn FrameHooks,
    before_present: impl FnOnce(),
) -> Result<Poll<Result<(), String>>, String> {
    let result = future.poll(&mut Context::from_waker(Waker::noop()));
    before_present();
    hooks.end_frame()?;
    Ok(result)
}

struct Runtime {
    title: String,
    size: LogicalSize<u32>,
    window: Option<Arc<Window>>,
    make_hooks: Option<HookFactory>,
    hooks: Option<Box<dyn FrameHooks>>,
    future: Pin<Box<dyn Future<Output = Result<(), String>>>>,
    error: Option<String>,
    suspended: bool,
}

impl Runtime {
    fn fail(&mut self, event_loop: &ActiveEventLoop, error: String) {
        self.error = Some(error);
        event_loop.exit();
    }
    fn resize(&mut self, event_loop: &ActiveEventLoop, size: PhysicalSize<u32>, scale_factor: f64) {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.size = size;
            s.scale_factor = scale_factor;
        });
        // Surface configuration with either dimension zero is invalid. Keep the
        // real size in state and stop redraws until the native restore event.
        if size.width == 0 || size.height == 0 {
            return;
        }
        if let Some(hooks) = &mut self.hooks {
            if let Err(error) = hooks.resize(size.width, size.height, scale_factor) {
                self.fail(event_loop, error);
            }
        }
    }
    fn redraw(&mut self, event_loop: &ActiveEventLoop) {
        let size = STATE.with(|s| s.borrow().size);
        if self.suspended || size.width == 0 || size.height == 0 || event_loop.exiting() {
            return;
        }
        let logical_size = STATE.with(|s| s.borrow().logical_size());
        let Some(hooks) = &mut self.hooks else {
            return;
        };
        let start = match hooks.begin_frame(logical_size.x, logical_size.y) {
            Ok(start) => start,
            Err(error) => {
                self.fail(event_loop, error);
                return;
            }
        };
        if !STATE.with(|s| s.borrow_mut().start_frame(start, Instant::now())) {
            return;
        }
        // Frames are requested unconditionally while drawable, so futures do
        // not need to signal another wake to be polled at the next redraw.
        let app_result = match poll_and_submit(self.future.as_mut(), hooks.as_mut(), || {
            if let Some(window) = &self.window {
                window.pre_present_notify();
            }
        }) {
            Ok(result) => result,
            Err(error) => {
                self.fail(event_loop, error);
                return;
            }
        };
        match app_result {
            Poll::Ready(Ok(())) => event_loop.exit(),
            Poll::Ready(Err(error)) => self.fail(event_loop, error),
            Poll::Pending => {}
        }
    }
}

impl ApplicationHandler for Runtime {
    fn resumed(&mut self, event_loop: &ActiveEventLoop) {
        self.suspended = false;
        if let Some(window) = self.window.clone() {
            STATE.with(|s| s.borrow_mut().input.focus_event(window.has_focus()));
            self.resize(event_loop, window.inner_size(), window.scale_factor());
            window.request_redraw();
            return;
        }
        let attributes = Window::default_attributes()
            .with_title(&self.title)
            .with_inner_size(self.size);
        let window = match event_loop.create_window(attributes) {
            Ok(window) => Arc::new(window),
            Err(error) => {
                self.fail(event_loop, error.to_string());
                return;
            }
        };
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.window = Some(window.clone());
            s.size = window.inner_size();
            s.scale_factor = window.scale_factor();
            s.input.focus_event(window.has_focus());
        });
        self.window = Some(window.clone());
        let Some(make_hooks) = self.make_hooks.take() else {
            return;
        };
        match make_hooks(window.clone()) {
            Ok(hooks) => self.hooks = Some(hooks),
            Err(error) => {
                self.fail(event_loop, error);
                return;
            }
        }
        self.resize(event_loop, window.inner_size(), window.scale_factor());
        window.request_redraw();
    }
    fn suspended(&mut self, _event_loop: &ActiveEventLoop) {
        self.suspended = true;
        STATE.with(|s| s.borrow_mut().input.focus_event(false));
        set_cursor_grab(false);
        show_mouse(true);
    }
    fn window_event(
        &mut self,
        event_loop: &ActiveEventLoop,
        window_id: WindowId,
        event: WindowEvent,
    ) {
        let Some(window) = self
            .window
            .clone()
            .filter(|window| window.id() == window_id)
        else {
            return;
        };
        match event {
            WindowEvent::CloseRequested | WindowEvent::Destroyed => event_loop.exit(),
            WindowEvent::RedrawRequested => self.redraw(event_loop),
            WindowEvent::Resized(size) => self.resize(event_loop, size, window.scale_factor()),
            WindowEvent::ScaleFactorChanged { scale_factor, .. } => {
                self.resize(event_loop, window.inner_size(), scale_factor)
            }
            WindowEvent::Focused(focused) => {
                STATE.with(|s| s.borrow_mut().input.focus_event(focused));
                if !focused {
                    set_cursor_grab(false);
                    show_mouse(true);
                }
            }
            WindowEvent::KeyboardInput { event, .. } => {
                if let PhysicalKey::Code(code) = event.physical_key {
                    if let Some(key) = map_key(code) {
                        STATE.with(|s| {
                            s.borrow_mut().input.key_event(
                                key,
                                event.state == ElementState::Pressed,
                                event.repeat,
                            )
                        });
                    }
                }
            }
            WindowEvent::MouseInput { state, button, .. } => {
                STATE.with(|s| {
                    s.borrow_mut().input.mouse_button_event(
                        map_mouse_button(button),
                        state == ElementState::Pressed,
                    )
                });
            }
            WindowEvent::CursorMoved { position, .. } => {
                let logical = position.to_logical::<f32>(window.scale_factor());
                STATE.with(|s| s.borrow_mut().input.cursor_moved(logical.x, logical.y));
            }
            _ => {}
        }
    }
    fn device_event(
        &mut self,
        _event_loop: &ActiveEventLoop,
        _device_id: DeviceId,
        event: DeviceEvent,
    ) {
        if let DeviceEvent::MouseMotion { delta: (dx, dy) } = event {
            STATE.with(|s| s.borrow_mut().input.mouse_motion(dx as f32, dy as f32));
        }
    }
    fn about_to_wait(&mut self, event_loop: &ActiveEventLoop) {
        let size = STATE.with(|s| s.borrow().size);
        if !self.suspended && !event_loop.exiting() && size.width > 0 && size.height > 0 {
            if let Some(window) = &self.window {
                window.request_redraw();
            }
        }
    }
}

fn map_mouse_button(button: winit::event::MouseButton) -> MouseButton {
    match button {
        winit::event::MouseButton::Left => MouseButton::Left,
        winit::event::MouseButton::Right => MouseButton::Right,
        winit::event::MouseButton::Middle => MouseButton::Middle,
        winit::event::MouseButton::Back => MouseButton::Other(4),
        winit::event::MouseButton::Forward => MouseButton::Other(5),
        winit::event::MouseButton::Other(value) => MouseButton::Other(value),
    }
}
fn map_key(key: NativeKey) -> Option<KeyCode> {
    Some(match key {
        NativeKey::KeyA => KeyCode::A,
        NativeKey::KeyC => KeyCode::C,
        NativeKey::KeyD => KeyCode::D,
        NativeKey::KeyE => KeyCode::E,
        NativeKey::KeyF => KeyCode::F,
        NativeKey::KeyM => KeyCode::M,
        NativeKey::KeyQ => KeyCode::Q,
        NativeKey::KeyR => KeyCode::R,
        NativeKey::KeyS => KeyCode::S,
        NativeKey::KeyV => KeyCode::V,
        NativeKey::KeyW => KeyCode::W,
        NativeKey::KeyX => KeyCode::X,
        NativeKey::KeyZ => KeyCode::Z,
        NativeKey::Digit2 => KeyCode::Key2,
        NativeKey::Space => KeyCode::Space,
        NativeKey::Enter => KeyCode::Enter,
        NativeKey::Escape => KeyCode::Escape,
        NativeKey::Tab => KeyCode::Tab,
        NativeKey::ShiftLeft => KeyCode::LeftShift,
        NativeKey::ShiftRight => KeyCode::RightShift,
        NativeKey::ControlLeft => KeyCode::LeftControl,
        NativeKey::ControlRight => KeyCode::RightControl,
        NativeKey::AltLeft => KeyCode::LeftAlt,
        NativeKey::AltRight => KeyCode::RightAlt,
        NativeKey::SuperLeft => KeyCode::LeftSuper,
        NativeKey::SuperRight => KeyCode::RightSuper,
        NativeKey::ArrowUp => KeyCode::Up,
        NativeKey::ArrowDown => KeyCode::Down,
        NativeKey::ArrowLeft => KeyCode::Left,
        NativeKey::ArrowRight => KeyCode::Right,
        NativeKey::Home => KeyCode::Home,
        NativeKey::End => KeyCode::End,
        NativeKey::PageUp => KeyCode::PageUp,
        NativeKey::PageDown => KeyCode::PageDown,
        NativeKey::BracketLeft => KeyCode::LeftBracket,
        NativeKey::BracketRight => KeyCode::RightBracket,
        NativeKey::Minus => KeyCode::Minus,
        NativeKey::Equal => KeyCode::Equal,
        NativeKey::F1 => KeyCode::F1,
        NativeKey::F2 => KeyCode::F2,
        NativeKey::F5 => KeyCode::F5,
        NativeKey::F6 => KeyCode::F6,
        NativeKey::F7 => KeyCode::F7,
        NativeKey::F8 => KeyCode::F8,
        NativeKey::F9 => KeyCode::F9,
        NativeKey::F10 => KeyCode::F10,
        NativeKey::F11 => KeyCode::F11,
        _ => return None,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn final_success_and_app_error_both_submit_before_completion() {
        use std::{cell::RefCell, rc::Rc};
        struct Hooks {
            events: Rc<RefCell<Vec<&'static str>>>,
            error: bool,
        }
        impl FrameHooks for Hooks {
            fn resize(&mut self, _: u32, _: u32, _: f64) -> Result<(), String> {
                Ok(())
            }
            fn begin_frame(&mut self, _: f32, _: f32) -> Result<FrameStart, String> {
                Ok(FrameStart::Ready)
            }
            fn end_frame(&mut self) -> Result<(), String> {
                self.events.borrow_mut().push("submit-and-readback");
                if self.error {
                    Err("final PNG write failed".into())
                } else {
                    Ok(())
                }
            }
        }
        for app_error in [false, true] {
            for submission_error in [false, true] {
                let events = Rc::new(RefCell::new(Vec::new()));
                let polled = events.clone();
                let mut future = Box::pin(async move {
                    polled.borrow_mut().push("app-final-frame");
                    if app_error {
                        Err("app failed".into())
                    } else {
                        Ok(())
                    }
                });
                let mut hooks = Hooks {
                    events: events.clone(),
                    error: submission_error,
                };
                let result = poll_and_submit(future.as_mut(), &mut hooks, || {
                    events.borrow_mut().push("pre-present");
                });
                assert_eq!(
                    *events.borrow(),
                    ["app-final-frame", "pre-present", "submit-and-readback"]
                );
                if submission_error {
                    assert_eq!(result.unwrap_err(), "final PNG write failed");
                } else {
                    assert_eq!(
                        result.unwrap(),
                        Poll::Ready(if app_error {
                            Err("app failed".into())
                        } else {
                            Ok(())
                        })
                    );
                }
            }
        }
    }

    #[test]
    fn skipped_surface_frame_preserves_edges_motion_and_generation() {
        let mut state = State::default();
        state.input.key_event(KeyCode::W, true, false);
        state.input.key_event(KeyCode::W, false, false);
        state.input.mouse_button_event(MouseButton::Left, true);
        state.input.mouse_button_event(MouseButton::Left, false);
        state.input.mouse_motion(7., -3.);
        let previous = state.previous_frame;
        assert!(!state.start_frame(FrameStart::Skip, Instant::now()));
        assert_eq!(state.generation, 0);
        assert_eq!(state.previous_frame, previous);
        assert!(!state.frame.is_key_pressed(KeyCode::W));
        assert!(state.start_frame(FrameStart::Ready, Instant::now()));
        assert_eq!(state.generation, 1);
        assert!(state.frame.is_key_pressed(KeyCode::W));
        assert!(state.frame.is_key_released(KeyCode::W));
        assert!(state.frame.is_mouse_button_pressed(MouseButton::Left));
        assert!(state.frame.is_mouse_button_released(MouseButton::Left));
        assert_eq!(state.frame.mouse_delta, [7., -3.]);
        assert!(state.start_frame(FrameStart::Ready, Instant::now()));
        assert!(!state.frame.is_key_pressed(KeyCode::W));
        assert!(!state.frame.is_key_released(KeyCode::W));
    }

    #[test]
    fn theme_reload_key_keeps_settings_reload_on_its_existing_key() {
        assert_eq!(map_key(NativeKey::F6), Some(KeyCode::F6));
        assert_eq!(map_key(NativeKey::F7), Some(KeyCode::F7));
    }

    #[test]
    fn next_frame_yields_until_a_different_redraw() {
        STATE.with(|s| *s.borrow_mut() = State::default());
        let mut frame = Box::pin(next_frame());
        let mut cx = Context::from_waker(Waker::noop());
        assert!(frame.as_mut().poll(&mut cx).is_pending());
        assert!(frame.as_mut().poll(&mut cx).is_pending());
        STATE.with(|s| s.borrow_mut().advance_frame(Instant::now()));
        assert!(frame.as_mut().poll(&mut cx).is_ready());
        assert!(Box::pin(next_frame()).as_mut().poll(&mut cx).is_pending());
    }
    #[test]
    fn logical_ui_and_mouse_sensitivity_are_dpi_independent() {
        for scale in [1., 1.25, 2.] {
            let state = State {
                size: PhysicalSize::new(1920, 1080),
                scale_factor: scale,
                ..State::default()
            };
            let logical = state.logical_size();
            assert!((logical.x - 1920. / scale as f32).abs() < 0.001);
            let normalized = normalized_mouse_delta([17., -23.], logical);
            let applied = -normalized * logical * 0.5;
            assert!((applied - Vec2::new(17., -23.)).length() < 0.001);
        }
    }
    #[test]
    fn clearing_input_invalidates_accumulator_and_snapshot() {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            *s = State::default();
            s.input.key_event(KeyCode::W, true, false);
            s.input.mouse_motion(3., 4.);
            s.advance_frame(Instant::now());
        });
        assert!(snapshot_input().is_key_down(KeyCode::W));
        clear_input();
        assert!(!snapshot_input().is_key_down(KeyCode::W));
        assert_eq!(mouse_delta_position(), Vec2::ZERO);
        STATE.with(|s| s.borrow_mut().advance_frame(Instant::now()));
        assert!(!snapshot_input().is_key_down(KeyCode::W));
    }
    #[test]
    fn physical_keys_keep_modifier_sides_and_function_keys() {
        for (native, expected) in [
            (NativeKey::ControlLeft, KeyCode::LeftControl),
            (NativeKey::ControlRight, KeyCode::RightControl),
            (NativeKey::SuperLeft, KeyCode::LeftSuper),
            (NativeKey::SuperRight, KeyCode::RightSuper),
            (NativeKey::F10, KeyCode::F10),
            (NativeKey::F11, KeyCode::F11),
            (NativeKey::Digit2, KeyCode::Key2),
        ] {
            assert_eq!(map_key(native), Some(expected));
        }
        assert_eq!(map_key(NativeKey::F24), None);
    }
}
