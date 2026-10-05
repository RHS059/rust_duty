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
//!
//! Target RGB stores associated radiance plus emission, with coverage alpha.
//! Alpha coverage now uses source-over instead of the old macroquad default's
//! alpha squaring. Fractional-alpha pixels are intentionally corrected; this is
//! not historical pixel parity. Explicit target PNGs are raw diagnostic dumps,
//! while default framebuffer PNGs preserve display RGB with opaque alpha.

pub mod runtime;

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
precision mediump float;
varying lowp vec2 uv;
varying lowp vec4 vertex_color;
uniform sampler2D Texture;
void main() {
    gl_FragColor = texture2D(Texture, uv) * vertex_color;
}
"#;

const ASSOCIATED_FRAGMENT_SHADER: &str = r#"#version 100
precision mediump float;
varying lowp vec2 uv;
varying lowp vec4 vertex_color;
uniform sampler2D Texture;
void main() {
    vec4 sampled = texture2D(Texture, uv);
    gl_FragColor = vec4(sampled.rgb * vertex_color.rgb * vertex_color.a,
                       sampled.a * vertex_color.a);
}
"#;
const REPLACE_STRAIGHT_FRAGMENT_SHADER: &str = r#"#version 100
precision mediump float;
varying lowp vec2 uv;
varying lowp vec4 vertex_color;
uniform sampler2D Texture;
void main() {
    vec4 straight = texture2D(Texture, uv) * vertex_color;
    gl_FragColor = vec4(straight.rgb * straight.a, straight.a);
}
"#;

fn fragment_shader(blend: BlendMode, associated: bool) -> &'static str {
    if associated {
        ASSOCIATED_FRAGMENT_SHADER
    } else if blend == BlendMode::Opaque {
        REPLACE_STRAIGHT_FRAGMENT_SHADER
    } else {
        FRAGMENT_SHADER
    }
}

struct CachedTexture {
    descriptor: draw::Texture,
    texture: texture::Texture2D,
    target: Option<texture::RenderTarget>,
}

/// GPU resources are created lazily and retained for the renderer's lifetime.
/// Cloned descriptors with the same ID share a resource. Changing a resource's
/// extent, source, or sampler requires a new ID, matching the provisional
/// immutable-descriptor contract used by wgpu.
pub struct LegacyRenderer {
    info: draw::BackendInfo,
    textures: HashMap<ResourceId, CachedTexture>,
    materials: HashMap<(u8, bool, bool, bool), material::Material>,
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
        if let Some(cached) = self.textures.get(&descriptor.id) {
            // Reject changed descriptors before touching GL state or pending
            // draws. The shared resource identity is immutable even though GL
            // itself permits changing a texture's sampler in place.
            return validate_cached_texture(&cached.descriptor, descriptor);
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

    fn material(
        &mut self,
        blend: BlendMode,
        depth: bool,
        associated: bool,
        lines: bool,
    ) -> Result<material::Material, String> {
        let key = (blend_key(blend), depth, associated, lines);
        if let Some(material) = self.materials.get(&key) {
            return Ok(material.clone());
        }
        let loaded = material::load_material(
            mq::ShaderSource::Glsl {
                vertex: VERTEX_SHADER,
                fragment: fragment_shader(blend, associated),
            },
            material::MaterialParams {
                pipeline_params: pipeline_params(blend, depth, associated, lines),
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
            self.execute_command(command, &mut active, (list.width, list.height), &mut output)
                .map_err(|error| format!("legacy command {index}: {error}"))?;
        }
        Ok(output)
    }

    fn execute_command(
        &mut self,
        command: &Command,
        active: &mut draw::Camera,
        extent: (u32, u32),
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
                window::clear_background(associated_clear(*color));
            }
            Command::Mesh { mesh, model, blend } => {
                mesh.validate()?;
                validate_model(*model)?;
                reject_feedback(mesh.texture.as_ref(), active)?;
                let texture = mesh.texture.as_ref().map(|t| self.texture(t)).transpose()?;
                let associated = mesh
                    .texture
                    .as_ref()
                    .is_some_and(|texture| matches!(texture.source, TextureSource::Target { .. }));
                let material = self.material(*blend, active.depth_test, associated, false)?;
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
                let material = self.material(BlendMode::Alpha, active.depth_test, false, true)?;
                material::gl_use_material(&material);
                with_model(*model, || {
                    for line in lines {
                        models::draw_line_3d(line.start, line.end, color_to_legacy(line.color));
                    }
                });
                material::gl_use_default_material();
            }
            Command::Rect { rect, color } => {
                self.with_screen_camera(active, extent, false, || {
                    macroquad::shapes::draw_rectangle(
                        rect.x,
                        rect.y,
                        rect.w,
                        rect.h,
                        color_to_legacy(*color),
                    );
                })?
            }
            Command::Sprite {
                texture: descriptor,
                destination,
                tint,
            } => {
                reject_feedback(Some(descriptor), active)?;
                let texture = self.texture(descriptor)?;
                self.with_screen_camera(
                    active,
                    extent,
                    matches!(descriptor.source, TextureSource::Target { .. }),
                    || {
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
                    },
                )?;
            }
            Command::Text {
                text,
                baseline,
                size,
                color,
            } => {
                prepare_default_text(text, *size)?;
                self.with_screen_camera(active, extent, false, || {
                    macroquad::text::draw_text(
                        text,
                        baseline.x,
                        baseline.y,
                        *size,
                        color_to_legacy(*color),
                    );
                })?;
            }
            Command::Capture { target, path } => {
                let diagnostic = target.is_some();
                let target = target.as_ref().map(|t| self.target(t)).transpose()?;
                flush();
                let image = match target {
                    Some(target) => target.texture.get_texture_data(),
                    None => texture::get_screen_data(),
                };
                save_capture(path, image.width, image.height, &image.bytes, diagnostic)?;
                output.captures.push(path.clone());
            }
        }
        Ok(())
    }

