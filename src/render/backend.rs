//! Native GPU implementation; CPU text stays available without this feature.
use super::{device, mesh, target, text, BackendSelection};
use crate::draw::{
    BackendInfo, DrawList, FrameOutput, RenderTarget, Renderer, ResourceId, Sampler,
    TextDimensions, Texture,
};
use std::{collections::HashMap, sync::Arc};

pub struct WgpuRenderer {
    pub(super) gpu: device::Gpu,
    pub(super) pipelines: mesh::Pipelines,
    pub(super) main: Arc<target::GpuTexture>,
    pub(super) white: Arc<target::GpuTexture>,
    textures: HashMap<ResourceId, Arc<target::GpuTexture>>,
    pub(super) text: text::TextRenderer,
    pub(super) prepared: Option<PreparedFrame>,
}
pub(super) struct PreparedFrame<T = wgpu::SurfaceTexture> {
    pub width: u32,
    pub height: u32,
    pub presentation: Option<T>,
}

/// Shared ownership gate: even a validation failure consumes the prepared
/// token, and a windowed submission can never acquire a replacement here.
pub(super) fn take_presentation<T>(
    prepared: &mut Option<PreparedFrame<T>>,
    windowed: bool,
    width: u32,
    height: u32,
) -> Result<Option<T>, String> {
    match prepared.take() {
        Some(frame) => {
            if frame.width != width || frame.height != height {
                return Err("draw-list extent differs from the prepared frame".into());
            }
            if windowed && frame.presentation.is_none() {
                return Err("prepared windowed frame has no surface texture".into());
            }
            Ok(frame.presentation)
        }
        None if windowed => Err("windowed submission requires prepare_frame first".into()),
        None => Ok(None),
    }
}

impl WgpuRenderer {
    /// `force_fallback` requests lavapipe/WARP explicitly; otherwise hardware is tried first.
    pub async fn new_headless(
        width: u32,
        height: u32,
        selection: BackendSelection,
        force_fallback: bool,
    ) -> Result<Self, String> {
        Self::new(width, height, selection, force_fallback, None).await
    }
    /// The surface owns an Arc clone, so the window cannot disappear while it is presented.
    pub async fn new_windowed(
        window: Arc<winit::window::Window>,
        selection: BackendSelection,
        force_fallback: bool,
    ) -> Result<Self, String> {
        let size = window.inner_size();
        Self::new(
            size.width.max(1),
            size.height.max(1),
            selection,
            force_fallback,
            Some(window),
        )
        .await
    }
    async fn new(
        width: u32,
        height: u32,
        selection: BackendSelection,
        force_fallback: bool,
        window: Option<Arc<winit::window::Window>>,
    ) -> Result<Self, String> {
        let gpu = device::Gpu::new(selection, force_fallback, window, width, height).await?;
        let error_scope = gpu.device.push_error_scope(wgpu::ErrorFilter::Validation);
        let result = (|| {
            let pipelines = mesh::Pipelines::new(&gpu.device);
            let main = Arc::new(target::GpuTexture::new(
                &gpu.device,
                &gpu.queue,
                &pipelines.texture_layout,
                &RenderTarget::new(width, height, true)?.texture,
            )?);
            let white = Arc::new(target::GpuTexture::new(
                &gpu.device,
                &gpu.queue,
                &pipelines.texture_layout,
                &Texture::rgba8(1, 1, &[255; 4], Sampler::default())?,
            )?);
            let text = text::TextRenderer::new()?;
            Ok::<_, String>((pipelines, main, white, text))
        })();
        if let Some(error) = error_scope.pop().await {
            return Err(format!("renderer initialization validation: {error}"));
        }
        gpu.check_errors()?;
        let (pipelines, main, white, text) = result?;
        Ok(Self {
            gpu,
            pipelines,
            main,
            white,
            text,
            textures: HashMap::new(),
            prepared: None,
        })
    }
    /// Acquire before input is consumed or the application future is polled.
    /// A timeout, occlusion, or minimized extent retains no frame and is safe to retry.
    /// A successful surface texture is consumed exactly once by `submit`.
    pub fn prepare_frame(&mut self, width: u32, height: u32) -> Result<bool, String> {
        if self.prepared.is_some() {
            return Err("prepare_frame called before submitting the previous frame".into());
        }
        if width == 0 || height == 0 {
            return Ok(false);
        }
        let limit = self.gpu.device.limits().max_texture_dimension_2d;
        if width > limit || height > limit {
            return Err("frame extent exceeds adapter limit".into());
        }
        self.gpu.resize(width, height)?;
        let presentation = if self.gpu.surface.is_some() {
            let Some(frame) = self.gpu.acquire()? else {
                return Ok(false);
            };
            Some(frame)
        } else {
            None
        };
        self.prepared = Some(PreparedFrame {
            width,
            height,
            presentation,
        });
        Ok(true)
    }

