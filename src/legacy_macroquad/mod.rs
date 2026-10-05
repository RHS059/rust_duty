//! Compatibility renderer for the provisional, backend-neutral draw contract.
//!
//! Construct and use this only on macroquad's render thread after its OpenGL
//! context exists. The renderer owns the material state while submitting a list;
//! each mesh restores the default material and balances its model-matrix push.
//! No simulation, lighting, animation, or clock work happens here.
//!
//! Known compatibility difference: miniquad 0.4.8's OpenGL apply_pipeline
//! enables depth testing only when depth_write is true. Consequently additive
//! meshes disable both depth testing and writes, as existing muzzle_fx does.
//! The wgpu backend can depth-test additive meshes without writing depth.

use crate::draw::{self, BlendMode, Command, Renderer, ResourceId, TextureSource};
use glam::Mat4;
use macroquad::{camera, material, miniquad as mq, models, texture, window};
use std::{collections::HashMap, path::Path};

// Below macroquad 0.4.14's default 10,000-vertex / 5,000-index capacities.
// Expand indexed triangles into bounded batches rather than letting its
// geometry() silently clamp a large skinned mesh or triangle soup.
const BATCH_INDICES: usize = 4_095;

const VERTEX_SHADER: &str = r#"#version 100
attribute vec3 position;
attribute vec2 texcoord;
attribute vec4 color0;
varying lowp vec2 uv;
varying lowp vec4 vertex_color;
uniform mat4 Model;
uniform mat4 Projection;
void main() {
    gl_Position = Projection * Model * vec4(position, 1.0);
    uv = texcoord;
    vertex_color = color0 / 255.0;
}
"#;
const FRAGMENT_SHADER: &str = r#"#version 100
varying lowp vec2 uv;
varying lowp vec4 vertex_color;
uniform sampler2D Texture;
void main() {
    gl_FragColor = texture2D(Texture, uv) * vertex_color;
}
"#;

struct CachedTexture {
    descriptor: draw::Texture,
    texture: texture::Texture2D,
    target: Option<texture::RenderTarget>,
}

/// GPU resources are created lazily and retained for the renderer's lifetime.
/// Cloned descriptors with the same ID share a resource. Changing a resource's
/// extent/source requires a new ID; changing its sampler is supported.
pub struct LegacyRenderer {
    info: draw::BackendInfo,
    textures: HashMap<ResourceId, CachedTexture>,
    materials: HashMap<(u8, bool), material::Material>,
}

impl LegacyRenderer {
    /// The compatibility path is OpenGL only, as selected by --renderer=gl.
    pub fn new(requested: impl Into<String>) -> Result<Self, String> {
        // SAFETY: the caller runs on macroquad's initialized render thread.
        let context_info = unsafe { window::get_internal_gl().quad_context.info() };
        if context_info.backend != mq::Backend::OpenGl {
            return Err("legacy renderer requires a macroquad OpenGL context".into());
        }
        Ok(Self {
            info: draw::BackendInfo {
                requested: requested.into(),
                backend: "OpenGl".into(),
                adapter: adapter_name(&context_info.gl_version_string),
            },
            textures: HashMap::new(),
            materials: HashMap::new(),
        })
    }

    /// Matches macroquad's default-font draw_text sizing, including truncation
    /// to its u16 font size. Requires the same initialized context as submit.
    pub fn measure_text(&self, text: &str, size: f32) -> Result<draw::TextDimensions, String> {
        validate_text_size(size)?;
        if text.is_empty() {
            return Ok(draw::TextDimensions::default());
        }
        let measured = macroquad::text::measure_text(text, None, size as u16, 1.0);
        Ok(draw::TextDimensions {
            width: measured.width,
            height: measured.height,
            offset_y: measured.offset_y,
        })
    }

