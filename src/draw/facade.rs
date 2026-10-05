//! Frame-local, CPU-only compatibility drawing for the game presentation layer.
//!
//! Window coordinates are logical pixels; explicit render targets use their own
//! pixels. Cameras and model transforms are snapshots in an ordered draw list.
//! Nothing in this module reads input, advances simulation, or queries a GPU.

use super::{geometry, Camera, DrawList, Line, TextureSource};
pub use super::{
    BackendInfo, BlendMode, Color, FilterMode, Mesh, Rect, RenderTarget, Sampler, TextDimensions,
    Texture, Texture as Texture2D, Vertex, WrapMode,
};
use crate::render::text::TextRenderer;
pub use glam::*;
use std::{cell::RefCell, path::PathBuf};

pub const WHITE: Color = Color::WHITE;
pub const BLACK: Color = Color::new(0., 0., 0., 1.);
pub const BLANK: Color = Color::TRANSPARENT;
pub const LIGHTGRAY: Color = Color::new(200. / 255., 200. / 255., 200. / 255., 1.);
pub const GRAY: Color = Color::new(130. / 255., 130. / 255., 130. / 255., 1.);
pub const DARKGRAY: Color = Color::new(80. / 255., 80. / 255., 80. / 255., 1.);
pub const YELLOW: Color = Color::new(253. / 255., 249. / 255., 0., 1.);
pub const GOLD: Color = Color::new(1., 203. / 255., 0., 1.);
pub const RED: Color = Color::new(230. / 255., 41. / 255., 55. / 255., 1.);

/// Perspective camera using radians and right-handed OpenGL clip depth.
#[derive(Clone, Debug)]
pub struct Camera3D {
    pub position: Vec3,
    pub target: Vec3,
    pub up: Vec3,
    pub fovy: f32,
    pub aspect: Option<f32>,
    pub z_near: f32,
    pub z_far: f32,
    pub render_target: Option<RenderTarget>,
}
impl Default for Camera3D {
    fn default() -> Self {
        Self {
            position: vec3(0., -10., 0.),
            target: Vec3::ZERO,
            up: Vec3::Z,
            fovy: 45_f32.to_radians(),
            aspect: None,
            z_near: 0.01,
            z_far: 10_000.,
            render_target: None,
        }
    }
}

#[derive(Clone, Copy, Debug, Default)]
pub struct DrawTextureParams {
    pub dest_size: Option<Vec2>,
    /// Explicit source-image flip only. Render targets already use top-left UVs.
    pub flip_y: bool,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct RenderTargetParams {
    pub depth: bool,
}

/// The compatibility layer currently exposes only the embedded default font.
#[derive(Clone, Copy, Debug, Default)]
pub struct Font;

pub fn render_target_ex(
    width: u32,
    height: u32,
    params: RenderTargetParams,
) -> Result<RenderTarget, String> {
    RenderTarget::new(width, height, params.depth)
}

struct FrameRecorder {
    id: u64,
    list: DrawList,
    scale: f32,
    screen_scale_override: Option<f32>,
    camera: Camera,
    model: Mat4,
}
impl FrameRecorder {
    fn screen_scale(&self) -> f32 {
        if let Some(scale) = self.screen_scale_override {
            return scale;
        }
        if self.camera.target.is_some() {
            1.
        } else {
            self.scale
        }
    }

    fn screen_camera(&self) -> Camera {
        let (width, height) = self
            .camera
            .target
            .as_ref()
            .map_or((self.list.width, self.list.height), |target| {
                (target.texture.width, target.texture.height)
            });
        let mut camera = Camera::screen(width, height);
        camera.target = self.camera.target.clone();
        camera
    }

    fn validate_sample(&self, texture: &Texture2D) -> Result<(), String> {
        validate_texture(texture)?;
        if self
            .camera
            .target
            .as_ref()
            .is_some_and(|target| target.texture.id == texture.id)
        {
            return Err("cannot sample the active render target".into());
        }
        Ok(())
    }

    fn mesh(&mut self, mesh: &Mesh, model: Mat4, blend: BlendMode) -> Result<(), String> {
        mesh.validate()?;
        finite_matrix(model)?;
        if !(self.camera.view_projection * model).is_finite() {
            return Err("camera-model transform overflow".into());
        }
        if let Some(texture) = &mesh.texture {
            self.validate_sample(texture)?;
        }
        // Bound every batch, including triangle soups, before any u16 cast.
        // Source indices are already u16; remapping also omits unused vertices.
        const BATCH_INDICES: usize = 65_535;
        const MAX_VERTICES: usize = u16::MAX as usize + 1;
        if mesh.indices.is_empty() {
            return Ok(());
        }
        if mesh.indices.len() <= BATCH_INDICES && mesh.vertices.len() <= MAX_VERTICES {
            self.list.draw_mesh(mesh, model, blend);
        } else {
            for indices in mesh.indices.chunks(BATCH_INDICES) {
                let mut remap = vec![None; mesh.vertices.len().min(MAX_VERTICES)];
                let mut batch = Mesh {
                    texture: mesh.texture.clone(),
                    ..Mesh::default()
                };
                for &index in indices {
                    let mapped = match remap[index as usize] {
                        Some(mapped) => mapped,
                        None => {
                            let mapped = u16::try_from(batch.vertices.len())
                                .map_err(|_| "mesh batch exceeds u16 vertex capacity")?;
                            batch.vertices.push(mesh.vertices[index as usize]);
                            remap[index as usize] = Some(mapped);
                            mapped
                        }
                    };
                    batch.indices.push(mapped);
                }
                self.list.draw_mesh(&batch, model, blend);
            }
        }
        Ok(())
    }