    fn with_screen_camera(
        &mut self,
        active: &draw::Camera,
        extent: (u32, u32),
        associated: bool,
        draw: impl FnOnce(),
    ) -> Result<(), String> {
        let screen = screen_camera(active, extent);
        let target = active.target.as_ref().map(|t| self.target(t)).transpose()?;
        // set_camera flushes pending geometry with its old projection before
        // changing projection, render pass, depth, and viewport. Do it on both
        // boundaries: a depth toggle alone leaves HUD pixels in world space.
        let material = self.material(BlendMode::Alpha, false, associated, false)?;
        camera::set_camera(&LegacyCamera::new(&screen, target.clone()));
        material::gl_use_material(&material);
        draw();
        material::gl_use_default_material();
        // Every renderer-owned camera uses the full-target viewport (None).
        // Restore through set_camera, not get_viewport(): macroquad resolves
        // None to WINDOW dimensions, which is wrong on a smaller target.
        camera::set_camera(&LegacyCamera::new(active, target));
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

fn associated_clear(color: draw::Color) -> macroquad::color::Color {
    let alpha = color.a.clamp(0., 1.);
    macroquad::color::Color::new(
        color.r.clamp(0., 1.) * alpha,
        color.g.clamp(0., 1.) * alpha,
        color.b.clamp(0., 1.) * alpha,
        alpha,
    )
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

fn pipeline_params(
    blend: BlendMode,
    depth: bool,
    associated: bool,
    lines: bool,
) -> mq::PipelineParams {
    use mq::{BlendFactor as Factor, BlendState, BlendValue, Equation};
    let source_color = if associated {
        Factor::One
    } else {
        Factor::Value(BlendValue::SourceAlpha)
    };
    mq::PipelineParams {
        primitive_type: if lines {
            mq::PrimitiveType::Lines
        } else {
            mq::PrimitiveType::Triangles
        },
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
                source_color,
                Factor::OneMinusValue(BlendValue::SourceAlpha),
            )),
            BlendMode::Additive => Some(BlendState::new(Equation::Add, source_color, Factor::One)),
        },
        alpha_blend: match blend {
            BlendMode::Opaque => None,
            BlendMode::Alpha => Some(BlendState::new(
                Equation::Add,
                Factor::One,
                Factor::OneMinusValue(BlendValue::SourceAlpha),
            )),
            BlendMode::Additive => Some(BlendState::new(Equation::Add, Factor::Zero, Factor::One)),
        },
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

fn validate_cached_texture(
    cached: &draw::Texture,
    requested: &draw::Texture,
) -> Result<(), String> {
    if same_descriptor(cached, requested) {
        Ok(())
    } else {
        Err(format!(
            "texture {:?} changed without a new resource ID",
            requested.id
        ))
    }
}

fn same_descriptor(a: &draw::Texture, b: &draw::Texture) -> bool {
    a.width == b.width
        && a.height == b.height
        && a.sampler == b.sampler
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

/// Protect Macroquad 0.4.14's shared glyph atlas before it can grow/upload.
/// Its atlas repacks glyphs and replaces the texture; Miniquad 0.4.8's GL
/// delete_texture does not invalidate cached bindings. Flushing alone leaves
/// that cache intact. The public GL commit_frame hook clears buffer/texture
/// bindings in this pinned version; it neither swaps buffers nor presents.
/// Do not extend this mid-frame workaround to another backend/version without
/// checking that implementation. All font sizing, rasterization and drawing
/// remain Macroquad's original default-font path.
fn prepare_default_text(text: &str, size: f32) -> Result<(), String> {
    prepare_default_text_with(
        text,
        size,
        flush,
        || {
            // SAFETY: the same initialized render thread and short exclusive
            // context access used by flush; no reference survives this block.
            unsafe {
                let gl = window::get_internal_gl();
                if gl.quad_context.info().backend != mq::Backend::OpenGl {
                    return Err("legacy text cache preparation requires OpenGL".into());
                }
                gl.quad_context.commit_frame();
            }
            Ok(())
        },
        |text, font_size| {
            // Native Macroquad measurement populates its actual glyph atlas.
            // The facade's CPU-only measurement would not prepare that atlas.
            // This is the same u16 truncation and scale used by draw_text;
            // Macroquad applies its own existing DPI adjustment in both paths.
            macroquad::text::measure_text(text, None, font_size, 1.0);
        },
    )
}

fn prepare_default_text_with(
    text: &str,
    size: f32,
    flush_pending: impl FnOnce(),
    invalidate_bindings: impl FnOnce() -> Result<(), String>,
    prewarm: impl FnOnce(&str, u16),
) -> Result<(), String> {
    validate_text_size(size)?;
    if text.is_empty() {
        return Ok(());
    }
    // Drain old-UV draws, invalidate both backend/cache bindings, then cache
    // the entire string before draw_text can queue any new glyph geometry.
    flush_pending();
    invalidate_bindings()?;
    prewarm(text, size as u16);
    Ok(())
}

fn screen_camera(active: &draw::Camera, extent: (u32, u32)) -> draw::Camera {
    let (width, height) = active.target.as_ref().map_or(extent, |target| {
        (target.texture.width, target.texture.height)
    });
    draw::Camera {
        target: active.target.clone(),
        ..draw::Camera::screen(width, height)
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

fn save_capture(
    path: &Path,
    width: u16,
    height: u16,
    bottom_up: &[u8],
    diagnostic: bool,
) -> Result<(), String> {
    let pixels = capture_pixels(width, height, bottom_up, diagnostic)?;
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

fn capture_pixels(
    width: u16,
    height: u16,
    bottom_up: &[u8],
    diagnostic: bool,
) -> Result<Vec<u8>, String> {
    let mut pixels = top_left_pixels(width, height, bottom_up)?;
    if !diagnostic {
        for pixel in pixels.as_chunks_mut::<4>().0 {
            pixel[3] = 255;
        }
    }
    Ok(pixels)
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
        let pipeline = pipeline_params(BlendMode::Additive, true, false, false);
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
        assert!(pipeline_params(BlendMode::Opaque, true, false, false).depth_write);
        assert!(pipeline_params(BlendMode::Alpha, true, false, false).depth_write);
        assert!(!pipeline_params(BlendMode::Alpha, false, false, false).depth_write);
        assert!(pipeline_params(BlendMode::Opaque, true, false, false)
            .color_blend
            .is_none());
    }

    fn blend_pixel(
        pipeline: mq::PipelineParams,
        source: [f32; 4],
        destination: [f32; 4],
    ) -> [f32; 4] {
        use mq::{BlendFactor as F, BlendState, BlendValue, Equation};
        let factors = [
            (F::Zero, 0.),
            (F::One, 1.),
            (F::Value(BlendValue::SourceAlpha), source[3]),
            (F::OneMinusValue(BlendValue::SourceAlpha), 1. - source[3]),
        ];
        // Miniquad's BlendState fields are private. Match its actual value to
        // supported factors rather than reimplementing our mode selection.
        let apply = |state: Option<BlendState>, component: usize| {
            let Some(state) = state else {
                return source[component];
            };
            for (src_factor, src_value) in factors {
                for (dst_factor, dst_value) in factors {
                    if state == BlendState::new(Equation::Add, src_factor, dst_factor) {
                        return source[component] * src_value + destination[component] * dst_value;
                    }
                }
            }
            panic!("unhandled legacy blend state: {state:?}");
        };
        std::array::from_fn(|i| {
            apply(
                if i == 3 {
                    // This fallback is how pinned miniquad behaves; removing the
                    // separate Alpha state must expose the old alpha-squared defect.
                    pipeline.alpha_blend.or(pipeline.color_blend)
                } else {
                    pipeline.color_blend
                },
                i,
            )
        })
    }

    #[test]
    fn alpha_coverage_is_source_over_for_mesh_hud_and_line_materials() {
        for depth in [false, true] {
            for lines in [false, true] {
                let straight = pipeline_params(BlendMode::Alpha, depth, false, lines);
                let stored = blend_pixel(straight, [1., 1., 1., 0.5], [0.; 4]);
                assert_eq!(stored, [0.5; 4]);
                assert_eq!(
                    straight.primitive_type,
                    if lines {
                        mq::PrimitiveType::Lines
                    } else {
                        mq::PrimitiveType::Triangles
                    }
                );
                let target = pipeline_params(BlendMode::Alpha, depth, true, lines);
                assert_eq!(
                    blend_pixel(target, stored, [0., 0., 0., 1.]),
                    [0.5, 0.5, 0.5, 1.]
                );
                assert_eq!(
                    blend_pixel(target, stored, [0.25, 0.5, 0.75, 1.]),
                    [0.625, 0.75, 0.875, 1.]
                );
            }
        }
    }

    #[test]
    fn all_legacy_fragment_variants_declare_float_precision() {
        // GLSL ES 1.00 has no default fragment float precision. Native Mesa
        // compilation rejected the associated target shader's local vec4.
        // This source guard covers every selected variant; native CI still
        // owns compilation and rendering proof.
        for blend in [BlendMode::Opaque, BlendMode::Alpha, BlendMode::Additive] {
            for associated in [false, true] {
                let shader = fragment_shader(blend, associated);
                assert!(shader.starts_with("#version 100\nprecision mediump float;\n"));
            }
        }
    }

    #[test]
    fn associated_target_material_retains_zero_alpha_emission() {
        let stored = blend_pixel(
            pipeline_params(BlendMode::Additive, false, false, false),
            [1., 0., 0., 0.5],
            [0.; 4],
        );
        assert_eq!(stored, [0.5, 0., 0., 0.]);
        for blend in [BlendMode::Alpha, BlendMode::Additive] {
            assert_eq!(
                blend_pixel(
                    pipeline_params(blend, false, true, false),
                    stored,
                    [0., 0., 0., 1.]
                ),
                [0.5, 0., 0., 1.]
            );
            assert_eq!(fragment_shader(blend, true), ASSOCIATED_FRAGMENT_SHADER);
            assert_eq!(fragment_shader(blend, false), FRAGMENT_SHADER);
        }
        assert_eq!(
            fragment_shader(BlendMode::Opaque, false),
            REPLACE_STRAIGHT_FRAGMENT_SHADER
        );
        assert_eq!(
            fragment_shader(BlendMode::Opaque, true),
            ASSOCIATED_FRAGMENT_SHADER
        );
    }

    #[test]
    fn legacy_clear_and_capture_obey_associated_target_contract() {
        let clear = associated_clear(draw::Color::new(1., 0.5, 0.25, 0.5));
        assert_eq!(
            [clear.r, clear.g, clear.b, clear.a],
            [0.5, 0.25, 0.125, 0.5]
        );
        let clear = associated_clear(draw::Color::new(1., 0., 0., 0.));
        assert_eq!([clear.r, clear.g, clear.b, clear.a], [0.; 4]);
        let original = [128, 128, 128, 128, 200, 25, 0, 0, 240, 20, 10, 64];
        assert_eq!(capture_pixels(3, 1, &original, true).unwrap(), original);
        assert_eq!(
            capture_pixels(3, 1, &original, false).unwrap(),
            [128, 128, 128, 255, 200, 25, 0, 255, 240, 20, 10, 255]
        );
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

    fn identity_camera(target: Option<draw::RenderTarget>) -> draw::Camera {
        draw::Camera {
            view_projection: Mat4::IDENTITY,
            target,
            depth_test: true,
        }
    }

    fn assert_projected(camera: &draw::Camera, point: Vec3, expected: Vec3) {
        let actual = camera.view_projection.project_point3(point);
        assert!(
            actual.abs_diff_eq(expected, 0.000_001),
            "{actual:?} != {expected:?}"
        );
    }

    #[test]
    fn hud_pixels_override_identity_3d_projection() {
        let active = identity_camera(None);
        let screen = screen_camera(&active, (320, 180));
        let point = Vec3::new(80., 45., 0.);
        assert_projected(&screen, point, Vec3::new(-0.5, 0.5, 0.));
        assert_ne!(
            active.view_projection.project_point3(point),
            Vec3::new(-0.5, 0.5, 0.)
        );
    }

    #[test]
    fn hud_pixels_override_perspective_projection() {
        let active = draw::Camera {
            view_projection: Mat4::perspective_rh_gl(1., 2., 0.1, 100.)
                * Mat4::look_at_rh(Vec3::new(3., 2., 5.), Vec3::ZERO, Vec3::Y),
            ..identity_camera(None)
        };
        let screen = screen_camera(&active, (400, 200));
        assert_projected(&screen, Vec3::new(200., 100., 0.), Vec3::ZERO);
        assert_ne!(screen.view_projection, active.view_projection);
    }

    #[test]
    fn hud_default_target_uses_current_draw_list_extent() {
        // A previous screen camera may still encode a different window size.
        let active = draw::Camera::screen(320, 180);
        let screen = screen_camera(&active, (128, 64));
        assert_projected(&screen, Vec3::new(128., 64., 0.), Vec3::new(1., -1., 0.));
        assert!(screen.target.is_none());
    }

    #[test]
    fn hud_offscreen_target_overrides_larger_draw_list_extent() {
        let target = draw::RenderTarget::new(64, 32, true).unwrap();
        let active = identity_camera(Some(target));
        let screen = screen_camera(&active, (640, 480));
        assert_projected(&screen, Vec3::new(16., 8., 0.), Vec3::new(-0.5, 0.5, 0.));
        assert_projected(&screen, Vec3::new(64., 32., 0.), Vec3::new(1., -1., 0.));
    }

    #[test]
    fn hud_non_square_odd_target_keeps_top_left_pixel_convention() {
        let active = identity_camera(Some(draw::RenderTarget::new(37, 19, false).unwrap()));
        let screen = screen_camera(&active, (128, 128));
        assert_projected(&screen, Vec3::ZERO, Vec3::new(-1., 1., 0.));
        assert_projected(&screen, Vec3::new(37., 19., 0.), Vec3::new(1., -1., 0.));
        assert_projected(&screen, Vec3::new(18.5, 9.5, 0.), Vec3::ZERO);
    }

    #[test]
    fn hud_disables_depth_regardless_of_active_camera_depth() {
        for depth_test in [false, true] {
            let active = draw::Camera {
                depth_test,
                ..identity_camera(None)
            };
            assert!(!screen_camera(&active, (128, 64)).depth_test);
            assert_eq!(active.depth_test, depth_test);
        }
    }

    #[test]
    fn hud_keeps_target_identity_and_does_not_mutate_active_camera() {
        let active = identity_camera(Some(draw::RenderTarget::new(32, 16, true).unwrap()));
        let original = active.clone();
        let screen = screen_camera(&active, (128, 64));
        let screen_target = &screen.target.as_ref().unwrap().texture;
        let active_target = &active.target.as_ref().unwrap().texture;
        assert_eq!(screen_target.id, active_target.id);
        assert!(same_descriptor(screen_target, active_target));
        assert_eq!(active.view_projection, original.view_projection);
        assert_eq!(active.depth_test, original.depth_test);
        assert!(same_descriptor(
            active_target,
            &original.target.unwrap().texture
        ));
    }

    #[test]
    fn hud_camera_preserves_feedback_rejection() {
        let target = draw::RenderTarget::new(32, 16, true).unwrap();
        let active = identity_camera(Some(target.clone()));
        let screen = screen_camera(&active, (128, 64));
        assert!(reject_feedback(Some(&target.texture), &screen).is_err());
    }

    #[test]
    fn scoped_camera_restore_retains_full_target_viewport_semantics() {
        use macroquad::camera::Camera as _;
        let active = identity_camera(Some(draw::RenderTarget::new(64, 32, true).unwrap()));
        let screen = LegacyCamera::new(&screen_camera(&active, (128, 128)), None);
        let restored = LegacyCamera::new(&active, None);
        // The renderer must restore None rather than macroquad's resolved
        // window-sized get_viewport(), which would clip/stretch a 64x32 pass.
        assert_eq!(screen.viewport(), None);
        assert_eq!(restored.viewport(), None);
        assert_eq!(restored.matrix(), Mat4::IDENTITY);
        assert!(restored.depth_enabled());
        assert!(!screen.depth_enabled());
    }

    fn rgba_texture() -> draw::Texture {
        draw::Texture::rgba8(
            2,
            1,
            &[255, 0, 0, 255, 0, 255, 0, 255],
            draw::Sampler::default(),
        )
        .unwrap()
    }

    #[test]
    fn immutable_descriptor_accepts_clones_and_equal_rgba_data() {
        let original = rgba_texture();
        assert!(validate_cached_texture(&original, &original.clone()).is_ok());
        let mut equal = rgba_texture();
        equal.id = original.id;
        assert!(validate_cached_texture(&original, &equal).is_ok());
    }

    #[test]
    fn immutable_descriptor_rejects_width_change() {
        let original = draw::RenderTarget::new(32, 16, true).unwrap().texture;
        let mut changed = original.clone();
        changed.width = 16;
        assert!(validate_cached_texture(&original, &changed).is_err());
    }

    #[test]
    fn immutable_descriptor_rejects_height_change() {
        let original = draw::RenderTarget::new(32, 16, true).unwrap().texture;
        let mut changed = original.clone();
        changed.height = 32;
        assert!(validate_cached_texture(&original, &changed).is_err());
    }

    #[test]
    fn immutable_descriptor_rejects_rgba_content_change() {
        let original = rgba_texture();
        let mut changed = original.clone();
        changed.source = TextureSource::Rgba8(vec![0; 8].into());
        assert!(validate_cached_texture(&original, &changed).is_err());
    }

    #[test]
    fn immutable_descriptor_rejects_source_kind_change() {
        let original = rgba_texture();
        let mut changed = original.clone();
        changed.source = TextureSource::Target { depth: false };
        assert!(validate_cached_texture(&original, &changed).is_err());
    }

    #[test]
    fn immutable_descriptor_rejects_target_depth_change() {
        let original = draw::RenderTarget::new(32, 16, true).unwrap().texture;
        let mut changed = original.clone();
        changed.source = TextureSource::Target { depth: false };
        assert!(validate_cached_texture(&original, &changed).is_err());
    }

    #[test]
    fn immutable_descriptor_rejects_filter_change() {
        let original = rgba_texture();
        let mut changed = original.clone();
        changed.sampler.filter = draw::FilterMode::Nearest;
        assert!(validate_cached_texture(&original, &changed).is_err());
    }

    #[test]
    fn immutable_descriptor_rejects_horizontal_wrap_change() {
        let original = rgba_texture();
        let mut changed = original.clone();
        changed.sampler.wrap_x = draw::WrapMode::Repeat;
        assert!(validate_cached_texture(&original, &changed).is_err());
    }

    #[test]
    fn immutable_descriptor_rejects_vertical_wrap_change() {
        let original = rgba_texture();
        let mut changed = original.clone();
        changed.sampler.wrap_y = draw::WrapMode::Repeat;
        assert!(validate_cached_texture(&original, &changed).is_err());
    }

    #[test]
    fn immutable_descriptor_rejection_keeps_original_usable() {
        let original = rgba_texture();
        let original_snapshot = original.clone();
        let mut changed = original.clone();
        changed.sampler.wrap_x = draw::WrapMode::Repeat;
        let error = validate_cached_texture(&original, &changed).unwrap_err();
        assert!(error.contains("without a new resource ID"));
        assert_eq!(original.id, original_snapshot.id);
        assert!(same_descriptor(&original, &original_snapshot));
        assert!(validate_cached_texture(&original, &original_snapshot).is_ok());
    }

    #[test]
    fn sampler_variants_can_be_created_with_distinct_resource_ids() {
        let original = rgba_texture();
        let variant = draw::Texture::rgba8(
            2,
            1,
            &[255, 0, 0, 255, 0, 255, 0, 255],
            draw::Sampler {
                wrap_x: draw::WrapMode::Repeat,
                ..original.sampler
            },
        )
        .unwrap();
        assert_ne!(original.id, variant.id);
        assert_ne!(original.sampler, variant.sampler);
        assert!(validate_texture(&original).is_ok());
        assert!(validate_texture(&variant).is_ok());
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
    fn descriptor_identity_and_feedback_are_checked() {
        let target = draw::RenderTarget::new(32, 32, true).unwrap();
        let mut camera = draw::Camera::screen(32, 32);
        camera.target = Some(target.clone());
        assert!(reject_feedback(Some(&target.texture), &camera).is_err());
        assert!(reject_feedback(None, &camera).is_ok());
        let mut changed = target.texture.clone();
        changed.width = 64;
        assert!(!same_descriptor(&changed, &target.texture));
        changed = target.texture.clone();
        changed.sampler.wrap_x = draw::WrapMode::Repeat;
        // This enforces the shared immutable-descriptor contract rather than
        // weakening coverage: sampler variants must now use separate IDs.
        assert!(!same_descriptor(&changed, &target.texture));
        assert!(validate_cached_texture(&target.texture, &changed).is_err());
    }

    #[test]
    fn text_cache_workaround_requires_review_when_dependencies_change() {
        let lock = include_str!("../../Cargo.lock");
        for (name, version, checksum) in [
            (
                "macroquad",
                "0.4.14",
                "d2befbae373456143ef55aa93a73594d080adfb111dc32ec96a1123a3e4ff4ae",
            ),
            (
                "miniquad",
                "0.4.8",
                "2fb3e758e46dbc45716a8a49ca9edc54b15bcca826277e80b1f690708f67f9e3",
            ),
        ] {
            let name_line = format!("name = \"{name}\"");
            let packages: Vec<_> = lock
                .split("[[package]]")
                .filter(|package| package.lines().any(|line| line == name_line))
                .collect();
            assert_eq!(packages.len(), 1, "review the {name} text-cache workaround");
            for required in [
                format!("version = \"{version}\""),
                format!("checksum = \"{checksum}\""),
                "source = \"registry+https://github.com/rust-lang/crates.io-index\"".into(),
            ] {
                assert!(
                    packages[0].lines().any(|line| line == required),
                    "review {name} atlas and GL commit_frame behavior before changing {required}"
                );
            }
        }
    }

    #[test]
    fn text_preparation_drains_and_invalidates_before_native_glyph_warming() {
        use std::cell::RefCell;
        let operations = RefCell::new(Vec::new());
        prepare_default_text_with(
            "F / AMMO FULL — Ω",
            18.75,
            || operations.borrow_mut().push("flush"),
            || {
                operations.borrow_mut().push("invalidate");
                Ok(())
            },
            |text, size| {
                assert_eq!(text, "F / AMMO FULL — Ω");
                assert_eq!(size, 18);
                operations.borrow_mut().push("prewarm");
            },
        )
        .unwrap();
        assert_eq!(*operations.borrow(), ["flush", "invalidate", "prewarm"]);
    }

    #[test]
    fn text_preparation_preserves_quantized_size_in_both_scale_orders() {
        use std::cell::RefCell;
        for sizes in [[18.75, 37.5, 18.75], [37.5, 18.75, 37.5]] {
            let warmed = RefCell::new(Vec::new());
            for size in sizes {
                prepare_default_text_with(
                    "same glyphs",
                    size,
                    || {},
                    || Ok(()),
                    |text, quantized| warmed.borrow_mut().push((text.to_owned(), quantized)),
                )
                .unwrap();
            }
            assert_eq!(
                *warmed.borrow(),
                sizes.map(|size| ("same glyphs".to_owned(), size as u16))
            );
        }
    }

    #[test]
    fn unsupported_text_cache_backend_stops_before_glyph_allocation() {
        use std::cell::RefCell;
        let operations = RefCell::new(Vec::new());
        let result = prepare_default_text_with(
            "not allocated",
            20.,
            || operations.borrow_mut().push("flush"),
            || {
                operations.borrow_mut().push("reject-backend");
                Err("not OpenGL".into())
            },
            |_, _| operations.borrow_mut().push("prewarm"),
        );
        assert_eq!(result.unwrap_err(), "not OpenGL");
        assert_eq!(*operations.borrow(), ["flush", "reject-backend"]);
    }

    #[test]
    fn empty_or_invalid_text_preparation_has_no_graphics_side_effects() {
        for (text, size, valid) in [
            ("", 18., true),
            ("bad", 0., false),
            ("bad", f32::NAN, false),
            ("bad", f32::INFINITY, false),
            ("bad", 65_536., false),
        ] {
            let result = prepare_default_text_with(
                text,
                size,
                || panic!("unexpected flush"),
                || panic!("unexpected binding invalidation"),
                |_, _| panic!("unexpected glyph allocation"),
            );
            assert_eq!(result.is_ok(), valid);
        }
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
        let result = save_capture(&path.join("capture.png"), 1, 1, &[0, 0, 0, 255], true);
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
        save_capture(&path, 2, 2, &bottom_up, true).unwrap();
        let decoded = image::open(&path).unwrap().to_rgba8();
        std::fs::remove_file(path).unwrap();
        assert_eq!(decoded.dimensions(), (2, 2));
        assert_eq!(decoded.get_pixel(0, 0).0, [255, 0, 0, 255]);
        assert_eq!(decoded.get_pixel(1, 0).0, [0, 255, 0, 255]);
        assert_eq!(decoded.get_pixel(0, 1).0, [0, 0, 255, 255]);
        assert_eq!(decoded.get_pixel(1, 1).0, [255, 255, 255, 255]);
    }
}