    fn ensure_texture(&mut self, descriptor: &draw::Texture) -> Result<(), String> {
        validate_texture(descriptor)?;
        if let Some(cached) = self.textures.get_mut(&descriptor.id) {
            if !same_storage(&cached.descriptor, descriptor) {
                return Err(format!(
                    "texture {:?} changed storage without a new resource ID",
                    descriptor.id
                ));
            }
            if cached.descriptor.sampler != descriptor.sampler {
                // Samplers are mutable texture state in GL, unlike wgpu's
                // separate objects. Finish older draws before changing it.
                flush();
                set_sampler(&cached.texture, descriptor.sampler);
                cached.descriptor.sampler = descriptor.sampler;
            }
            return Ok(());
        }
        let (gpu_texture, target) = match &descriptor.source {
            TextureSource::Rgba8(bytes) => (
                texture::Texture2D::from_rgba8(
                    descriptor.width as u16,
                    descriptor.height as u16,
                    bytes,
                ),
                None,
            ),
            TextureSource::Target { depth } => {
                let target = texture::render_target_ex(
                    descriptor.width,
                    descriptor.height,
                    texture::RenderTargetParams {
                        // Zero selects miniquad's plain, non-resolving pass.
                        // macroquad 0.4.14 creates a resolve attachment even
                        // for sample_count=1, which requires newer GL APIs.
                        sample_count: 0,
                        depth: *depth,
                    },
                );
                (target.texture.clone(), Some(target))
            }
        };
        set_sampler(&gpu_texture, descriptor.sampler);
        self.textures.insert(
            descriptor.id,
            CachedTexture {
                descriptor: descriptor.clone(),
                texture: gpu_texture,
                target,
            },
        );
        Ok(())
    }

    fn texture(&mut self, descriptor: &draw::Texture) -> Result<texture::Texture2D, String> {
        self.ensure_texture(descriptor)?;
        Ok(self.textures[&descriptor.id].texture.clone())
    }

    fn target(&mut self, target: &draw::RenderTarget) -> Result<texture::RenderTarget, String> {
        self.ensure_texture(&target.texture)?;
        self.textures[&target.texture.id]
            .target
            .clone()
            .ok_or_else(|| "render target descriptor contains an ordinary RGBA texture".into())
    }

    fn material(&mut self, blend: BlendMode, depth: bool) -> Result<material::Material, String> {
        let key = (blend_key(blend), depth);
        if let Some(material) = self.materials.get(&key) {
            return Ok(material.clone());
        }
        let loaded = material::load_material(
            mq::ShaderSource::Glsl {
                vertex: VERTEX_SHADER,
                fragment: FRAGMENT_SHADER,
            },
            material::MaterialParams {
                pipeline_params: pipeline_params(blend, depth),
                ..Default::default()
            },
        )
        .map_err(|error| format!("legacy {blend:?} material failed: {error}"))?;
        self.materials.insert(key, loaded.clone());
        Ok(loaded)
    }

    fn execute(&mut self, list: &draw::DrawList) -> Result<draw::FrameOutput, String> {
        let mut output = draw::FrameOutput::default();
        let mut active = draw::Camera::screen(list.width, list.height);
        camera::set_camera(&LegacyCamera::new(&active, None));
        for (index, command) in list.commands.iter().enumerate() {
            self.execute_command(command, &mut active, &mut output)
                .map_err(|error| format!("legacy command {index}: {error}"))?;
        }
        Ok(output)
    }

