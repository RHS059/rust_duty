//! The legacy renderer and recorder live on macroquad's initialized render thread.
//! Flush before `next_frame().await`, restart afterward, and finish the final
//! recorder when the application future completes. No simulation or input lives here.
use super::LegacyRenderer;
use crate::draw::{facade, Renderer};
use std::cell::RefCell;

struct Driver<R> {
    renderer: R,
    recording: bool,
}
impl<R: Renderer> Driver<R> {
    fn start_frame(&mut self, width: u32, height: u32, scale: f64) -> Result<(), String> {
        if self.recording {
            return Err("legacy start_frame called before finishing the previous frame".into());
        }
        facade::begin_frame(width, height, scale)?;
        facade::set_backend_info(self.renderer.info().clone());
        self.recording = true;
        Ok(())
    }

    fn finish_frame(&mut self) -> Result<(), String> {
        if !std::mem::take(&mut self.recording) {
            return Err("legacy finish_frame called without an active frame".into());
        }
        let list = facade::take_draw_list()?;
        self.renderer.submit(&list)?;
        Ok(())
    }
}
thread_local! {
    static DRIVER: RefCell<Option<Driver<LegacyRenderer>>> = const { RefCell::new(None) };
}

/// Initialize after macroquad has created its context; starts the first recorder.
pub fn initialize(requested: impl Into<String>) -> Result<(), String> {
    DRIVER.with(|slot| {
        let mut slot = slot.borrow_mut();
        if slot.is_some() {
            return Err("legacy renderer is already initialized on this thread".into());
        }
        let mut driver = Driver {
            renderer: LegacyRenderer::new(requested)?,
            recording: false,
        };
        let (width, height, scale) = framebuffer_extent()?;
        driver.start_frame(width, height, scale)?;
        *slot = Some(driver);
        Ok(())
    })
}

/// Restart immediately after macroquad's next-frame future has completed.
pub fn start_frame() -> Result<(), String> {
    DRIVER.with(|slot| {
        let mut slot = slot.borrow_mut();
        let driver = slot.as_mut().ok_or("legacy renderer is not initialized")?;
        let (width, height, scale) = framebuffer_extent()?;
        driver.start_frame(width, height, scale)
    })
}

/// Submit all commands and finish synchronous capture writes before yielding or
/// returning from the application. Errors, including PNG I/O errors, propagate.
pub fn finish_frame() -> Result<(), String> {
    DRIVER.with(|slot| {
        let mut slot = slot.borrow_mut();
        let driver = slot.as_mut().ok_or("legacy renderer is not initialized")?;
        driver.finish_frame()?;
        // Ensure the final queued geometry reaches GL even without another
        // application await. Macroquad retains ownership of presentation.
        super::flush();
        Ok(())
    })
}

fn framebuffer_extent() -> Result<(u32, u32, f64), String> {
    // Miniquad reports real framebuffer pixels. Macroquad screen_width/height
    // divide those by this same DPI factor and remain the logical app source.
    let (width, height) = macroquad::miniquad::window::screen_size();
    let scale = macroquad::window::screen_dpi_scale();
    checked_extent(width, height, scale)
}
fn checked_extent(width: f32, height: f32, scale: f32) -> Result<(u32, u32, f64), String> {
    if ![width, height, scale].into_iter().all(f32::is_finite)
        || width < 1.
        || height < 1.
        || width >= u32::MAX as f32
        || height >= u32::MAX as f32
        || scale <= 0.
    {
        return Err("legacy framebuffer extent and DPI scale must be finite and positive".into());
    }
    Ok((width as u32, height as u32, f64::from(scale)))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::draw::{BackendInfo, Command, DrawList, FrameOutput, TextDimensions};

    struct FakeRenderer {
        info: BackendInfo,
        frames: Vec<DrawList>,
        error: Option<String>,
    }
    impl Renderer for FakeRenderer {
        fn info(&self) -> &BackendInfo {
            &self.info
        }
        fn measure_text(&self, _: &str, _: f32) -> Result<TextDimensions, String> {
            Ok(TextDimensions::default())
        }
        fn submit(&mut self, list: &DrawList) -> Result<FrameOutput, String> {
            self.frames.push(list.clone());
            self.error.take().map_or(Ok(FrameOutput::default()), Err)
        }
    }
    fn driver() -> Driver<FakeRenderer> {
        Driver {
            renderer: FakeRenderer {
                info: BackendInfo {
                    requested: "gl".into(),
                    backend: "OpenGl".into(),
                    adapter: "CPU-only driver fixture".into(),
                },
                frames: Vec::new(),
                error: None,
            },
            recording: false,
        }
    }

    #[test]
    fn physical_extent_is_not_divided_by_dpi_twice() {
        assert_eq!(checked_extent(1920., 1080., 2.).unwrap(), (1920, 1080, 2.));
        assert_eq!(
            checked_extent(1000., 750., 1.25).unwrap(),
            (1000, 750, 1.25)
        );
        for values in [
            (0., 1., 1.),
            (1., 0., 1.),
            (1., 1., 0.),
            (f32::NAN, 1., 1.),
            (1., 1., f32::INFINITY),
        ] {
            assert!(checked_extent(values.0, values.1, values.2).is_err());
        }
    }

    #[test]
    fn captures_submit_before_next_recording_and_final_frame_is_consumed() {
        let mut driver = driver();
        driver.start_frame(320, 180, 2.).unwrap();
        assert_eq!(facade::backend_info().unwrap(), driver.renderer.info);
        facade::capture_png(None, "before-await.png");
        driver.finish_frame().unwrap();
        assert!(facade::current_camera().is_err());
        assert!(
            matches!(driver.renderer.frames[0].commands.last(), Some(Command::Capture { path, .. }) if path.to_str() == Some("before-await.png"))
        );
        driver.start_frame(640, 360, 2.).unwrap();
        facade::capture_png(None, "final.png");
        driver.finish_frame().unwrap();
        assert_eq!(driver.renderer.frames.len(), 2);
        assert_eq!(driver.renderer.frames[1].width, 640);
        assert!(driver.finish_frame().is_err());
    }

    #[test]
    fn double_start_preserves_the_previous_recording() {
        let mut driver = driver();
        driver.start_frame(320, 180, 1.).unwrap();
        facade::capture_png(None, "retained.png");
        assert!(driver.start_frame(640, 360, 1.).is_err());
        driver.finish_frame().unwrap();
        assert_eq!(driver.renderer.frames.len(), 1);
        assert_eq!(driver.renderer.frames[0].width, 320);
    }

    #[test]
    fn capture_failures_return_to_the_application_loop() {
        let mut driver = driver();
        driver.renderer.error = Some("could not save capture final.png".into());
        driver.start_frame(320, 180, 1.).unwrap();
        facade::capture_png(None, "final.png");
        assert_eq!(
            driver.finish_frame().unwrap_err(),
            "could not save capture final.png"
        );
        assert!(facade::current_camera().is_err());
        assert_eq!(driver.renderer.frames.len(), 1);
    }
}
