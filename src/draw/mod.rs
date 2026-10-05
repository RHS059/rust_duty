//! Backend-neutral presentation snapshots; the renderer never advances simulation.
use glam::{Mat4, Vec2, Vec3, Vec4};
use std::{
    path::PathBuf,
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc,
    },
};
pub mod facade;
pub mod geometry;
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Color {
    pub r: f32,
    pub g: f32,
    pub b: f32,
    pub a: f32,
}
impl Color {
    pub const fn new(r: f32, g: f32, b: f32, a: f32) -> Self {
        Self { r, g, b, a }
    }
    pub const WHITE: Self = Self::new(1., 1., 1., 1.);
    pub const TRANSPARENT: Self = Self::new(0., 0., 0., 0.);
}
impl From<Color> for [u8; 4] {
    fn from(c: Color) -> Self {
        [c.r, c.g, c.b, c.a].map(|v| (v * 255.) as u8)
    }
}
/// Public CPU vertex. GPU packing must not read aligned Vec4 padding.
#[repr(C)]
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Vertex {
    pub position: Vec3,
    pub uv: Vec2,
    pub color: [u8; 4],
    pub normal: Vec4,
}
impl Vertex {
    pub fn new2(position: Vec3, uv: Vec2, color: Color) -> Self {
        Self {
            position,
            uv,
            color: color.into(),
            normal: Vec4::ZERO,
        }
    }
    pub fn new(x: f32, y: f32, z: f32, u: f32, v: f32, color: Color) -> Self {
        Self::new2(Vec3::new(x, y, z), Vec2::new(u, v), color)
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum FilterMode {
    Nearest,
    Linear,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum WrapMode {
    Clamp,
    Repeat,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct Sampler {
    pub filter: FilterMode,
    pub wrap_x: WrapMode,
    pub wrap_y: WrapMode,
}
impl Default for Sampler {
    fn default() -> Self {
        Self {
            filter: FilterMode::Linear,
            wrap_x: WrapMode::Clamp,
            wrap_y: WrapMode::Clamp,
        }
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct ResourceId(pub u64);
fn resource_id() -> ResourceId {
    static NEXT: AtomicU64 = AtomicU64::new(1);
    ResourceId(NEXT.fetch_add(1, Ordering::Relaxed))
}
#[derive(Clone, Debug)]
pub enum TextureSource {
    Rgba8(Arc<[u8]>),
    Target { depth: bool },
}
/// Source, extent and sampler are immutable once submitted; changes need a new ID.
#[derive(Clone, Debug)]
pub struct Texture {
    pub id: ResourceId,
    pub width: u32,
    pub height: u32,
    pub sampler: Sampler,
    pub source: TextureSource,
}
impl Texture {
    pub fn rgba8(width: u32, height: u32, bytes: &[u8], sampler: Sampler) -> Result<Self, String> {
        let expected = width.checked_mul(height).and_then(|n| n.checked_mul(4));
        if width == 0 || height == 0 || expected.map(|n| n as usize) != Some(bytes.len()) {
            return Err("texture extent does not match RGBA8 data".into());
        }
        Ok(Self {
            id: resource_id(),
            width,
            height,
            sampler,
            source: TextureSource::Rgba8(bytes.into()),
        })
    }
}
#[derive(Clone, Debug)]
pub struct RenderTarget {
    pub texture: Texture,
}
impl RenderTarget {
    pub fn new(width: u32, height: u32, depth: bool) -> Result<Self, String> {
        if width == 0 || height == 0 {
            return Err("render target extent must be nonzero".into());
        }
        Ok(Self {
            texture: Texture {
                id: resource_id(),
                width,
                height,
                sampler: Sampler::default(),
                source: TextureSource::Target { depth },
            },
        })
    }
}
#[derive(Clone, Debug, Default)]
pub struct Mesh {
    pub vertices: Vec<Vertex>,
    pub indices: Vec<u16>,
    pub texture: Option<Texture>,
}
impl Mesh {
    pub fn validate(&self) -> Result<(), String> {
        if !self.indices.len().is_multiple_of(3) {
            return Err("triangle index count is not divisible by three".into());
        }
        if self
            .indices
            .iter()
            .any(|&i| i as usize >= self.vertices.len())
        {
            return Err("mesh index out of range".into());
        }
        if self
            .vertices
            .iter()
            .any(|v| !v.position.is_finite() || !v.uv.is_finite() || !v.normal.is_finite())
        {
            return Err("non-finite mesh vertex".into());
        }
        Ok(())
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BlendMode {
    Opaque,
    Alpha,
    Additive,
}
#[derive(Clone, Debug)]
pub struct Camera {
    /// Right-handed OpenGL clip depth. Only wgpu remaps to 0..1.
    pub view_projection: Mat4,
    pub target: Option<RenderTarget>,
    pub depth_test: bool,
}
impl Camera {
    pub fn screen(width: u32, height: u32) -> Self {
        Self {
            view_projection: Mat4::orthographic_rh_gl(0., width as f32, height as f32, 0., -1., 1.),
            target: None,
            depth_test: false,
        }
    }
}
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Line {
    pub start: Vec3,
    pub end: Vec3,
    pub color: Color,
}
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Rect {
    pub x: f32,
    pub y: f32,
    pub w: f32,
    pub h: f32,
}
impl Rect {
    pub const fn new(x: f32, y: f32, w: f32, h: f32) -> Self {
        Self { x, y, w, h }
    }
    /// Match the inclusive edge hit-testing used by existing native UI rectangles.
    pub fn contains(&self, point: Vec2) -> bool {
        point.x >= self.x
            && point.x <= self.x + self.w
            && point.y >= self.y
            && point.y <= self.y + self.h
    }
}
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct TextDimensions {
    pub width: f32,
    pub height: f32,
    pub offset_y: f32,
}
#[derive(Clone, Debug)]
pub enum Command {
    Camera(Camera),
    Clear(Color),
    Mesh {
        mesh: Mesh,
        model: Mat4,
        blend: BlendMode,
    },
    Lines {
        lines: Vec<Line>,
        model: Mat4,
    },
    Rect {
        rect: Rect,
        color: Color,
    },
    Sprite {
        texture: Texture,
        destination: Rect,
        tint: Color,
    },
    Text {
        text: String,
        baseline: Vec2,
        size: f32,
        color: Color,
    },
    /// Ordered checkpoint; bytes are top-left first.
    Capture {
        target: Option<RenderTarget>,
        path: PathBuf,
    },
}
#[derive(Clone, Debug)]
pub struct DrawList {
    pub width: u32,
    pub height: u32,
    pub commands: Vec<Command>,
}
impl DrawList {
    pub fn new(width: u32, height: u32) -> Self {
        Self {
            width,
            height,
            commands: Vec::new(),
        }
    }
    pub fn camera(&mut self, camera: Camera) {
        self.commands.push(Command::Camera(camera));
    }
    pub fn clear(&mut self, color: Color) {
        self.commands.push(Command::Clear(color));
    }
    pub fn draw_mesh(&mut self, mesh: &Mesh, model: Mat4, blend: BlendMode) {
        self.commands.push(Command::Mesh {
            mesh: mesh.clone(),
            model,
            blend,
        });
    }
    pub fn draw_lines(&mut self, lines: &[Line], model: Mat4) {
        self.commands.push(Command::Lines {
            lines: lines.to_vec(),
            model,
        });
    }
    pub fn draw_wire_box(&mut self, center: Vec3, size: Vec3, color: Color, model: Mat4) {
        self.draw_lines(&geometry::wire_box(center, size, color), model);
    }
    pub fn draw_rect(&mut self, rect: Rect, color: Color) {
        self.commands.push(Command::Rect { rect, color });
    }
    pub fn draw_texture(&mut self, texture: &Texture, destination: Rect, tint: Color) {
        self.commands.push(Command::Sprite {
            texture: texture.clone(),
            destination,
            tint,
        });
    }
    pub fn draw_text(&mut self, text: &str, baseline: Vec2, size: f32, color: Color) {
        self.commands.push(Command::Text {
            text: text.to_owned(),
            baseline,
            size,
            color,
        });
    }
    pub fn capture_png(&mut self, target: Option<&RenderTarget>, path: impl Into<PathBuf>) {
        self.commands.push(Command::Capture {
            target: target.cloned(),
            path: path.into(),
        });
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BackendInfo {
    pub requested: String,
    pub backend: String,
    pub adapter: String,
}
#[derive(Clone, Debug, Default)]
pub struct FrameOutput {
    pub captures: Vec<PathBuf>,
}
pub trait Renderer {
    fn info(&self) -> &BackendInfo;
    fn measure_text(&self, text: &str, size: f32) -> Result<TextDimensions, String>;
    fn submit(&mut self, list: &DrawList) -> Result<FrameOutput, String>;
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn draws_snapshot_skinned_vertices_and_capture_order() {
        let mut mesh = Mesh {
            vertices: vec![Vertex::new2(Vec3::ZERO, Vec2::ZERO, Color::WHITE)],
            ..Mesh::default()
        };
        let mut list = DrawList::new(960, 540);
        list.draw_mesh(&mesh, Mat4::IDENTITY, BlendMode::Alpha);
        list.capture_png(None, "world.png");
        list.draw_rect(Rect::new(0., 0., 1., 1.), Color::WHITE);
        mesh.vertices[0].position = Vec3::ONE;
        assert!(
            matches!(&list.commands[0],Command::Mesh{mesh,..}if mesh.vertices[0].position==Vec3::ZERO)
        );
        assert!(
            matches!(&list.commands[1],Command::Capture{path,..}if path.to_str()==Some("world.png"))
        );
        assert!(matches!(&list.commands[2], Command::Rect { .. }));
    }
    #[test]
    fn rejects_corrupt_geometry_and_texture_size() {
        assert!(Texture::rgba8(1, 1, &[0; 3], Sampler::default()).is_err());
        assert!(Texture::rgba8(u32::MAX, 2, &[], Sampler::default()).is_err());
        assert!(Mesh {
            indices: vec![0, 1, 2],
            ..Mesh::default()
        }
        .validate()
        .is_err());
    }
    #[test]
    fn screen_coordinates_preserve_top_left() {
        assert_eq!(
            Camera::screen(960, 540)
                .view_projection
                .project_point3(Vec3::ZERO)
                .truncate(),
            Vec2::new(-1., 1.)
        );
    }
}