    fn execute_command(
        &mut self,
        command: &Command,
        active: &mut draw::Camera,
        output: &mut draw::FrameOutput,
    ) -> Result<(), String> {
        match command {
            Command::Camera(next) => {
                if !next.view_projection.is_finite() {
                    return Err("non-finite camera matrix".into());
                }
                let target = next.target.as_ref().map(|t| self.target(t)).transpose()?;
                camera::set_camera(&LegacyCamera::new(next, target));
                *active = next.clone();
            }
            Command::Clear(color) => {
                // macroquad clear_background drops queued geometry. Submit it
                // first so previous captures/targets and command order survive.
                flush();
                window::clear_background(color_to_legacy(*color));
            }
            Command::Mesh { mesh, model, blend } => {
                mesh.validate()?;
                validate_model(*model)?;
                reject_feedback(mesh.texture.as_ref(), active)?;
                let texture = mesh.texture.as_ref().map(|t| self.texture(t)).transpose()?;
                let material = self.material(*blend, active.depth_test)?;
                material::gl_use_material(&material);
                with_model(*model, || {
                    for indices in mesh.indices.chunks(BATCH_INDICES) {
                        let batch = mesh_batch(mesh, indices, texture.clone());
                        models::draw_mesh(&batch);
                    }
                });
                material::gl_use_default_material();
            }
            Command::Lines { lines, model } => {
                validate_model(*model)?;
                if lines
                    .iter()
                    .any(|l| !l.start.is_finite() || !l.end.is_finite())
                {
                    return Err("non-finite line endpoint".into());
                }
                with_model(*model, || {
                    for line in lines {
                        models::draw_line_3d(line.start, line.end, color_to_legacy(line.color));
                    }
                });
            }
            Command::Rect { rect, color } => without_depth(|| {
                macroquad::shapes::draw_rectangle(
                    rect.x,
                    rect.y,
                    rect.w,
                    rect.h,
                    color_to_legacy(*color),
                );
            }),
            Command::Sprite {
                texture: descriptor,
                destination,
                tint,
            } => {
                reject_feedback(Some(descriptor), active)?;
                let texture = self.texture(descriptor)?;
                without_depth(|| {
                    texture::draw_texture_ex(
                        &texture,
                        destination.x,
                        destination.y,
                        color_to_legacy(*tint),
                        texture::DrawTextureParams {
                            dest_size: Some(glam::Vec2::new(destination.w, destination.h)),
                            // Camera matrices keep GL's convention. A target is
                            // sampled with a flip at this one backend boundary.
                            flip_y: matches!(descriptor.source, TextureSource::Target { .. }),
                            ..Default::default()
                        },
                    )
                });
            }
            Command::Text {
                text,
                baseline,
                size,
                color,
            } => {
                validate_text_size(*size)?;
                without_depth(|| {
                    macroquad::text::draw_text(
                        text,
                        baseline.x,
                        baseline.y,
                        *size,
                        color_to_legacy(*color),
                    );
                });
            }
            Command::Capture { target, path } => {
                let target = target.as_ref().map(|t| self.target(t)).transpose()?;
                flush();
                let image = match target {
                    Some(target) => target.texture.get_texture_data(),
                    None => texture::get_screen_data(),
                };
                save_capture(path, image.width, image.height, &image.bytes)?;
                output.captures.push(path.clone());
            }
        }
        Ok(())
    }
}

impl Renderer for LegacyRenderer {
    fn info(&self) -> &draw::BackendInfo {
        &self.info
    }

    fn measure_text(&self, text: &str, size: f32) -> Result<draw::TextDimensions, String> {
        LegacyRenderer::measure_text(self, text, size)
    }

    fn submit(&mut self, list: &draw::DrawList) -> Result<draw::FrameOutput, String> {
        if list.width == 0 || list.height == 0 {
            return Err("draw list extent must be nonzero".into());
        }
        camera::push_camera_state();
        // push_camera_state does not save viewport in macroquad 0.4.14.
        // SAFETY: used exclusively on macroquad's initialized render thread.
        let viewport = unsafe { window::get_internal_gl().quad_gl.get_viewport() };
        material::gl_use_default_material();
        let result = self.execute(list);
        material::gl_use_default_material();
        camera::pop_camera_state();
        // SAFETY: no reference to macroquad's context outlives this block.
        unsafe {
            let gl = window::get_internal_gl();
            gl.quad_gl.viewport(Some(viewport));
            gl.quad_gl.texture(None);
            gl.quad_gl
                .draw_mode(macroquad::prelude::DrawMode::Triangles);
        }
        result
    }
}