    pub(super) fn texture(
        &mut self,
        descriptor: &Texture,
    ) -> Result<Arc<target::GpuTexture>, String> {
        if let Some(texture) = self.textures.get(&descriptor.id) {
            if !texture.matches(descriptor) {
                return Err(format!(
                    "texture resource {:?} changed without a new identity",
                    descriptor.id
                ));
            }
            return Ok(texture.clone());
        }
        let texture = Arc::new(target::GpuTexture::new(
            &self.gpu.device,
            &self.gpu.queue,
            &self.pipelines.texture_layout,
            descriptor,
        )?);
        self.textures.insert(descriptor.id, texture.clone());
        Ok(texture)
    }
    /// Release an application-owned texture once the caller no longer needs its contents.
    /// Reusing a released render-target handle creates a fresh cleared target.
    pub fn release_texture(&mut self, id: ResourceId) {
        self.textures.remove(&id);
    }
}
impl Renderer for WgpuRenderer {
    fn info(&self) -> &BackendInfo {
        &self.gpu.info
    }
    fn submit(&mut self, list: &DrawList) -> Result<FrameOutput, String> {
        self.submit_frame(list)
    }
    fn measure_text(&self, text: &str, size: f32) -> Result<TextDimensions, String> {
        self::text::validate_size(size)?;
        Ok(self.text.measure_text(text, size))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn prepared_surface_is_consumed_once_without_reacquisition() {
        let mut prepared = Some(PreparedFrame {
            width: 640,
            height: 360,
            presentation: Some("the acquired surface"),
        });
        assert_eq!(
            take_presentation(&mut prepared, true, 640, 360).unwrap(),
            Some("the acquired surface")
        );
        assert!(prepared.is_none());
        assert!(take_presentation(&mut prepared, true, 640, 360).is_err());
    }

    #[test]
    fn extent_mismatch_drops_the_acquired_surface() {
        let mut prepared = Some(PreparedFrame {
            width: 640,
            height: 360,
            presentation: Some("the acquired surface"),
        });
        assert!(take_presentation(&mut prepared, true, 320, 180)
            .unwrap_err()
            .contains("extent"));
        assert!(prepared.is_none());
        assert!(take_presentation(&mut prepared, true, 640, 360).is_err());
    }

    #[test]
    fn windowed_submission_requires_an_actual_acquired_texture() {
        let mut prepared: Option<PreparedFrame<()>> = Some(PreparedFrame {
            width: 640,
            height: 360,
            presentation: None,
        });
        assert!(take_presentation(&mut prepared, true, 640, 360)
            .unwrap_err()
            .contains("surface texture"));
        assert!(prepared.is_none());
    }

    #[test]
    fn headless_submission_does_not_require_a_surface() {
        let mut prepared: Option<PreparedFrame<()>> = None;
        assert!(take_presentation(&mut prepared, false, 640, 360)
            .unwrap()
            .is_none());
        prepared = Some(PreparedFrame {
            width: 640,
            height: 360,
            presentation: None,
        });
        assert!(take_presentation(&mut prepared, false, 640, 360)
            .unwrap()
            .is_none());
        assert!(prepared.is_none());
    }
}
