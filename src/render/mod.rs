//! Provisional native wgpu backend for the shared CPU draw contract.
//! Simulation and animation never enter this module.
mod capture;
mod device;
mod frame;
mod lines;
mod mesh;
mod sprite2d;
mod target;
pub mod text;

use crate::draw::{
    BackendInfo, DrawList, FrameOutput, RenderTarget, Renderer, ResourceId, Sampler,
    TextDimensions, Texture,
};
pub use device::BackendSelection;
use std::{collections::HashMap, sync::Arc};

pub struct WgpuRenderer {
    gpu: device::Gpu,
    pipelines: mesh::Pipelines,
    main: Arc<target::GpuTexture>,
    white: Arc<target::GpuTexture>,
    textures: HashMap<ResourceId, Arc<target::GpuTexture>>,
    text: text::TextRenderer,
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
        let (pipelines, main, white, text) = result?;
        Ok(Self {
            gpu,
            pipelines,
            main,
            white,
            text,
            textures: HashMap::new(),
        })
    }
    fn texture(&mut self, descriptor: &Texture) -> Result<Arc<target::GpuTexture>, String> {
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