struct LegacyCamera {
    view_projection: Mat4,
    depth_test: bool,
    target: Option<texture::RenderTarget>,
}
impl LegacyCamera {
    fn new(camera: &draw::Camera, target: Option<texture::RenderTarget>) -> Self {
        Self {
            view_projection: camera.view_projection,
            depth_test: camera.depth_test,
            target,
        }
    }
}
impl camera::Camera for LegacyCamera {
    fn matrix(&self) -> Mat4 {
        self.view_projection
    }
    fn depth_enabled(&self) -> bool {
        self.depth_test
    }
    fn render_pass(&self) -> Option<texture::RenderPass> {
        self.target.as_ref().map(|t| t.render_pass.clone())
    }
    fn viewport(&self) -> Option<(i32, i32, i32, i32)> {
        None
    }
}

fn color_to_legacy(color: draw::Color) -> macroquad::color::Color {
    macroquad::color::Color::new(color.r, color.g, color.b, color.a)
}

fn adapter_name(version: &str) -> String {
    // GL_RENDERER is defined by OpenGL but not re-exported as a miniquad
    // constant. Query it only after verifying that the active backend is GL.
    const GL_RENDERER: u32 = 0x1F01;
    // SAFETY: OpenGL owns the NUL-terminated string for the active context's
    // lifetime; it is copied immediately. A failed query may return null.
    let renderer = unsafe {
        let ptr = mq::gl::glGetString(GL_RENDERER);
        if ptr.is_null() {
            None
        } else {
            Some(
                std::ffi::CStr::from_ptr(ptr.cast())
                    .to_string_lossy()
                    .into_owned(),
            )
        }
    };
    renderer.unwrap_or_else(|| format!("unknown OpenGL adapter ({version})"))
}

fn mesh_batch(
    mesh: &draw::Mesh,
    indices: &[u16],
    texture: Option<texture::Texture2D>,
) -> models::Mesh {
    let vertices =
        indices
            .iter()
            .map(|&index| {
                let vertex = mesh.vertices[index as usize];
                models::Vertex {
                    position: vertex.position,
                    uv: if mesh.texture.as_ref().is_some_and(|texture| {
                        matches!(texture.source, TextureSource::Target { .. })
                    }) {
                        glam::Vec2::new(vertex.uv.x, 1.0 - vertex.uv.y)
                    } else {
                        vertex.uv
                    },
                    color: vertex.color,
                    normal: vertex.normal,
                }
            })
            .collect();
    models::Mesh {
        vertices,
        indices: (0..indices.len() as u16).collect(),
        texture,
    }
}

fn blend_key(blend: BlendMode) -> u8 {
    match blend {
        BlendMode::Opaque => 0,
        BlendMode::Alpha => 1,
        BlendMode::Additive => 2,
    }
}

fn pipeline_params(blend: BlendMode, depth: bool) -> mq::PipelineParams {
    use mq::{BlendFactor as Factor, BlendState, BlendValue, Equation};
    mq::PipelineParams {
        depth_test: if depth {
            mq::Comparison::LessOrEqual
        } else {
            mq::Comparison::Always
        },
        // Legacy alpha meshes wrote depth; only additive flashes bypass it.
        depth_write: depth && blend != BlendMode::Additive,
        color_blend: match blend {
            BlendMode::Opaque => None,
            BlendMode::Alpha => Some(BlendState::new(
                Equation::Add,
                Factor::Value(BlendValue::SourceAlpha),
                Factor::OneMinusValue(BlendValue::SourceAlpha),
            )),
            BlendMode::Additive => Some(BlendState::new(
                Equation::Add,
                Factor::Value(BlendValue::SourceAlpha),
                Factor::One,
            )),
        },
        alpha_blend: (blend == BlendMode::Additive)
            .then(|| BlendState::new(Equation::Add, Factor::Zero, Factor::One)),
        ..Default::default()
    }
}

