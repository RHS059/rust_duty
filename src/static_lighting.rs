//! Offline, deterministic diffuse lighting bake. Triangle BVH, soft sun, occluded
//! sky and one diffuse bounce. Runtime consumes colors; it does not trace rays.
use crate::{
    draw::{Color, Mesh, Vertex},
    sim::Aabb,
};
#[cfg(test)]
use glam::Vec2;
use glam::Vec3;

#[derive(Clone, Copy)]
struct Triangle {
    p: Vec3,
    e1: Vec3,
    e2: Vec3,
    n: Vec3,
    color: Vec3,
    bounce: Vec3,
    bounds: Aabb,
}
struct Node {
    bounds: Aabb,
    start: usize,
    end: usize,
    children: Option<(usize, usize)>,
}
pub struct BakeScene {
    triangles: Vec<Triangle>,
    nodes: Vec<Node>,
    pub lamps: Vec<Vec3>,
}
const SUN: Vec3 = Vec3::new(-0.45, 0.78, 0.43);
fn sun() -> Vec3 {
    SUN.normalize()
}
fn linear(c: Vec3) -> Vec3 {
    Vec3::from_array(c.to_array().map(|v| {
        if v <= 0.04045 {
            v / 12.92
        } else {
            ((v + 0.055) / 1.055).powf(2.4)
        }
    }))
}
fn display(c: Vec3) -> Vec3 {
    Vec3::from_array(c.to_array().map(|x| {
        let x = x.max(0.);
        let t = ((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14)).clamp(0., 1.);
        if t <= 0.0031308 {
            t * 12.92
        } else {
            1.055 * t.powf(1. / 2.4) - 0.055
        }
    }))
}
impl BakeScene {
    pub fn new(meshes: &[Mesh], lamps: Vec<Vec3>) -> Self {
        let mut triangles = Vec::new();
        for mesh in meshes {
            for ids in mesh.indices.chunks_exact(3) {
                let a = &mesh.vertices[ids[0] as usize];
                let b = &mesh.vertices[ids[1] as usize];
                let c = &mesh.vertices[ids[2] as usize];
                let e1 = b.position - a.position;
                let e2 = c.position - a.position;
                if e1.cross(e2).length_squared() < 1e-12 {
                    continue;
                }
                let n = (a.normal.truncate() + b.normal.truncate() + c.normal.truncate())
                    .try_normalize()
                    .unwrap_or(e1.cross(e2).normalize());
                let col = Vec3::new(a.color[0] as f32, a.color[1] as f32, a.color[2] as f32) / 255.;
                triangles.push(Triangle {
                    p: a.position,
                    e1,
                    e2,
                    n,
                    color: linear(col),
                    bounce: Vec3::ZERO,
                    bounds: Aabb {
                        min: a.position.min(b.position).min(c.position) - Vec3::splat(0.0001),
                        max: a.position.max(b.position).max(c.position) + Vec3::splat(0.0001),
                    },
                });
            }
        }
        let mut scene = Self {
            triangles,
            nodes: Vec::new(),
            lamps,
        };
        let n = scene.triangles.len();
        if n > 0 {
            scene.build(0, n);
        }
        // Cache low-frequency bounce radiance on source triangles. Primary
        // receiver shadows are still sampled at every baked vertex.
        let mut bounce = vec![Vec3::ZERO; n];
        let threads = std::thread::available_parallelism()
            .map_or(2, |n| n.get())
            .min(16);
        std::thread::scope(|scope| {
            for (part, values) in bounce.chunks_mut(n.div_ceil(threads).max(1)).enumerate() {
                let scene = &scene;
                scope.spawn(move || {
                    for (offset, value) in values.iter_mut().enumerate() {
                        let t = &scene.triangles[part * n.div_ceil(threads).max(1) + offset];
                        let p = t.p + (t.e1 + t.e2) / 3. + t.n * 0.035;
                        *value = t.color * scene.direct(p, t.n, false) * 0.60;
                    }
                });
            }
        });
        for (triangle, value) in scene.triangles.iter_mut().zip(bounce) {
            triangle.bounce = value;
        }
        scene
    }
    fn build(&mut self, start: usize, end: usize) -> usize {
        let mut bounds = Aabb {
            min: Vec3::splat(f32::INFINITY),
            max: Vec3::splat(f32::NEG_INFINITY),
        };
        for t in &self.triangles[start..end] {
            bounds.min = bounds.min.min(t.bounds.min);
            bounds.max = bounds.max.max(t.bounds.max);
        }
        let id = self.nodes.len();
        self.nodes.push(Node {
            bounds,
            start,
            end,
            children: None,
        });
        if end - start > 8 {
            let size = bounds.size();
            let axis = if size.x > size.y && size.x > size.z {
                0
            } else if size.y > size.z {
                1
            } else {
                2
            };
            let mid = (start + end) / 2;
            self.triangles[start..end].select_nth_unstable_by(mid - start, |a, b| {
                a.bounds.center()[axis].total_cmp(&b.bounds.center()[axis])
            });
            let l = self.build(start, mid);
            let r = self.build(mid, end);
            self.nodes[id].children = Some((l, r));
        }
        id
    }
    fn hit(&self, o: Vec3, d: Vec3, limit: f32) -> Option<(usize, f32)> {
        if self.nodes.is_empty() {
            return None;
        }
        let mut stack = [0usize; 128];
        let mut len = 1;
        let mut closest = limit;
        let mut result = None;
        while len > 0 {
            len -= 1;
            let node = &self.nodes[stack[len]];
            if node.bounds.ray(o, d, closest).is_none() {
                continue;
            }
            if let Some((l, r)) = node.children {
                stack[len] = l;
                stack[len + 1] = r;
                len += 2;
            } else {
                for i in node.start..node.end {
                    let t = &self.triangles[i];
                    let p = d.cross(t.e2);
                    let det = t.e1.dot(p);
                    if det.abs() < 1e-8 {
                        continue;
                    }
                    let inv = 1. / det;
                    let s = o - t.p;
                    let u = s.dot(p) * inv;
                    if !(0. ..=1.).contains(&u) {
                        continue;
                    }
                    let q = s.cross(t.e1);
                    let v = d.dot(q) * inv;
                    if v < 0. || u + v > 1. {
                        continue;
                    }
                    let distance = t.e2.dot(q) * inv;
                    if distance > 0.001 && distance < closest {
                        closest = distance;
                        result = Some((i, distance));
                    }
                }
            }
        }
        result
    }
    fn direct(&self, p: Vec3, n: Vec3, soft: bool) -> Vec3 {
        let mut light = Vec3::ZERO;
        let s = sun();
        let tangent = s.cross(Vec3::Y).normalize();
        let bitangent = s.cross(tangent);
        let samples = if soft { 8 } else { 1 };
        for k in 0..samples {
            let angle = k as f32 * 2.399963;
            let offset = if soft { 0.035 } else { 0. };
            let d = (s + offset * (tangent * angle.cos() + bitangent * angle.sin())).normalize();
            let cosine = n.dot(d).max(0.);
            if cosine > 0. && self.hit(p, d, 500.).is_none() {
                light += Vec3::new(2.8, 2.55, 2.15) * cosine / samples as f32;
            }
        }
        for lamp in &self.lamps {
            let delta = *lamp - p;
            let distance = delta.length();
            if distance > 0.03 && distance < 12. {
                let d = delta / distance;
                let cosine = n.dot(d).max(0.);
                if cosine > 0. && self.hit(p, d, distance - 0.025).is_none() {
                    let cutoff = (1. - (distance / 12.).powi(4)).max(0.).powi(2);
                    light += Vec3::new(1., 0.78, 0.53)
                        * (16. * cutoff * cosine / (distance * distance + 0.3));
                }
            }
        }
        light
    }
    pub fn shade(&self, position: Vec3, normal: Vec3, albedo: Color) -> Color {
        let n = normal.try_normalize().unwrap_or(Vec3::Y);
        let p = position + n * 0.035;
        let mut irradiance = self.direct(p, n, true);
        let tangent = n
            .cross(if n.y.abs() < 0.95 { Vec3::Y } else { Vec3::X })
            .normalize();
        let bitangent = n.cross(tangent);
        const SAMPLES: usize = 32;
        for i in 0..SAMPLES {
            let r = ((i as f32 + 0.5) / SAMPLES as f32).sqrt();
            let angle = i as f32 * 2.399963;
            let d = (tangent * (r * angle.cos())
                + bitangent * (r * angle.sin())
                + n * (1. - r * r).sqrt())
            .normalize();
            let contribution = if let Some((id, t)) = self.hit(p, d, 180.) {
                let hit = &self.triangles[id];
                let _ = t;
                hit.bounce + hit.color * Vec3::new(0.018, 0.022, 0.03)
            } else {
                Vec3::new(0.27, 0.39, 0.60) * (d.y * 0.4 + 0.6).max(0.08)
            };
            irradiance += contribution / SAMPLES as f32;
        }
        let rgb = display(linear(Vec3::new(albedo.r, albedo.g, albedo.b)) * irradiance);
        Color::new(rgb.x, rgb.y, rgb.z, albedo.a)
    }
    pub fn bake(&self, mesh: &mut Mesh) {
        let albedos: Vec<_> = mesh.vertices.iter().map(|v| v.color).collect();
        for v in &mut mesh.vertices {
            let c = v.color;
            v.color = self
                .shade(
                    v.position,
                    v.normal.truncate(),
                    Color::new(
                        c[0] as f32 / 255.,
                        c[1] as f32 / 255.,
                        c[2] as f32 / 255.,
                        c[3] as f32 / 255.,
                    ),
                )
                .into();
        }
        filter_irradiance(mesh, &albedos);
    }
}
// Suppress sampling/triangulation patterns on coplanar surfaces while keeping
// material boundaries, opposing faces and hard normals completely separate.
fn filter_irradiance(mesh: &mut Mesh, albedos: &[[u8; 4]]) {
    const R: f32 = 0.38;
    let cell = |p: Vec3| ((p / R).floor().as_ivec3()).to_array();
    let mut bins: std::collections::HashMap<([i32; 3], [u8; 4]), Vec<usize>> =
        std::collections::HashMap::new();
    for (i, v) in mesh.vertices.iter().enumerate() {
        bins.entry((cell(v.position), albedos[i]))
            .or_default()
            .push(i);
    }
    let source: Vec<_> = mesh.vertices.iter().map(|v| v.color).collect();
    let mut output = source.clone();
    for (i, v) in mesh.vertices.iter().enumerate() {
        let n = v.normal.truncate().normalize_or_zero();
        let c = cell(v.position);
        let mut sum = Vec3::ZERO;
        let mut weight = 0.;
        for x in -1..=1 {
            for y in -1..=1 {
                for z in -1..=1 {
                    if let Some(candidates) =
                        bins.get(&([c[0] + x, c[1] + y, c[2] + z], albedos[i]))
                    {
                        for &j in candidates {
                            let other = &mesh.vertices[j];
                            let delta = other.position - v.position;
                            let distance = delta.length_squared();
                            if distance > R * R
                                || delta.dot(n).abs() > 0.005
                                || n.dot(other.normal.truncate().normalize_or_zero()) < 0.995
                            {
                                continue;
                            }
                            let w = (-distance / (R * R * 0.55)).exp();
                            let rgb = Vec3::new(
                                source[j][0] as f32,
                                source[j][1] as f32,
                                source[j][2] as f32,
                            ) / 255.;
                            sum += linear(rgb) * w;
                            weight += w;
                        }
                    }
                }
            }
        }
        if weight > 0. {
            let rgb = (sum / weight).to_array().map(|v| {
                if v <= 0.0031308 {
                    v * 12.92
                } else {
                    1.055 * v.powf(1. / 2.4) - 0.055
                }
            });
            for k in 0..3 {
                output[i][k] = (rgb[k] * 255.).round().clamp(0., 255.) as u8;
            }
        }
    }
    for (v, color) in mesh.vertices.iter_mut().zip(output) {
        v.color = color;
    }
}
/// Split only large triangles. Detailed assets keep their original geometry.
/// Barycentric interpolation preserves normals/albedo and does not round edges.
pub fn subdivide(mesh: &Mesh, max_edge: f32) -> Vec<Mesh> {
    let mut out = Vec::new();
    let mut current = Mesh {
        vertices: Vec::new(),
        indices: Vec::new(),
        texture: None,
    };
    fn emit(a: Vertex, b: Vertex, c: Vertex, limit: f32, current: &mut Mesh, out: &mut Vec<Mesh>) {
        let edges = [
            a.position.distance_squared(b.position),
            b.position.distance_squared(c.position),
            c.position.distance_squared(a.position),
        ];
        let axis = if edges[0] >= edges[1] && edges[0] >= edges[2] {
            0
        } else if edges[1] >= edges[2] {
            1
        } else {
            2
        };
        if edges[axis] > limit * limit
            && (b.position - a.position)
                .cross(c.position - a.position)
                .length()
                > limit * limit * 0.6
        {
            let (a, b, c) = match axis {
                0 => (a, b, c),
                1 => (b, c, a),
                _ => (c, a, b),
            };
            let mut m = a;
            m.position = (a.position + b.position) * 0.5;
            m.uv = (a.uv + b.uv) * 0.5;
            m.normal = (a.normal + b.normal) * 0.5;
            for i in 0..4 {
                m.color[i] = ((a.color[i] as u16 + b.color[i] as u16) / 2) as u8;
            }
            emit(a, m, c, limit, current, out);
            emit(m, b, c, limit, current, out);
            return;
        }
        if current.vertices.len() + 3 > 60000 {
            out.push(std::mem::replace(
                current,
                Mesh {
                    vertices: Vec::new(),
                    indices: Vec::new(),
                    texture: None,
                },
            ));
        }
        let start = current.vertices.len() as u16;
        current.vertices.extend([a, b, c]);
        current.indices.extend([start, start + 1, start + 2]);
    }
    let mut retained = Mesh {
        vertices: mesh.vertices.clone(),
        indices: Vec::new(),
        texture: None,
    };
    for f in mesh.indices.chunks_exact(3) {
        let a = mesh.vertices[f[0] as usize];
        let b = mesh.vertices[f[1] as usize];
        let c = mesh.vertices[f[2] as usize];
        // Wall/window contact shadows need denser sampling than broad terrain.
        let normal = (a.normal + b.normal + c.normal)
            .truncate()
            .try_normalize()
            .unwrap_or(Vec3::Y);
        let max_edge = if normal.y.abs() < 0.6 {
            max_edge.min(0.25)
        } else {
            max_edge
        };
        if a.position
            .distance(b.position)
            .max(b.position.distance(c.position))
            .max(c.position.distance(a.position))
            <= max_edge
        {
            retained.indices.extend_from_slice(f);
        } else {
            emit(a, b, c, max_edge, &mut current, &mut out);
        }
    }
    if !retained.indices.is_empty() {
        out.push(retained);
    }
    if !current.vertices.is_empty() {
        out.push(current);
    }
    out
}
pub fn write_meshes(path: &std::path::Path, meshes: &[Mesh]) -> Result<(), String> {
    use std::io::Write;
    let file = std::fs::File::create(path).map_err(|e| e.to_string())?;
    let mut out = flate2::write::GzEncoder::new(file, flate2::Compression::default());
    let result = (|| -> std::io::Result<()> {
        out.write_all(b"RDCITY03")?;
        out.write_all(&(meshes.len() as u32).to_le_bytes())?;
        for mesh in meshes {
            let mut lo = Vec3::splat(f32::INFINITY);
            let mut hi = -lo;
            for v in &mesh.vertices {
                lo = lo.min(v.position);
                hi = hi.max(v.position);
            }
            for f in lo.to_array().into_iter().chain(hi.to_array()) {
                out.write_all(&f.to_le_bytes())?;
            }
            out.write_all(&(mesh.vertices.len() as u32).to_le_bytes())?;
            out.write_all(&(mesh.indices.len() as u32).to_le_bytes())?;
            for v in &mesh.vertices {
                for f in v.position.to_array() {
                    out.write_all(&f.to_le_bytes())?;
                }
                out.write_all(&v.color)?;
            }
            for i in &mesh.indices {
                out.write_all(&i.to_le_bytes())?;
            }
        }
        out.finish()?;
        Ok(())
    })();
    result.map_err(|e| e.to_string())
}
#[cfg(test)]
mod tests {
    use super::*;
    use crate::scene_lighting::SceneLighting;
    #[test]
    fn compact_bake_round_trips_without_relighting() {
        let mesh =
            SceneLighting::range().cube_mesh(Vec3::ZERO, Vec3::ONE, Color::new(0.6, 0.4, 0.2, 1.));
        let path =
            std::env::temp_dir().join(format!("rd-lighting-roundtrip-{}.bin", std::process::id()));
        write_meshes(&path, std::slice::from_ref(&mesh)).unwrap();
        let bytes = std::fs::read(&path).unwrap();
        std::fs::remove_file(path).unwrap();
        let decoded = crate::city_level::decode_meshes(&bytes).unwrap();
        for (a, b) in mesh.vertices.iter().zip(&decoded[0].mesh.vertices) {
            assert_eq!(a.position, b.position);
            assert_eq!(a.color, b.color);
        }
        assert_eq!(mesh.indices, decoded[0].mesh.indices);
    }
    #[test]
    fn roof_blocks_sun_and_sky() {
        let roof = SceneLighting::range().cube_mesh(
            Vec3::new(0., 3., 0.),
            Vec3::new(20., 0.3, 20.),
            Color::new(0.5, 0.5, 0.5, 1.),
        );
        let scene = BakeScene::new(&[roof], vec![]);
        let shaded = scene.shade(Vec3::ZERO, Vec3::Y, Color::new(0.7, 0.7, 0.7, 1.));
        let open = scene.shade(
            Vec3::new(40., 0., 0.),
            Vec3::Y,
            Color::new(0.7, 0.7, 0.7, 1.),
        );
        assert!(open.r > shaded.r + 0.25);
    }
    #[test]
    fn subdivision_covers_original_triangle() {
        let v = |p| Vertex::new2(p, Vec2::ZERO, Color::new(1., 1., 1., 1.));
        let m = Mesh {
            vertices: vec![v(Vec3::ZERO), v(Vec3::X * 4.), v(Vec3::Z * 4.)],
            indices: vec![0, 1, 2],
            texture: None,
        };
        let meshes = subdivide(&m, 0.7);
        let area: f32 = meshes
            .iter()
            .flat_map(|m| {
                m.indices.chunks_exact(3).map(|f| {
                    let a = m.vertices[f[0] as usize].position;
                    let b = m.vertices[f[1] as usize].position;
                    let c = m.vertices[f[2] as usize].position;
                    (b - a).cross(c - a).length() * 0.5
                })
            })
            .sum();
        assert!((area - 8.).abs() < 1e-5);
    }
}

/// Share identical baked vertices and discard unreferenced source vertices.
/// Color is part of the key so a lighting discontinuity cannot be welded away.
pub fn compact(mesh: &mut Mesh) {
    let mut unique = std::collections::HashMap::new();
    let mut vertices = Vec::new();
    for index in &mut mesh.indices {
        let v = mesh.vertices[*index as usize];
        let key = (
            v.position.to_array().map(f32::to_bits),
            v.normal.to_array().map(f32::to_bits),
            v.color,
        );
        *index = *unique.entry(key).or_insert_with(|| {
            let id = vertices.len() as u16;
            vertices.push(v);
            id
        });
    }
    mesh.vertices = vertices;
}