    fn screen_mesh(&mut self, mesh: &Mesh) -> Result<(), String> {
        // Screen geometry must not inherit a 3D projection, depth test, or model.
        let previous = self.camera.clone();
        self.camera = self.screen_camera();
        self.list.camera(self.camera.clone());
        let result = self.mesh(mesh, Mat4::IDENTITY, BlendMode::Alpha);
        self.camera = previous;
        self.list.camera(self.camera.clone());
        result
    }
}

#[derive(Default)]
struct RecorderState {
    frame: Option<FrameRecorder>,
    errors: Vec<String>,
    backend: Option<BackendInfo>,
    text: Option<TextRenderer>,
    next_frame_id: u64,
}
thread_local! {
    static RECORDER: RefCell<RecorderState> = RefCell::new(RecorderState::default());
}

/// Starts exactly one frame at a nonzero physical extent.
/// Taking the previous frame is required; silently discarding work is forbidden.
pub fn begin_frame(width: u32, height: u32, scale_factor: f64) -> Result<(), String> {
    let scale = scale_factor as f32;
    if width == 0 || height == 0 || !scale_factor.is_finite() || !scale.is_finite() || scale <= 0. {
        return Err("frame extent must be nonzero and DPI scale finite and positive".into());
    }
    RECORDER.with(|state| {
        let mut state = state.borrow_mut();
        if state.frame.is_some() {
            return Err("begin_frame called before taking the previous draw list".into());
        }
        if !state.errors.is_empty() {
            return Err(std::mem::take(&mut state.errors).join("; "));
        }
        let camera = Camera::screen(width, height);
        let mut list = DrawList::new(width, height);
        list.camera(camera.clone());
        state.next_frame_id = state.next_frame_id.wrapping_add(1);
        state.frame = Some(FrameRecorder {
            id: state.next_frame_id,
            list,
            scale,
            screen_scale_override: None,
            camera,
            model: Mat4::IDENTITY,
        });
        Ok(())
    })
}

/// Consumes the frame once. Invalid recording returns errors, never a partial frame.
pub fn take_draw_list() -> Result<DrawList, String> {
    RECORDER.with(|state| {
        let mut state = state.borrow_mut();
        let frame = state.frame.take();
        let mut errors = std::mem::take(&mut state.errors);
        match frame {
            Some(frame) if errors.is_empty() => Ok(frame.list),
            Some(_) => Err(errors.join("; ")),
            None => {
                errors.push("take_draw_list called without an active frame".into());
                Err(errors.join("; "))
            }
        }
    })
}

pub fn set_backend_info(info: BackendInfo) {
    RECORDER.with(|state| state.borrow_mut().backend = Some(info));
}
pub fn backend_info() -> Result<BackendInfo, String> {
    RECORDER.with(|state| {
        state
            .borrow()
            .backend
            .clone()
            .ok_or_else(|| "renderer backend information has not been initialized".into())
    })
}
pub fn current_camera() -> Result<Camera, String> {
    RECORDER.with(|state| {
        state
            .borrow()
            .frame
            .as_ref()
            .map(|frame| frame.camera.clone())
            .ok_or_else(|| "no active drawing frame".into())
    })
}
pub fn current_model_matrix() -> Result<Mat4, String> {
    RECORDER.with(|state| {
        state
            .borrow()
            .frame
            .as_ref()
            .map(|frame| frame.model)
            .ok_or_else(|| "no active drawing frame".into())
    })
}

/// Window dimensions in logical pixels, independent of the active target.
/// Presentation helpers can use these without reading a native graphics context.
pub fn screen_width() -> f32 {
    logical_screen_size().x
}
pub fn screen_height() -> f32 {
    logical_screen_size().y
}
fn logical_screen_size() -> Vec2 {
    let mut size = Vec2::ZERO;
    record("screen_size", |frame| {
        size = vec2(frame.list.width as f32, frame.list.height as f32) / frame.scale;
        Ok(())
    });
    size
}

fn record(operation: &str, f: impl FnOnce(&mut FrameRecorder) -> Result<(), String>) {
    RECORDER.with(|state| {
        let mut state = state.borrow_mut();
        let result = state
            .frame
            .as_mut()
            .ok_or_else(|| "no active drawing frame".to_owned())
            .and_then(f);
        if let Err(error) = result {
            state.errors.push(format!("{operation}: {error}"));
        }
    });
}
fn record_error(operation: &str, error: String) {
    RECORDER.with(|state| {
        state
            .borrow_mut()
            .errors
            .push(format!("{operation}: {error}"))
    });
}
fn finite_matrix(matrix: Mat4) -> Result<(), String> {
    if matrix.is_finite() {
        Ok(())
    } else {
        Err("model matrix must be finite".into())
    }
}
fn finite_color(color: Color) -> Result<(), String> {
    if [color.r, color.g, color.b, color.a]
        .into_iter()
        .all(f32::is_finite)
    {
        Ok(())
    } else {
        Err("color must be finite".into())
    }
}
fn finite_values(values: &[f32]) -> Result<(), String> {
    if values.iter().all(|value| value.is_finite()) {
        Ok(())
    } else {
        Err("coordinates must be finite".into())
    }
}
fn validate_texture(texture: &Texture2D) -> Result<(), String> {
    if texture.width == 0 || texture.height == 0 {
        return Err("texture extent must be nonzero".into());
    }
    if let TextureSource::Rgba8(bytes) = &texture.source {
        let expected = texture
            .width
            .checked_mul(texture.height)
            .and_then(|pixels| pixels.checked_mul(4));
        if expected.map(|bytes| bytes as usize) != Some(bytes.len()) {
            return Err("texture extent does not match RGBA8 data".into());
        }
    }
    Ok(())
}
fn validate_target(target: &RenderTarget) -> Result<(), String> {
    validate_texture(&target.texture)?;
    if !matches!(target.texture.source, TextureSource::Target { .. }) {
        return Err("render target must refer to target storage".into());
    }
    Ok(())
}
fn scaled_rect(x: f32, y: f32, w: f32, h: f32, scale: f32) -> Result<Rect, String> {
    let rect = Rect::new(x * scale, y * scale, w * scale, h * scale);
    finite_values(&[
        rect.x,
        rect.y,
        rect.w,
        rect.h,
        rect.x + rect.w,
        rect.y + rect.h,
    ])?;
    Ok(rect)
}

pub fn set_camera(camera: &Camera3D) {
    record("set_camera", |frame| {
        let aspect = camera
            .aspect
            .unwrap_or(frame.list.width as f32 / frame.list.height as f32);
        if !camera.position.is_finite()
            || !camera.target.is_finite()
            || !camera.up.is_finite()
            || !camera.fovy.is_finite()
            || camera.fovy <= 0.
            || camera.fovy >= std::f32::consts::PI
            || !aspect.is_finite()
            || aspect <= 0.
            || !camera.z_near.is_finite()
            || !camera.z_far.is_finite()
            || camera.z_near <= 0.
            || camera.z_far <= camera.z_near
            || (camera.target - camera.position)
                .cross(camera.up)
                .length_squared()
                <= f32::MIN_POSITIVE
        {
            return Err("invalid perspective camera parameters".into());
        }
        if let Some(target) = &camera.render_target {
            validate_target(target)?;
            if !matches!(target.texture.source, TextureSource::Target { depth: true }) {
                return Err("3D camera requires a target with depth storage".into());
            }
        }
        let view_projection =
            Mat4::perspective_rh_gl(camera.fovy, aspect, camera.z_near, camera.z_far)
                * Mat4::look_at_rh(camera.position, camera.target, camera.up);
        if !view_projection.is_finite() {
            return Err("camera projection is not finite".into());
        }
        frame.screen_scale_override = None;
        frame.camera = Camera {
            view_projection,
            target: camera.render_target.clone(),
            depth_test: true,
        };
        frame.list.camera(frame.camera.clone());
        Ok(())
    });
}
/// Select a screen-space canvas with an explicit logical-to-target pixel scale.
/// This does not change the platform's logical viewport or OS DPI. The override
/// is reset by perspective/default camera selection and the next frame.
/// Errors follow the facade's deferred-error contract in `take_draw_list`.
pub fn set_screen_camera(target: Option<&RenderTarget>, logical_scale: f32) {
    record("set_screen_camera", |frame| {
        if !logical_scale.is_finite() || logical_scale <= 0. {
            return Err("screen camera scale must be finite and positive".into());
        }
        if let Some(target) = target {
            validate_target(target)?;
        }
        let (width, height) = target.map_or((frame.list.width, frame.list.height), |target| {
            (target.texture.width, target.texture.height)
        });
        let mut camera = Camera::screen(width, height);
        camera.target = target.cloned();
        frame.camera = camera;
        frame.screen_scale_override = Some(logical_scale);
        frame.list.camera(frame.camera.clone());
        Ok(())
    });
}

pub fn set_default_camera() {
    record("set_default_camera", |frame| {
        frame.screen_scale_override = None;
        frame.camera = Camera::screen(frame.list.width, frame.list.height);
        frame.list.camera(frame.camera.clone());
        Ok(())
    });
}
pub fn clear_background(color: Color) {
    record("clear_background", |frame| {
        finite_color(color)?;
        frame.list.clear(color);
        Ok(())
    });
}

struct ModelGuard {
    previous: Option<(u64, Mat4)>,
}
impl Drop for ModelGuard {
    fn drop(&mut self) {
        if let Some((id, previous)) = self.previous {
            RECORDER.with(|state| {
                if let Some(frame) = state.borrow_mut().frame.as_mut() {
                    if frame.id == id {
                        frame.model = previous;
                    }
                }
            });
        }
    }
}
/// Multiplies the current model matrix by `matrix`, restoring it even on unwind.
/// No RefCell borrow is held while user presentation code executes.
pub fn with_model_matrix<R>(matrix: Mat4, f: impl FnOnce() -> R) -> R {
    let mut guard = ModelGuard { previous: None };
    record("with_model_matrix", |frame| {
        finite_matrix(matrix)?;
        let next = frame.model * matrix;
        finite_matrix(next)?;
        guard.previous = Some((frame.id, frame.model));
        frame.model = next;
        Ok(())
    });
    let result = f();
    drop(guard);
    result
}

pub fn draw_mesh(mesh: &Mesh) {
    draw_mesh_transformed(mesh, Mat4::IDENTITY, BlendMode::Alpha);
}
pub fn draw_mesh_transformed(mesh: &Mesh, model: Mat4, blend: BlendMode) {
    record("draw_mesh", |frame| {
        frame.mesh(mesh, frame.model * model, blend)
    });
}
pub fn draw_cube(position: Vec3, size: Vec3, texture: Option<&Texture2D>, color: Color) {
    record("draw_cube", |frame| {
        finite_color(color)?;
        if !position.is_finite() || !size.is_finite() {
            return Err("cube coordinates must be finite".into());
        }
        let mesh = geometry::cube(position, size, texture.cloned(), color);
        frame.mesh(&mesh, frame.model, BlendMode::Alpha)
    });
}
pub fn draw_cube_wires(position: Vec3, size: Vec3, color: Color) {
    record("draw_cube_wires", |frame| {
        finite_color(color)?;
        let lines = geometry::wire_box(position, size, color);
        if lines
            .iter()
            .any(|line| !line.start.is_finite() || !line.end.is_finite())
        {
            return Err("wire cube coordinates must be finite".into());
        }
        frame.list.draw_lines(&lines, frame.model);
        Ok(())
    });
}
pub fn draw_line_3d(start: Vec3, end: Vec3, color: Color) {
    record("draw_line_3d", |frame| {
        finite_color(color)?;
        if !start.is_finite() || !end.is_finite() {
            return Err("line coordinates must be finite".into());
        }
        frame
            .list
            .draw_lines(&[Line { start, end, color }], frame.model);
        Ok(())
    });
}
pub fn draw_sphere(center: Vec3, radius: f32, texture: Option<&Texture2D>, color: Color) {
    record("draw_sphere", |frame| {
        finite_color(color)?;
        let mut mesh = geometry::sphere(center, radius, 16, 17, color)?;
        mesh.texture = texture.cloned();
        frame.mesh(&mesh, frame.model, BlendMode::Alpha)
    });
}

pub fn draw_rectangle(x: f32, y: f32, width: f32, height: f32, color: Color) {
    record("draw_rectangle", |frame| {
        finite_color(color)?;
        let rect = scaled_rect(x, y, width, height, frame.screen_scale())?;
        frame.list.draw_rect(rect, color);
        Ok(())
    });
}
pub fn draw_rectangle_lines(x: f32, y: f32, width: f32, height: f32, thickness: f32, color: Color) {
    record("draw_rectangle_lines", |frame| {
        finite_color(color)?;
        finite_values(&[thickness])?;
        if thickness < 0. {
            return Err("line thickness must not be negative".into());
        }
        let rect = scaled_rect(x, y, width, height, frame.screen_scale())?;
        let t = thickness * frame.screen_scale() / 2.;
        let right = rect.x + rect.w;
        let bottom = rect.y + rect.h;
        let positions = [
            vec2(rect.x, rect.y),
            vec2(right, rect.y),
            vec2(right, bottom),
            vec2(rect.x, bottom),
            vec2(rect.x + t, rect.y + t),
            vec2(right - t, rect.y + t),
            vec2(right - t, bottom - t),
            vec2(rect.x + t, bottom - t),
        ];
        let mesh = Mesh {
            vertices: positions
                .into_iter()
                .map(|position| Vertex::new2(position.extend(0.), Vec2::ZERO, color))
                .collect(),
            indices: vec![
                0, 1, 4, 1, 4, 5, 1, 5, 6, 1, 2, 6, 3, 7, 2, 2, 7, 6, 0, 4, 3, 3, 4, 7,
            ],
            texture: None,
        };
        frame.screen_mesh(&mesh)
    });
}
pub fn draw_line(x1: f32, y1: f32, x2: f32, y2: f32, thickness: f32, color: Color) {
    record("draw_line", |frame| {
        finite_color(color)?;
        finite_values(&[x1, y1, x2, y2, thickness])?;
        if thickness < 0. {
            return Err("line thickness must not be negative".into());
        }
        let scale = frame.screen_scale();
        let start = vec2(x1, y1) * scale;
        let end = vec2(x2, y2) * scale;
        let delta = end - start;
        if !delta.is_finite() {
            return Err("scaled line coordinates overflow".into());
        }
        if delta == Vec2::ZERO || thickness == 0. {
            return Ok(());
        }
        let normal = vec2(-delta.y, delta.x)
            .try_normalize()
            .ok_or("line length overflow")?
            * (thickness * scale * 0.5);
        let mesh = Mesh {
            vertices: [start + normal, start - normal, end + normal, end - normal]
                .into_iter()
                .map(|position| Vertex::new2(position.extend(0.), Vec2::ZERO, color))
                .collect(),
            indices: vec![0, 1, 2, 2, 1, 3],
            texture: None,
        };
        frame.screen_mesh(&mesh)
    });
}
pub fn draw_circle(x: f32, y: f32, radius: f32, color: Color) {
    record("draw_circle", |frame| {
        finite_color(color)?;
        finite_values(&[x, y, radius])?;
        if radius < 0. {
            return Err("circle radius must not be negative".into());
        }
        let scale = frame.screen_scale();
        let center = vec2(x, y) * scale;
        let mut mesh = Mesh::default();
        mesh.vertices
            .push(Vertex::new2(center.extend(0.), Vec2::ZERO, color));
        const SIDES: u16 = 20;
        for index in 0..=SIDES {
            let angle = f32::from(index) / f32::from(SIDES) * std::f32::consts::TAU;
            let position = center + vec2(angle.cos(), angle.sin()) * radius * scale;
            mesh.vertices
                .push(Vertex::new2(position.extend(0.), Vec2::ZERO, color));
            if index < SIDES {
                mesh.indices.extend_from_slice(&[0, index + 1, index + 2]);
            }
        }
        frame.screen_mesh(&mesh)
    });
}
pub fn draw_triangle(a: Vec2, b: Vec2, c: Vec2, color: Color) {
    record("draw_triangle", |frame| {
        finite_color(color)?;
        let mesh = Mesh {
            vertices: [a, b, c]
                .into_iter()
                .map(|position| {
                    Vertex::new2(
                        (position * frame.screen_scale()).extend(0.),
                        Vec2::ZERO,
                        color,
                    )
                })
                .collect(),
            indices: vec![0, 1, 2],
            texture: None,
        };
        frame.screen_mesh(&mesh)
    });
}
pub fn draw_texture_ex(
    texture: &Texture2D,
    x: f32,
    y: f32,
    tint: Color,
    params: DrawTextureParams,
) {
    record("draw_texture_ex", |frame| {
        finite_color(tint)?;
        frame.validate_sample(texture)?;
        let size = params
            .dest_size
            .unwrap_or(vec2(texture.width as f32, texture.height as f32));
        let rect = scaled_rect(x, y, size.x, size.y, frame.screen_scale())?;
        if !params.flip_y {
            frame.list.draw_texture(texture, rect, tint);
        } else {
            let mesh = Mesh {
                vertices: vec![
                    Vertex::new(rect.x, rect.y, 0., 0., 1., tint),
                    Vertex::new(rect.x + rect.w, rect.y, 0., 1., 1., tint),
                    Vertex::new(rect.x + rect.w, rect.y + rect.h, 0., 1., 0., tint),
                    Vertex::new(rect.x, rect.y + rect.h, 0., 0., 0., tint),
                ],
                indices: vec![0, 1, 2, 0, 2, 3],
                texture: Some(texture.clone()),
            };
            frame.screen_mesh(&mesh)?;
        }
        Ok(())
    });
}

fn measure_default_text(text: &str, size: f32) -> Result<TextDimensions, String> {
    crate::render::text::validate_size(size)?;
    RECORDER.with(|state| {
        let mut state = state.borrow_mut();
        if state.text.is_none() {
            state.text = Some(TextRenderer::new()?);
        }
        let dimensions = state
            .text
            .as_ref()
            .expect("initialized CPU text renderer")
            .measure_text(text, size);
        finite_values(&[dimensions.width, dimensions.height, dimensions.offset_y])?;
        Ok(dimensions)
    })
}
/// Measures in logical pixels, independent of window DPI and the active target.
pub fn measure_text(
    text: &str,
    _font: Option<&Font>,
    font_size: u16,
    font_scale: f32,
) -> TextDimensions {
    match measure_default_text(text, f32::from(font_size) * font_scale) {
        Ok(dimensions) => dimensions,
        Err(error) => {
            record_error("measure_text", error);
            TextDimensions::default()
        }
    }
}
pub fn draw_text(text: &str, x: f32, y: f32, font_size: f32, color: Color) -> TextDimensions {
    let dimensions = match measure_default_text(text, font_size) {
        Ok(dimensions) => dimensions,
        Err(error) => {
            record_error("draw_text", error);
            return TextDimensions::default();
        }
    };
    record("draw_text", |frame| {
        finite_color(color)?;
        let scale = frame.screen_scale();
        let baseline = vec2(x, y) * scale;
        finite_values(&[baseline.x, baseline.y])?;
        crate::render::text::validate_size(font_size * scale)?;
        frame
            .list
            .draw_text(text, baseline, font_size * scale, color);
        Ok(())
    });
    dimensions
}

/// Records a mid-frame checkpoint; readback and file I/O happen only on submit.
pub fn capture_png(target: Option<&RenderTarget>, path: impl Into<PathBuf>) {
    let path = path.into();
    record("capture_png", |frame| {
        if path.as_os_str().is_empty() {
            return Err("capture path must not be empty".into());
        }
        if let Some(target) = target {
            validate_target(target)?;
        }
        frame.list.capture_png(target, path);
        Ok(())
    });
}

/// Validation-only capture: encode invocation/frame identity through real draw commands.
/// The marker occupies physical [0,0,64,22]; normal capture_png is untouched.
pub fn capture_png_with_frame_witness(
    target: Option<&RenderTarget>,
    path: impl Into<PathBuf>,
    frame_index: u32,
    identity: [u8; 32],
) {
    let path = path.into();
    record("capture_png_with_frame_witness", |frame| {
        if path.as_os_str().is_empty() {
            return Err("capture path must not be empty".into());
        }
        if let Some(target) = target {
            validate_target(target)?;
        }
        let (width, height) = target.map_or((frame.list.width, frame.list.height), |t| {
            (t.texture.width, t.texture.height)
        });
        if width < super::frame_witness::WIDTH || height < super::frame_witness::HEIGHT {
            return Err("capture target is too small for frame witness".into());
        }
        let restore = frame.camera.clone();
        let mut marker = Camera::screen(width, height);
        marker.target = target.cloned();
        frame.list.camera(marker);
        frame.list.draw_mesh(
            &super::frame_witness::mesh(frame_index, &identity),
            Mat4::IDENTITY,
            BlendMode::Opaque,
        );
        frame.list.capture_png(target, path);
        frame.list.camera(restore);
        Ok(())
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::draw::Command;

    #[test]
    fn frame_witness_is_drawn_before_readback_and_restores_camera() {
        begin(2.0);
        let target = RenderTarget::new(960, 540, true).unwrap();
        let camera = Camera3D {
            render_target: Some(target.clone()),
            ..Camera3D::default()
        };
        set_camera(&camera);
        capture_png_with_frame_witness(Some(&target), "frame.png", 9, [0x42; 32]);
        let list = take_draw_list().unwrap();
        assert!(matches!(&list.commands[0], Command::Camera(_)));
        let capture_index = list
            .commands
            .iter()
            .position(|command| matches!(command, Command::Capture { .. }))
            .unwrap();
        let marker_index = capture_index - 2;
        let marker = match &list.commands[marker_index] {
            Command::Camera(c) => c,
            _ => panic!("marker camera missing"),
        };
        assert!(!marker.depth_test);
        assert_eq!(
            marker.target.as_ref().unwrap().texture.id,
            target.texture.id
        );
        match &list.commands[marker_index + 1] {
            Command::Mesh { mesh, model, blend } => {
                assert_eq!(mesh.vertices.len(), 1288);
                assert_eq!(mesh.indices.len(), 1932);
                assert_eq!(*model, Mat4::IDENTITY);
                assert_eq!(*blend, BlendMode::Opaque);
            }
            _ => panic!("single witness mesh missing"),
        }
        assert!(
            matches!(&list.commands[capture_index], Command::Capture{path,..} if path.to_str()==Some("frame.png"))
        );
        let (original, restored) = match (
            &list.commands[marker_index - 1],
            &list.commands[capture_index + 1],
        ) {
            (Command::Camera(a), Command::Camera(b)) => (a, b),
            _ => panic!("camera restore missing"),
        };
        assert_eq!(original.view_projection, restored.view_projection);
        assert_eq!(
            original.target.as_ref().unwrap().texture.id,
            restored.target.as_ref().unwrap().texture.id
        );
    }

    #[test]
    fn ordinary_capture_has_no_validation_pixels() {
        begin(1.0);
        capture_png(None, "normal.png");
        let list = take_draw_list().unwrap();
        assert_eq!(
            list.commands
                .iter()
                .filter(|command| matches!(command, Command::Capture { .. }))
                .count(),
            1
        );
        assert!(!list
            .commands
            .iter()
            .any(|command| matches!(command, Command::Rect { .. } | Command::Mesh { .. })));
    }

    fn reset() {
        RECORDER.with(|state| *state.borrow_mut() = RecorderState::default());
    }
    fn begin(scale: f64) {
        reset();
        begin_frame(960, 540, scale).unwrap();
    }
    fn triangle() -> Mesh {
        Mesh {
            vertices: vec![
                Vertex::new2(Vec3::ZERO, Vec2::ZERO, WHITE),
                Vertex::new2(Vec3::X, Vec2::X, WHITE),
                Vertex::new2(Vec3::Y, Vec2::Y, WHITE),
            ],
            indices: vec![0, 1, 2],
            texture: None,
        }
    }
    fn perspective(target: Option<RenderTarget>) -> Camera3D {
        Camera3D {
            position: vec3(2., 3., 4.),
            target: Vec3::ZERO,
            up: Vec3::Y,
            render_target: target,
            ..Camera3D::default()
        }
    }

    #[test]
    fn frame_lifecycle_rejects_invalid_extents_and_does_not_overwrite_work() {
        reset();
        for (width, height, scale) in [
            (0, 1, 1.),
            (1, 0, 1.),
            (1, 1, 0.),
            (1, 1, -1.),
            (1, 1, f64::NAN),
            (1, 1, f64::MAX),
            (1, 1, f64::MIN_POSITIVE),
        ] {
            assert!(begin_frame(width, height, scale).is_err());
        }
        begin_frame(800, 600, 1.).unwrap();
        clear_background(WHITE);
        assert!(begin_frame(400, 300, 2.).is_err());
        let list = take_draw_list().unwrap();
        assert_eq!((list.width, list.height), (800, 600));
        assert!(matches!(list.commands.last(), Some(Command::Clear(WHITE))));
        assert!(take_draw_list().is_err());
        draw_rectangle(0., 0., 1., 1., WHITE);
        assert!(begin_frame(800, 600, 1.)
            .unwrap_err()
            .contains("draw_rectangle"));
        begin_frame(800, 600, 1.).unwrap();
        take_draw_list().unwrap();
    }

    #[test]
    fn window_screen_commands_scale_but_text_measurements_remain_logical() {
        begin(2.);
        let texture = Texture2D::rgba8(2, 1, &[255; 8], Sampler::default()).unwrap();
        draw_rectangle(10., 20., 30., 40., WHITE);
        draw_texture_ex(&texture, 3., 4., WHITE, DrawTextureParams::default());
        let measured = measure_text("Ag ", None, 16, 1.);
        let drawn = draw_text("Ag ", 10., 20., 16., WHITE);
        assert_eq!(
            measured,
            TextDimensions {
                width: 21.,
                height: 11.,
                offset_y: 8.
            }
        );
        assert_eq!(drawn, measured);
        let list = take_draw_list().unwrap();
        assert!(
            matches!(&list.commands[1], Command::Rect { rect, .. } if *rect == Rect::new(20.,40.,60.,80.))
        );
        assert!(
            matches!(&list.commands[2], Command::Sprite { destination, .. } if *destination == Rect::new(6.,8.,4.,2.))
        );
        assert!(
            matches!(&list.commands[3], Command::Text { baseline, size, .. } if *baseline == vec2(20.,40.) && *size == 32.)
        );
    }

    #[test]
    fn explicit_screen_target_scales_production_2d_and_restores_existing_defaults() {
        begin(1.5);
        let target = RenderTarget::new(640, 400, false).unwrap();
        set_screen_camera(Some(&target), 2.);
        let measured = measure_text("A", None, 16, 1.);
        draw_rectangle(10., 20., 30., 40., WHITE);
        assert_eq!(draw_text("A", 5., 6., 16., WHITE), measured);
        set_default_camera();
        draw_rectangle(10., 20., 30., 40., WHITE);
        let list = take_draw_list().unwrap();
        let camera = list
            .commands
            .iter()
            .find_map(|command| match command {
                Command::Camera(camera) if camera.target.is_some() => Some(camera),
                _ => None,
            })
            .unwrap();
        assert_eq!(
            camera.target.as_ref().unwrap().texture.id,
            target.texture.id
        );
        assert!(!camera.depth_test);
        let rectangles: Vec<_> = list
            .commands
            .iter()
            .filter_map(|command| match command {
                Command::Rect { rect, .. } => Some(*rect),
                _ => None,
            })
            .collect();
        assert_eq!(
            rectangles,
            [Rect::new(20., 40., 60., 80.), Rect::new(15., 30., 45., 60.)]
        );
        assert!(list.commands.iter().any(|command| matches!(command,
            Command::Text { baseline, size, .. } if *baseline == vec2(10.,12.) && *size == 32.)));
        begin(1.);
        draw_rectangle(10., 20., 30., 40., WHITE);
        assert!(take_draw_list()
            .unwrap()
            .commands
            .iter()
            .any(|command| matches!(command,
            Command::Rect { rect, .. } if *rect == Rect::new(10.,20.,30.,40.))));
    }

    #[test]
    fn screen_scale_override_cannot_leak_into_perspective_or_bypass_validation() {
        begin(1.5);
        let target = RenderTarget::new(320, 200, true).unwrap();
        set_screen_camera(Some(&target), 2.);
        set_camera(&perspective(Some(target.clone())));
        draw_rectangle(1., 2., 3., 4., WHITE);
        assert!(take_draw_list()
            .unwrap()
            .commands
            .iter()
            .any(|command| matches!(command,
            Command::Rect { rect, .. } if *rect == Rect::new(1.,2.,3.,4.))));
        for scale in [0., -1., f32::NAN, f32::INFINITY] {
            begin(1.);
            set_screen_camera(Some(&target), scale);
            assert!(take_draw_list()
                .unwrap_err()
                .contains("screen camera scale"));
        }
        begin(1.);
        set_screen_camera(Some(&target), 2.);
        draw_texture_ex(&target.texture, 0., 0., WHITE, DrawTextureParams::default());
        assert!(take_draw_list()
            .unwrap_err()
            .contains("active render target"));
    }

    #[test]
    fn named_targets_use_their_own_pixels_and_default_camera_restores_dpi() {
        begin(2.);
        let target = RenderTarget::new(320, 200, true).unwrap();
        set_camera(&perspective(Some(target.clone())));
        draw_rectangle(10., 20., 30., 40., WHITE);
        draw_text("A", 5., 6., 16., WHITE);
        draw_triangle(vec2(1., 2.), vec2(3., 4.), vec2(5., 6.), WHITE);
        set_default_camera();
        draw_rectangle(10., 20., 30., 40., WHITE);
        let list = take_draw_list().unwrap();
        assert!(
            matches!(&list.commands[2], Command::Rect { rect, .. } if *rect == Rect::new(10.,20.,30.,40.))
        );
        assert!(
            matches!(&list.commands[3], Command::Text { baseline, size, .. } if *baseline == vec2(5.,6.) && *size == 16.)
        );
        let Command::Camera(screen) = &list.commands[4] else {
            panic!("scoped screen camera missing")
        };
        assert!(!screen.depth_test);
        assert_eq!(
            screen.target.as_ref().unwrap().texture.id,
            target.texture.id
        );
        assert_eq!(
            screen.view_projection,
            Camera::screen(320, 200).view_projection
        );
        let Command::Mesh { mesh, .. } = &list.commands[5] else {
            panic!("screen triangle missing")
        };
        assert_eq!(mesh.vertices[0].position, vec3(1., 2., 0.));
        assert!(
            matches!(list.commands.last(), Some(Command::Rect { rect, .. }) if *rect == Rect::new(20.,40.,60.,80.))
        );
    }

    #[test]
    fn screen_mesh_primitives_scope_projection_and_ignore_3d_model() {
        begin(2.);
        set_camera(&perspective(None));
        let camera = current_camera().unwrap();
        with_model_matrix(Mat4::from_translation(Vec3::splat(100.)), || {
            draw_line(1., 2., 5., 2., 2., WHITE);
            draw_circle(5., 6., 2., WHITE);
            draw_triangle(Vec2::ZERO, Vec2::X, Vec2::Y, WHITE);
            draw_rectangle_lines(1., 2., 8., 6., 2., WHITE);
        });
        assert_eq!(
            current_camera().unwrap().view_projection,
            camera.view_projection
        );
        draw_mesh(&triangle());
        let list = take_draw_list().unwrap();
        for chunk in list.commands[2..14].as_chunks::<3>().0 {
            let Command::Camera(screen) = &chunk[0] else {
                panic!("screen camera missing")
            };
            assert!(!screen.depth_test);
            assert_eq!(
                screen.view_projection,
                Camera::screen(960, 540).view_projection
            );
            let Command::Mesh { model, mesh, .. } = &chunk[1] else {
                panic!("screen mesh missing")
            };
            assert_eq!(*model, Mat4::IDENTITY);
            mesh.validate().unwrap();
            let Command::Camera(restored) = &chunk[2] else {
                panic!("restored camera missing")
            };
            assert!(restored.depth_test);
            assert_eq!(restored.view_projection, camera.view_projection);
        }
        let Command::Mesh { mesh, .. } = &list.commands[3] else {
            panic!("line missing")
        };
        assert_eq!(mesh.vertices[0].position, vec3(2., 6., 0.));
        assert_eq!(mesh.vertices[3].position, vec3(10., 2., 0.));
        assert!(
            matches!(list.commands.last(), Some(Command::Mesh { model, .. }) if *model == Mat4::IDENTITY)
        );
    }

    #[test]
    fn perspective_uses_gl_clip_depth_and_macroquad_defaults() {
        begin(1.);
        let camera = Camera3D {
            position: Vec3::ZERO,
            target: -Vec3::Z,
            up: Vec3::Y,
            z_near: 0.25,
            z_far: 20.,
            ..Camera3D::default()
        };
        set_camera(&camera);
        let current = current_camera().unwrap();
        assert!(
            (current
                .view_projection
                .project_point3(vec3(0., 0., -0.25))
                .z
                + 1.)
                .abs()
                < 0.00001
        );
        assert!(
            (current.view_projection.project_point3(vec3(0., 0., -20.)).z - 1.).abs() < 0.00001
        );
        assert!(current.depth_test);
        assert_eq!(
            current.view_projection,
            Mat4::perspective_rh_gl(45_f32.to_radians(), 960. / 540., 0.25, 20.)
        );
        take_draw_list().unwrap();
    }

    #[test]
    fn model_scopes_compose_nested_matrices_and_restore_on_unwind() {
        begin(1.);
        let translate = Mat4::from_translation(vec3(2., 3., 4.));
        let rotate = Mat4::from_rotation_y(0.7);
        let scale = Mat4::from_scale(vec3(1., 2., 3.));
        let result = with_model_matrix(translate, || {
            assert_eq!(current_model_matrix().unwrap(), translate);
            with_model_matrix(rotate, || {
                draw_mesh_transformed(&triangle(), scale, BlendMode::Additive);
            });
            assert_eq!(current_model_matrix().unwrap(), translate);
            42
        });
        assert_eq!(result, 42);
        assert_eq!(current_model_matrix().unwrap(), Mat4::IDENTITY);
        let panic =
            std::panic::catch_unwind(|| with_model_matrix(translate, || panic!("scope test")));
        assert!(panic.is_err());
        assert_eq!(current_model_matrix().unwrap(), Mat4::IDENTITY);
        draw_mesh(&triangle());
        let list = take_draw_list().unwrap();
        assert!(
            matches!(&list.commands[1], Command::Mesh { model, blend: BlendMode::Additive, .. } if *model == translate * rotate * scale)
        );
        assert!(
            matches!(&list.commands[2], Command::Mesh { model, .. } if *model == Mat4::IDENTITY)
        );
    }

    #[test]
    fn recording_snapshots_meshes_and_texture_descriptors() {
        begin(1.);
        let mut mesh = triangle();
        mesh.texture = Some(Texture2D::rgba8(1, 1, &[255; 4], Sampler::default()).unwrap());
        draw_mesh(&mesh);
        mesh.vertices[0].position = Vec3::ONE;
        mesh.indices[0] = 2;
        mesh.texture.as_mut().unwrap().width = 7;
        let list = take_draw_list().unwrap();
        let Command::Mesh { mesh, .. } = &list.commands[1] else {
            panic!("mesh missing")
        };
        assert_eq!(mesh.vertices[0].position, Vec3::ZERO);
        assert_eq!(mesh.indices, [0, 1, 2]);
        assert_eq!(mesh.texture.as_ref().unwrap().width, 1);
    }

    #[test]
    fn large_index_stream_is_split_without_truncating_or_reordering_triangles() {
        begin(1.);
        let mut mesh = triangle();
        mesh.indices = (0..70_002).map(|i| (i % 3) as u16).collect();
        draw_mesh(&mesh);
        let list = take_draw_list().unwrap();
        let batches: Vec<_> = list
            .commands
            .iter()
            .filter_map(|command| {
                if let Command::Mesh { mesh, .. } = command {
                    Some(mesh)
                } else {
                    None
                }
            })
            .collect();
        assert_eq!(batches.len(), 2);
        assert_eq!(
            batches.iter().map(|mesh| mesh.indices.len()).sum::<usize>(),
            70_002
        );
        assert_eq!(batches[0].indices.len(), 65_535);
        let actual: Vec<_> = batches
            .iter()
            .flat_map(|batch| {
                batch
                    .indices
                    .iter()
                    .map(|&index| batch.vertices[index as usize])
            })
            .collect();
        let expected: Vec<_> = mesh
            .indices
            .iter()
            .map(|&index| mesh.vertices[index as usize])
            .collect();
        assert_eq!(actual, expected);
        for batch in batches {
            batch.validate().unwrap();
        }
    }

    #[test]
    fn maximum_u16_index_is_valid_and_unreferenced_vertices_are_remapped() {
        begin(1.);
        let mut mesh = triangle();
        mesh.vertices.resize(65_540, mesh.vertices[0]);
        mesh.vertices[65_535] = Vertex::new2(vec3(9., 8., 7.), Vec2::ZERO, WHITE);
        mesh.indices = vec![65_535, 0, 1];
        draw_mesh(&mesh);
        let list = take_draw_list().unwrap();
        let Command::Mesh { mesh, .. } = &list.commands[1] else {
            panic!("mesh missing")
        };
        assert_eq!(mesh.vertices.len(), 3);
        assert_eq!(mesh.vertices[0].position, vec3(9., 8., 7.));
        assert_eq!(mesh.indices, [0, 1, 2]);
    }

    #[test]
    fn capture_checkpoints_preserve_target_and_composite_order() {
        begin(1.);
        let target = render_target_ex(100, 50, RenderTargetParams { depth: true }).unwrap();
        set_camera(&perspective(Some(target.clone())));
        clear_background(BLANK);
        draw_mesh(&triangle());
        capture_png(Some(&target), "viewmodel.png");
        set_default_camera();
        draw_texture_ex(
            &target.texture,
            0.,
            0.,
            WHITE,
            DrawTextureParams {
                dest_size: Some(vec2(960., 540.)),
                ..DrawTextureParams::default()
            },
        );
        capture_png(None, "composite.png");
        draw_rectangle(1., 2., 3., 4., WHITE);
        let list = take_draw_list().unwrap();
        assert!(
            matches!(&list.commands[4], Command::Capture { target: Some(captured), path } if captured.texture.id == target.texture.id && path.to_str() == Some("viewmodel.png"))
        );
        assert!(
            matches!(&list.commands[6], Command::Sprite { texture, .. } if texture.id == target.texture.id)
        );
        assert!(
            matches!(&list.commands[7], Command::Capture { target: None, path } if path.to_str() == Some("composite.png"))
        );
        assert!(matches!(&list.commands[8], Command::Rect { .. }));
    }

    #[test]
    fn explicit_sprite_flip_changes_uvs_without_changing_target_orientation() {
        begin(1.5);
        let target = RenderTarget::new(20, 10, true).unwrap();
        draw_texture_ex(
            &target.texture,
            1.,
            2.,
            WHITE,
            DrawTextureParams {
                dest_size: Some(vec2(4., 6.)),
                flip_y: true,
            },
        );
        let list = take_draw_list().unwrap();
        let Command::Mesh { mesh, .. } = &list.commands[2] else {
            panic!("flipped sprite missing")
        };
        assert_eq!(mesh.vertices[0].uv, vec2(0., 1.));
        assert_eq!(mesh.vertices[2].uv, vec2(1., 0.));
        assert_eq!(mesh.vertices[0].position, vec3(1.5, 3., 0.));
        assert_eq!(mesh.vertices[2].position, vec3(7.5, 12., 0.));
    }

    #[test]
    fn invalid_primitives_and_capture_errors_surface_together_instead_of_partial_frame() {
        begin(1.);
        draw_rectangle(f32::NAN, 0., 1., 1., WHITE);
        draw_line(0., 0., 1., 1., -1., WHITE);
        draw_circle(0., 0., -1., WHITE);
        draw_triangle(Vec2::splat(f32::INFINITY), Vec2::ZERO, Vec2::ONE, WHITE);
        draw_sphere(Vec3::ZERO, f32::NAN, None, WHITE);
        draw_mesh(&Mesh {
            indices: vec![0, 1],
            ..Mesh::default()
        });
        capture_png(None, "");
        let error = take_draw_list().unwrap_err();
        for operation in [
            "draw_rectangle",
            "draw_line",
            "draw_circle",
            "draw_triangle",
            "draw_sphere",
            "draw_mesh",
            "capture_png",
        ] {
            assert!(error.contains(operation), "missing {operation}: {error}");
        }
        begin_frame(960, 540, 1.).unwrap();
        take_draw_list().unwrap();
    }

    #[test]
    fn invalid_camera_preserves_prior_camera_and_rejects_depthless_targets() {
        begin(1.);
        let previous = current_camera().unwrap();
        set_camera(&Camera3D {
            position: Vec3::ZERO,
            target: Vec3::ZERO,
            ..Camera3D::default()
        });
        assert_eq!(
            current_camera().unwrap().view_projection,
            previous.view_projection
        );
        set_camera(&perspective(Some(RenderTarget::new(1, 1, false).unwrap())));
        let error = take_draw_list().unwrap_err();
        assert!(error.contains("invalid perspective camera"));
        assert!(error.contains("depth storage"));
    }

    #[test]
    fn sampling_active_target_is_an_explicit_recording_error() {
        begin(1.);
        let target = RenderTarget::new(10, 10, true).unwrap();
        set_camera(&perspective(Some(target.clone())));
        draw_texture_ex(&target.texture, 0., 0., WHITE, DrawTextureParams::default());
        let mut mesh = triangle();
        mesh.texture = Some(target.texture.clone());
        draw_mesh(&mesh);
        let error = take_draw_list().unwrap_err();
        assert!(error.contains("draw_texture_ex: cannot sample the active render target"));
        assert!(error.contains("draw_mesh: cannot sample the active render target"));
    }

    #[test]
    fn malformed_texture_and_non_target_capture_are_rejected() {
        begin(1.);
        let mut texture = Texture2D::rgba8(1, 1, &[255; 4], Sampler::default()).unwrap();
        capture_png(
            Some(&RenderTarget {
                texture: texture.clone(),
            }),
            "bad.png",
        );
        texture.width = 2;
        draw_texture_ex(&texture, 0., 0., WHITE, DrawTextureParams::default());
        let error = take_draw_list().unwrap_err();
        assert!(error.contains("target storage"));
        assert!(error.contains("RGBA8 data"));
    }

    #[test]
    fn invalid_model_and_scaled_text_are_queued_without_poisoning_next_frame() {
        begin(2.);
        with_model_matrix(Mat4::from_cols_array(&[f32::NAN; 16]), || {
            draw_mesh(&triangle())
        });
        assert_eq!(current_model_matrix().unwrap(), Mat4::IDENTITY);
        draw_text("too large", 0., 0., 600., WHITE);
        measure_text("bad", None, 16, f32::NAN);
        let error = take_draw_list().unwrap_err();
        assert!(error.contains("with_model_matrix"));
        assert!(error.contains("draw_text"));
        assert!(error.contains("measure_text"));
        begin_frame(100, 100, 1.).unwrap();
        draw_text("good", 0., 20., 16., WHITE);
        take_draw_list().unwrap();
    }

    #[test]
    fn world_primitives_snapshot_current_model_and_have_valid_geometry() {
        begin(1.);
        let model = Mat4::from_translation(vec3(1., 2., 3.));
        with_model_matrix(model, || {
            draw_cube(Vec3::ZERO, Vec3::ONE, None, WHITE);
            draw_cube_wires(Vec3::ZERO, Vec3::ONE, WHITE);
            draw_line_3d(Vec3::ZERO, Vec3::X, WHITE);
            draw_sphere(Vec3::ZERO, 0.25, None, WHITE);
        });
        let list = take_draw_list().unwrap();
        for command in &list.commands[1..] {
            match command {
                Command::Mesh {
                    mesh,
                    model: captured,
                    ..
                } => {
                    assert_eq!(*captured, model);
                    mesh.validate().unwrap();
                }
                Command::Lines {
                    model: captured,
                    lines,
                } => {
                    assert_eq!(*captured, model);
                    assert!(!lines.is_empty());
                }
                _ => panic!("unexpected primitive command"),
            }
        }
    }

    #[test]
    fn backend_and_frame_state_are_thread_local() {
        begin(1.);
        let info = BackendInfo {
            requested: "wgpu".into(),
            backend: "Vulkan".into(),
            adapter: "test".into(),
        };
        set_backend_info(info.clone());
        let child = std::thread::spawn(|| {
            assert!(backend_info().is_err());
            assert!(current_camera().is_err());
            begin_frame(20, 10, 2.).unwrap();
            draw_rectangle(1., 1., 1., 1., WHITE);
            take_draw_list().unwrap()
        })
        .join()
        .unwrap();
        assert_eq!((child.width, child.height), (20, 10));
        assert_eq!(backend_info().unwrap(), info);
        assert_eq!(take_draw_list().unwrap().commands.len(), 1);
        assert_eq!(backend_info().unwrap(), info);
    }
}