fn validate_model(model: Mat4) -> Result<(), String> {
    if model.is_finite() {
        Ok(())
    } else {
        Err("non-finite model matrix".into())
    }
}

fn validate_text_size(size: f32) -> Result<(), String> {
    if size.is_finite() && size >= 1.0 && size <= u16::MAX as f32 {
        Ok(())
    } else {
        Err("text size must be finite and between 1 and 65535".into())
    }
}

fn validate_texture(texture: &draw::Texture) -> Result<(), String> {
    if texture.width == 0
        || texture.height == 0
        || texture.width > u16::MAX as u32
        || texture.height > u16::MAX as u32
    {
        return Err("legacy texture dimensions must be between 1 and 65535".into());
    }
    if let TextureSource::Rgba8(bytes) = &texture.source {
        let expected = u64::from(texture.width) * u64::from(texture.height) * 4;
        if bytes.len() as u64 != expected {
            return Err("texture extent does not match RGBA8 data".into());
        }
    }
    Ok(())
}

fn same_storage(a: &draw::Texture, b: &draw::Texture) -> bool {
    a.width == b.width
        && a.height == b.height
        && match (&a.source, &b.source) {
            (TextureSource::Rgba8(a), TextureSource::Rgba8(b)) => a == b,
            (TextureSource::Target { depth: a }, TextureSource::Target { depth: b }) => a == b,
            _ => false,
        }
}

fn reject_feedback(texture: Option<&draw::Texture>, camera: &draw::Camera) -> Result<(), String> {
    if texture
        .zip(camera.target.as_ref())
        .is_some_and(|(texture, target)| texture.id == target.texture.id)
    {
        Err("cannot sample the active render target".into())
    } else {
        Ok(())
    }
}

fn set_sampler(texture: &texture::Texture2D, sampler: draw::Sampler) {
    texture.set_filter(match sampler.filter {
        draw::FilterMode::Nearest => mq::FilterMode::Nearest,
        draw::FilterMode::Linear => mq::FilterMode::Linear,
    });
    let wrap = |mode| match mode {
        draw::WrapMode::Clamp => mq::TextureWrap::Clamp,
        draw::WrapMode::Repeat => mq::TextureWrap::Repeat,
    };
    // SAFETY: a short, exclusive access on the initialized rendering thread.
    unsafe {
        window::get_internal_gl().quad_context.texture_set_wrap(
            texture.raw_miniquad_id(),
            wrap(sampler.wrap_x),
            wrap(sampler.wrap_y),
        );
    }
}

fn flush() {
    // SAFETY: all calls originate in an initialized renderer on its thread.
    unsafe {
        window::get_internal_gl().flush();
    }
}

fn without_depth(draw: impl FnOnce()) {
    // SAFETY: a short exclusive render-thread access; geometry snapshots the
    // selected default pipeline, so restoring depth does not affect the batch.
    let depth = unsafe {
        let gl = window::get_internal_gl();
        let depth = gl.quad_gl.is_depth_test_enabled();
        gl.quad_gl.depth_test(false);
        depth
    };
    draw();
    // SAFETY: restores the previously active camera's depth setting.
    unsafe {
        window::get_internal_gl().quad_gl.depth_test(depth);
    }
}

fn with_model(model: Mat4, draw: impl FnOnce()) {
    // SAFETY: no context borrow is retained while invoking macroquad draws.
    unsafe {
        window::get_internal_gl().quad_gl.push_model_matrix(model);
    }
    draw();
    // SAFETY: balances the push on the same render thread.
    unsafe {
        window::get_internal_gl().quad_gl.pop_model_matrix();
    }
}

fn save_capture(path: &Path, width: u16, height: u16, bottom_up: &[u8]) -> Result<(), String> {
    let pixels = top_left_pixels(width, height, bottom_up)?;
    // Image::export_png panics on I/O failure; expose the real error instead.
    image::save_buffer_with_format(
        path,
        &pixels,
        u32::from(width),
        u32::from(height),
        image::ColorType::Rgba8,
        image::ImageFormat::Png,
    )
    .map_err(|error| format!("could not save capture {}: {error}", path.display()))
}

fn top_left_pixels(width: u16, height: u16, bottom_up: &[u8]) -> Result<Vec<u8>, String> {
    let stride = usize::from(width) * 4;
    if width == 0 || height == 0 || bottom_up.len() != stride * usize::from(height) {
        return Err("capture dimensions do not match RGBA8 readback".into());
    }
    let mut pixels = Vec::with_capacity(bottom_up.len());
    for row in bottom_up.chunks_exact(stride).rev() {
        pixels.extend_from_slice(row);
    }
    Ok(pixels)
}

#[cfg(test)]
mod tests {
    use super::*;
    use glam::{Vec2, Vec3, Vec4};

    #[test]
    fn additive_preserves_alpha_without_depth_writes() {
        use mq::{BlendFactor as F, BlendState, BlendValue, Equation};
        let pipeline = pipeline_params(BlendMode::Additive, true);
        assert_eq!(pipeline.depth_test, mq::Comparison::LessOrEqual);
        assert!(!pipeline.depth_write);
        assert_eq!(
            pipeline.color_blend,
            Some(BlendState::new(
                Equation::Add,
                F::Value(BlendValue::SourceAlpha),
                F::One,
            ))
        );
        assert_eq!(
            pipeline.alpha_blend,
            Some(BlendState::new(Equation::Add, F::Zero, F::One))
        );
        assert!(pipeline_params(BlendMode::Opaque, true).depth_write);
        assert!(pipeline_params(BlendMode::Alpha, true).depth_write);
        assert!(!pipeline_params(BlendMode::Alpha, false).depth_write);
        assert!(pipeline_params(BlendMode::Opaque, true)
            .color_blend
            .is_none());
    }

    #[test]
    fn large_mesh_copies_every_index_and_vertex_field() {
        let vertex = draw::Vertex {
            position: Vec3::new(1., 2., 3.),
            uv: Vec2::new(0.25, 0.75),
            color: [10, 20, 30, 40],
            normal: Vec4::new(4., 5., 6., 7.),
        };
        let mesh = draw::Mesh {
            vertices: vec![vertex],
            indices: vec![0; 12_000],
            texture: None,
        };
        let mut count = 0;
        for chunk in mesh.indices.chunks(BATCH_INDICES) {
            let batch = mesh_batch(&mesh, chunk, None);
            assert!(batch.vertices.len() < 5_000);
            assert_eq!(batch.indices.len() % 3, 0);
            for (index, copied) in batch.vertices.iter().enumerate() {
                assert_eq!(copied.position, vertex.position);
                assert_eq!(copied.uv, vertex.uv);
                assert_eq!(copied.color, vertex.color);
                assert_eq!(copied.normal, vertex.normal);
                assert_eq!(batch.indices[index] as usize, index);
            }
            count += batch.indices.len();
        }
        assert_eq!(count, 12_000);
    }

    #[test]
    fn camera_keeps_supplied_projection_without_depth_remap() {
        use macroquad::camera::Camera as _;
        let projection = Mat4::perspective_rh_gl(1., 1.5, 0.1, 50.);
        let camera = LegacyCamera::new(
            &draw::Camera {
                view_projection: projection,
                target: None,
                depth_test: true,
            },
            None,
        );
        assert_eq!(camera.matrix(), projection);
        assert!(camera.depth_enabled());
        assert!(camera.render_pass().is_none());
    }

    #[test]
    fn target_sampling_flips_gpu_uv_without_changing_cpu_mesh() {
        let target = draw::RenderTarget::new(2, 2, false).unwrap();
        let mesh = draw::Mesh {
            vertices: vec![draw::Vertex::new2(
                Vec3::ZERO,
                Vec2::new(0.25, 0.75),
                draw::Color::WHITE,
            )],
            indices: vec![0, 0, 0],
            texture: Some(target.texture),
        };
        let batch = mesh_batch(&mesh, &mesh.indices, None);
        assert_eq!(batch.vertices[0].uv, Vec2::new(0.25, 0.25));
        assert_eq!(mesh.vertices[0].uv, Vec2::new(0.25, 0.75));
    }

    #[test]
    fn capture_rows_are_top_left_and_malformed_readback_fails() {
        let bottom_up = [
            0, 0, 255, 255, 255, 255, 255, 255, 255, 0, 0, 255, 0, 255, 0, 255,
        ];
        assert_eq!(
            top_left_pixels(2, 2, &bottom_up).unwrap(),
            [255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 255, 255, 255, 255]
        );
        assert!(top_left_pixels(2, 2, &bottom_up[..15]).is_err());
        assert!(top_left_pixels(0, 2, &[]).is_err());
    }

    #[test]
    fn storage_identity_and_feedback_are_checked() {
        let target = draw::RenderTarget::new(32, 32, true).unwrap();
        let mut camera = draw::Camera::screen(32, 32);
        camera.target = Some(target.clone());
        assert!(reject_feedback(Some(&target.texture), &camera).is_err());
        assert!(reject_feedback(None, &camera).is_ok());
        let mut changed = target.texture.clone();
        changed.width = 64;
        assert!(!same_storage(&changed, &target.texture));
        changed = target.texture.clone();
        changed.sampler.wrap_x = draw::WrapMode::Repeat;
        assert!(same_storage(&changed, &target.texture));
    }

    #[test]
    fn invalid_texture_and_text_inputs_fail_before_graphics_calls() {
        let mut target = draw::RenderTarget::new(32, 32, true).unwrap();
        target.texture.width = 65_536;
        assert!(validate_texture(&target.texture).is_err());
        for size in [f32::NAN, f32::INFINITY, -1., 0., 65_536.] {
            assert!(validate_text_size(size).is_err());
        }
        assert!(validate_text_size(18.5).is_ok());
    }

    #[test]
    fn png_write_errors_are_returned() {
        // A file cannot have children on supported native filesystems.
        let path =
            std::env::temp_dir().join(format!("rust-duty-capture-test-{}", std::process::id()));
        std::fs::write(&path, b"not a directory").unwrap();
        let result = save_capture(&path.join("capture.png"), 1, 1, &[0, 0, 0, 255]);
        std::fs::remove_file(path).unwrap();
        assert!(result.unwrap_err().contains("could not save capture"));
    }

    #[test]
    fn png_roundtrip_preserves_top_left_pixel_order() {
        let path = std::env::temp_dir().join(format!(
            "rust-duty-png-roundtrip-{}.png",
            std::process::id()
        ));
        let bottom_up = [
            0, 0, 255, 255, 255, 255, 255, 255, 255, 0, 0, 255, 0, 255, 0, 255,
        ];
        save_capture(&path, 2, 2, &bottom_up).unwrap();
        let decoded = image::open(&path).unwrap().to_rgba8();
        std::fs::remove_file(path).unwrap();
        assert_eq!(decoded.dimensions(), (2, 2));
        assert_eq!(decoded.get_pixel(0, 0).0, [255, 0, 0, 255]);
        assert_eq!(decoded.get_pixel(1, 0).0, [0, 255, 0, 255]);
        assert_eq!(decoded.get_pixel(0, 1).0, [0, 0, 255, 255]);
        assert_eq!(decoded.get_pixel(1, 1).0, [255, 255, 255, 255]);
    }
}
