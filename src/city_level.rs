//! Cedar Junction's authored static world, separate from deterministic gameplay.
//!
//! Meshes are decoded and lit once at startup. Spatial chunks are culled against
//! the world camera before being submitted through either rendering backend.
use crate::{
    draw::{facade::draw_static_mesh_transformed, BlendMode, Color, Mesh, StaticMesh, Vertex},
    scene_lighting::SceneLighting,
    sim::{Aabb, Block, Simulation},
};
use glam::{Mat4, Vec2, Vec3};
use serde_json::Value;
use std::path::{Path, PathBuf};

#[path = "city_visibility.rs"]
mod interior;
use interior::InteriorVisibility;

pub const CITY_FAR_PLANE: f32 = 400.;
const MAX_FILE_BYTES: usize = 768 * 1024 * 1024;
const MAX_CHUNKS: usize = 16_384;
const MAX_INSTANCES: usize = 262_144;
const MAX_VERTICES: usize = 60_000;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LevelSelection {
    CedarJunction,
    Range,
}
impl LevelSelection {
    /// Explicit CLI selection wins over the environment. Range-only capture
    /// replays retain their fixture coordinates unless a level is selected.
    pub fn from_options(args: &[String], environment: Option<&str>) -> Result<Self, String> {
        let explicit = args.iter().find_map(|arg| arg.strip_prefix("--level="));
        let range_fixture = args.iter().any(|arg| {
            arg.starts_with("--capture-sequence=")
                || matches!(arg.as_str(), "--capture-fixtures" | "--capture-supply")
        });
        match explicit.or(environment).unwrap_or(if range_fixture {
            "range"
        } else {
            "cedar_junction"
        }) {
            "cedar_junction" | "city" => Ok(Self::CedarJunction),
            "range" => Ok(Self::Range),
            other => Err(format!(
                "Unknown level {other:?}; use --level=cedar_junction or --level=range"
            )),
        }
    }
    pub fn scene_name(self) -> &'static str {
        match self {
            Self::CedarJunction => "cedar_junction",
            Self::Range => "vector_range_default_range",
        }
    }
}

pub struct CityChunk {
    pub bounds: Aabb,
    pub mesh: Mesh,
    pub instance: Option<InstanceMetadata>,
}

/// Runtime geometry is immutable and has a stable renderer resource identity.
/// CPU-only lighting tools retain the mutable `CityChunk` decoder below.
pub struct StaticCityChunk {
    pub bounds: Aabb,
    pub mesh: StaticMesh,
    pub instance: Option<InstanceMetadata>,
}

pub struct CityLevel {
    pub name: String,
    pub spawn_position: Vec3,
    pub spawn_yaw: f32,
    pub supply_position: Vec3,
    pub colliders: Vec<Block>,
    pub chunks: Vec<StaticCityChunk>,
    visibility: VisibilityBvh,
    interior_visibility: Option<InteriorVisibility>,
    mesh_source_path: PathBuf,
}

impl CityLevel {
    pub fn resolve(executable: &Path) -> PathBuf {
        let relative = Path::new("assets/levels/cedar_junction/level.json");
        let packaged = executable.parent().unwrap_or(Path::new(".")).join(relative);
        if packaged.exists() {
            packaged
        } else {
            // `cargo run` keeps assets in the source tree. Packaged builds use
            // their adjacent copy, including the verified updater version dir.
            let development = Path::new(env!("CARGO_MANIFEST_DIR")).join(relative);
            if development.exists() {
                development
            } else {
                packaged
            }
        }
    }

    pub fn load(path: &Path) -> Result<Self, String> {
        let result = (|| {
            let document = read_limited(path, 4 * 1024 * 1024)?;
            let value: Value = serde_json::from_slice(&document)
                .map_err(|error| format!("invalid level JSON: {error}"))?;
            if value["schema"].as_str() != Some("rust-duty-city/v1") {
                return Err("unsupported city schema (expected rust-duty-city/v1)".into());
            }
            let name = value["name"]
                .as_str()
                .filter(|name| !name.is_empty())
                .ok_or("missing level name")?
                .to_owned();
            let spawn_position = json_vec3(&value["spawn"]["position"], "spawn.position")?;
            let spawn_yaw =
                json_f32(&value["spawn"]["yaw_degrees"], "spawn.yaw_degrees")?.to_radians();
            let supply_position = if value["supply_position"].is_null() {
                spawn_position + Vec3::new(8., 0.15, 0.)
            } else {
                json_vec3(&value["supply_position"], "supply_position")?
            };
            let mesh_name = value["mesh_file"].as_str().ok_or("missing mesh_file")?;
            if mesh_name != "meshes.bin" {
                return Err("mesh_file must be meshes.bin beside level.json".into());
            }
            let colliders = value["colliders"]
                .as_array()
                .ok_or("missing colliders array")?;
            if colliders.is_empty() || colliders.len() > 100_000 {
                return Err("city must have 1..100000 colliders".into());
            }
            let colliders = colliders
                .iter()
                .enumerate()
                .map(|(index, value)| {
                    let bounds = Aabb {
                        min: json_vec3(&value["min"], "collider.min")?,
                        max: json_vec3(&value["max"], "collider.max")?,
                    };
                    if !bounds.min.cmplt(bounds.max).all() {
                        return Err(format!("collider {index} must have positive extents"));
                    }
                    let kind = match value.get("kind") {
                        Some(kind) => kind
                            .as_u64()
                            .filter(|kind| *kind <= u8::MAX as u64)
                            .ok_or_else(|| format!("collider {index} has invalid kind"))?
                            as u8,
                        None => 0,
                    };
                    Ok(Block { bounds, kind })
                })
                .collect::<Result<Vec<_>, String>>()?;
            let spawn_bounds = crate::sim::Player::default().bounds_at(spawn_position);
            if colliders
                .iter()
                .any(|block| spawn_bounds.overlaps(block.bounds))
            {
                return Err("spawn overlaps solid collision".into());
            }
            let baked = path.with_file_name("lighting.bin");
            let mut mesh_path = if baked.exists() {
                baked
            } else {
                path.with_file_name(mesh_name)
            };
            let meshes = read_limited(&mesh_path, MAX_FILE_BYTES)?;
            let mut geometry = decode_geometry(&meshes)?;
            // A stale coarse bake must not silently erase the ownership in a
            // freshly exported instance scene. Legacy manifests stay unchanged.
            if value["geometry_format"].as_str() == Some("RDCITY04")
                && !geometry.iter().any(|record| record.instance.is_some())
            {
                mesh_path = path.with_file_name(mesh_name);
                geometry = decode_geometry(&read_limited(&mesh_path, MAX_FILE_BYTES)?)?;
                if !geometry.iter().any(|record| record.instance.is_some()) {
                    return Err("RDCITY04 level has no authored instance metadata".into());
                }
            }
            let chunks = geometry
                .into_iter()
                .map(|record| {
                    Ok(StaticCityChunk {
                        bounds: record.bounds,
                        mesh: StaticMesh::new(record.vertices, record.indices, None)?,
                        instance: record.instance,
                    })
                })
                .collect::<Result<Vec<_>, String>>()?;
            let visibility = VisibilityBvh::new(
                chunks
                    .iter()
                    .map(|chunk| VisibilityItem {
                        bounds: chunk.bounds,
                        max_distance: chunk.instance.as_ref().map_or(0., |i| i.max_distance),
                    })
                    .collect(),
            );
            let interior_visibility = InteriorVisibility::from_manifest(&value, &chunks);
            Ok(Self {
                name,
                spawn_position,
                spawn_yaw,
                supply_position,
                colliders,
                chunks,
                visibility,
                interior_visibility,
                mesh_source_path: mesh_path,
            })
        })();
        result.map_err(|error: String| {
            format!(
                "City level {}: {error}. Use --level=range to open the test range.",
                path.display()
            )
        })
    }

    /// Actual file decoded by this load, including source fallback over a stale bake.
    pub fn mesh_source_path(&self) -> &Path {
        &self.mesh_source_path
    }

    pub fn install(&self, simulation: &mut Simulation) {
        simulation.install_level(self.colliders.clone(), self.spawn_position, self.spawn_yaw);
    }

    /// The same exact projection used by the camera preserves edge-of-view
    /// buildings even at widescreen aspect ratios or when the player leans.
    pub fn draw(&self, eye: Vec3, view_projection: Mat4) {
        self.visit_visible(eye, view_projection, |index| {
            draw_static_mesh_transformed(
                &self.chunks[index].mesh,
                Mat4::IDENTITY,
                BlendMode::Opaque,
            );
        });
    }

    /// Allocation-free visibility traversal used by rendering and CPU tests.
    /// Statistics describe candidate work, never measured GPU time or FPS.
    pub fn visit_visible(
        &self,
        eye: Vec3,
        view_projection: Mat4,
        visitor: impl FnMut(usize),
    ) -> VisibilityStats {
        let Some(interior) = &self.interior_visibility else {
            return self.visibility.visit(eye, view_projection, visitor);
        };
        let frame = interior.frame(eye, &Frustum::new(view_projection));
        let mut visitor = visitor;
        let mut occluded = 0;
        let mut stats = self.visibility.visit(eye, view_projection, |index| {
            if interior.record_visible(index, &frame) {
                visitor(index);
            } else {
                occluded += 1;
            }
        });
        stats.visible_records -= occluded;
        stats.occlusion_culled_records = occluded;
        stats.interior_occlusion_enabled = true;
        stats
    }
}

fn json_f32(value: &Value, label: &str) -> Result<f32, String> {
    value
        .as_f64()
        .map(|number| number as f32)
        .filter(|number| number.is_finite())
        .ok_or_else(|| format!("{label} must be a finite number"))
}

fn json_vec3(value: &Value, label: &str) -> Result<Vec3, String> {
    let values = value
        .as_array()
        .filter(|values| values.len() == 3)
        .ok_or_else(|| format!("{label} must contain three numbers"))?;
    Ok(Vec3::new(
        json_f32(&values[0], label)?,
        json_f32(&values[1], label)?,
        json_f32(&values[2], label)?,
    ))
}

fn read_limited(path: &Path, limit: usize) -> Result<Vec<u8>, String> {
    use std::io::Read;
    let file = std::fs::File::open(path).map_err(|error| format!("{}: {error}", path.display()))?;
    let mut bytes = Vec::new();
    file.take(limit as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|error| format!("{}: {error}", path.display()))?;
    if bytes.len() > limit {
        return Err(format!("{} exceeds {limit} bytes", path.display()));
    }
    Ok(bytes)
}

struct Reader<'a> {
    bytes: &'a [u8],
    offset: usize,
}
impl<'a> Reader<'a> {
    fn take<const N: usize>(&mut self) -> Result<[u8; N], String> {
        let end = self.offset.checked_add(N).ok_or("mesh offset overflow")?;
        let bytes = self
            .bytes
            .get(self.offset..end)
            .ok_or("truncated city mesh file")?;
        self.offset = end;
        Ok(bytes.try_into().unwrap())
    }
    fn u32(&mut self) -> Result<usize, String> {
        Ok(u32::from_le_bytes(self.take()?) as usize)
    }
    fn f32(&mut self) -> Result<f32, String> {
        let value = f32::from_le_bytes(self.take()?);
        if value.is_finite() {
            Ok(value)
        } else {
            Err("non-finite city vertex or bound".into())
        }
    }
    fn vec3(&mut self) -> Result<Vec3, String> {
        Ok(Vec3::new(self.f32()?, self.f32()?, self.f32()?))
    }
}

/// Authored identity survives subdivision/baking; multiple records may belong to
/// the same source instance. A legacy spatial batch has no instance metadata.
#[derive(Clone, Debug, PartialEq)]
pub struct InstanceMetadata {
    pub id: u32,
    pub asset: String,
    pub building: Option<String>,
    /// Zero disables additional distance culling. Only explicitly classified
    /// small props receive a cutoff; walls, doors and roads never infer one.
    pub max_distance: f32,
}

#[derive(Debug)]
pub struct CityGeometry {
    pub bounds: Aabb,
    pub vertices: Vec<Vertex>,
    pub indices: Vec<u32>,
    pub instance: Option<InstanceMetadata>,
}

impl CityGeometry {
    pub fn from_chunk(chunk: CityChunk) -> Self {
        Self {
            bounds: chunk.bounds,
            vertices: chunk.mesh.vertices,
            indices: chunk.mesh.indices.into_iter().map(u32::from).collect(),
            instance: chunk.instance,
        }
    }
}

pub fn decode_geometry(bytes: &[u8]) -> Result<Vec<CityGeometry>, String> {
    decode_geometry_mode(bytes, false)
}
pub fn decode_geometry_unlit(bytes: &[u8]) -> Result<Vec<CityGeometry>, String> {
    decode_geometry_mode(bytes, true)
}

/// Legacy CPU tools use u16 meshes. Wide records are split by whole triangles,
/// with source identity copied to every piece, never by truncating an index.
pub fn decode_meshes(bytes: &[u8]) -> Result<Vec<CityChunk>, String> {
    Ok(split_for_cpu(decode_geometry(bytes)?))
}
pub fn decode_meshes_unlit(bytes: &[u8]) -> Result<Vec<CityChunk>, String> {
    Ok(split_for_cpu(decode_geometry_unlit(bytes)?))
}
fn split_for_cpu(geometry: Vec<CityGeometry>) -> Vec<CityChunk> {
    let mut out = Vec::new();
    for record in geometry {
        if record.vertices.len() <= MAX_VERTICES && record.indices.len() <= 360_000 {
            out.push(CityChunk {
                bounds: record.bounds,
                mesh: Mesh {
                    vertices: record.vertices,
                    indices: record.indices.into_iter().map(|i| i as u16).collect(),
                    texture: None,
                },
                instance: record.instance,
            });
            continue;
        }
        let mut remap = std::collections::HashMap::<u32, u16>::new();
        let mut mesh = Mesh {
            vertices: Vec::new(),
            indices: Vec::new(),
            texture: None,
        };
        for triangle in record.indices.as_chunks::<3>().0 {
            if mesh.vertices.len() + 3 > MAX_VERTICES || mesh.indices.len() + 3 > 360_000 {
                out.push(CityChunk {
                    bounds: geometry_bounds(&mesh.vertices),
                    mesh,
                    instance: record.instance.clone(),
                });
                mesh = Mesh {
                    vertices: Vec::new(),
                    indices: Vec::new(),
                    texture: None,
                };
                remap.clear();
            }
            for &index in triangle {
                let next = mesh.vertices.len() as u16;
                let mapped = *remap.entry(index).or_insert_with(|| {
                    mesh.vertices.push(record.vertices[index as usize]);
                    next
                });
                mesh.indices.push(mapped);
            }
        }
        if !mesh.indices.is_empty() {
            out.push(CityChunk {
                bounds: geometry_bounds(&mesh.vertices),
                mesh,
                instance: record.instance,
            });
        }
    }
    out
}

pub fn geometry_bounds(vertices: &[Vertex]) -> Aabb {
    let mut bounds = Aabb {
        min: Vec3::splat(f32::INFINITY),
        max: Vec3::splat(f32::NEG_INFINITY),
    };
    for vertex in vertices {
        bounds.min = bounds.min.min(vertex.position);
        bounds.max = bounds.max.max(vertex.position);
    }
    bounds
}

fn parse_instance(value: &Value) -> Result<Option<InstanceMetadata>, String> {
    if value.is_null() {
        return Ok(None);
    }
    let id = value["id"]
        .as_u64()
        .filter(|id| *id <= u32::MAX as u64)
        .ok_or("invalid city instance id")? as u32;
    let asset = value["asset"]
        .as_str()
        .filter(|s| !s.is_empty() && s.len() <= 512)
        .ok_or("invalid city instance asset")?
        .to_owned();
    let building = if value["building"].is_null() {
        None
    } else {
        Some(
            value["building"]
                .as_str()
                .filter(|s| !s.is_empty() && s.len() <= 128)
                .ok_or("invalid city instance building")?
                .to_owned(),
        )
    };
    let max_distance = if value["max_distance"].is_null() {
        0.
    } else {
        json_f32(&value["max_distance"], "instance.max_distance")?
    };
    if !(0. ..=CITY_FAR_PLANE).contains(&max_distance) {
        return Err("invalid city instance distance".into());
    }
    Ok(Some(InstanceMetadata {
        id,
        asset,
        building,
        max_distance,
    }))
}

fn decode_geometry_mode(bytes: &[u8], unlit: bool) -> Result<Vec<CityGeometry>, String> {
    if bytes.len() > MAX_FILE_BYTES {
        return Err("city mesh file is too large".into());
    }
    let inflated;
    let bytes = if bytes.starts_with(&[0x1f, 0x8b]) {
        use std::io::Read;
        let mut output = Vec::new();
        flate2::read::MultiGzDecoder::new(bytes)
            .take(MAX_FILE_BYTES as u64 + 1)
            .read_to_end(&mut output)
            .map_err(|error| format!("invalid compressed city mesh: {error}"))?;
        if output.len() > MAX_FILE_BYTES {
            return Err("decompressed city mesh file is too large".into());
        }
        inflated = output;
        inflated.as_slice()
    } else {
        bytes
    };
    let mut reader = Reader { bytes, offset: 0 };
    let magic = reader.take::<8>()?;
    let modern = magic == *b"RDCITY04";
    let flags = if modern { reader.u32()? } else { 0 };
    if flags > 3 || flags == 2 {
        return Err("invalid city geometry flags".into());
    }
    let compact = magic == *b"RDCITY03" || modern && flags & 2 != 0;
    let baked = compact || magic == *b"RDCITY02" || modern && flags & 1 != 0;
    if !modern && !baked && magic != *b"RDCITY01" {
        return Err("invalid city mesh magic".into());
    }
    let mut instances = Vec::new();
    if modern {
        let length = reader.u32()?;
        if length > 32 * 1024 * 1024 {
            return Err("city metadata exceeds size limit".into());
        }
        let end = reader
            .offset
            .checked_add(length)
            .ok_or("city metadata offset overflow")?;
        let metadata: Value = serde_json::from_slice(
            bytes
                .get(reader.offset..end)
                .ok_or("truncated city metadata")?,
        )
        .map_err(|e| format!("invalid city metadata: {e}"))?;
        reader.offset = end;
        let values = metadata
            .as_array()
            .filter(|v| !v.is_empty() && v.len() <= MAX_INSTANCES)
            .ok_or("invalid city metadata count")?;
        instances = values
            .iter()
            .map(parse_instance)
            .collect::<Result<Vec<_>, _>>()?;
    }
    let count = reader.u32()?;
    if count == 0
        || count > if modern { MAX_INSTANCES } else { MAX_CHUNKS }
        || modern && count != instances.len()
    {
        return Err("invalid city chunk or instance count".into());
    }
    let lighting = SceneLighting::range();
    let mut chunks = Vec::with_capacity(count);
    let mut instances = instances.into_iter();
    for chunk_index in 0..count {
        let declared_bounds = Aabb {
            min: reader.vec3()?,
            max: reader.vec3()?,
        };
        if !declared_bounds.min.cmple(declared_bounds.max).all() {
            return Err(format!("invalid bounds for chunk {chunk_index}"));
        }
        let vertex_count = reader.u32()?;
        let index_count = reader.u32()?;
        if vertex_count == 0
            || vertex_count > if modern { 4_000_000 } else { MAX_VERTICES }
            || index_count == 0
            || index_count > if modern { 12_000_000 } else { 360_000 }
            || !index_count.is_multiple_of(3)
        {
            return Err(format!("invalid geometry count for chunk {chunk_index}"));
        }
        let required =
            vertex_count * if compact { 16 } else { 40 } + index_count * if modern { 4 } else { 2 };
        if required > bytes.len() - reader.offset {
            return Err("truncated city geometry".into());
        }
        let mut vertices = Vec::with_capacity(vertex_count);
        for _ in 0..vertex_count {
            let position = reader.vec3()?;
            let normal = if compact { Vec3::ZERO } else { reader.vec3()? };
            let rgba = if compact {
                reader.take::<4>()?.map(|c| c as f32 / 255.)
            } else {
                [reader.f32()?, reader.f32()?, reader.f32()?, reader.f32()?]
            };
            if !position
                .cmpge(declared_bounds.min - Vec3::splat(0.01))
                .all()
                || !position
                    .cmple(declared_bounds.max + Vec3::splat(0.01))
                    .all()
            {
                return Err(format!("vertex outside chunk {chunk_index} bounds"));
            }
            if rgba.iter().any(|c| !(0. ..=1.).contains(c)) {
                return Err("city vertex color outside 0..1".into());
            }
            let color = Color::new(rgba[0], rgba[1], rgba[2], rgba[3]);
            let mut vertex = Vertex::new2(
                position,
                Vec2::ZERO,
                if baked || unlit {
                    color
                } else {
                    lighting.shade(color, normal)
                },
            );
            vertex.normal = normal.extend(0.);
            vertices.push(vertex);
        }
        let mut indices = Vec::with_capacity(index_count);
        for _ in 0..index_count {
            let index = if modern {
                reader.u32()? as u32
            } else {
                u16::from_le_bytes(reader.take()?) as u32
            };
            if index as usize >= vertex_count {
                return Err(format!("index outside chunk {chunk_index} vertices"));
            }
            indices.push(index);
        }
        // Use actual geometry for culling, including accepted rounding slack.
        let bounds = geometry_bounds(&vertices);
        chunks.push(CityGeometry {
            bounds,
            vertices,
            indices,
            instance: if modern {
                instances.next().expect("metadata count checked")
            } else {
                None
            },
        });
    }
    if reader.offset != bytes.len() {
        return Err("trailing data after city chunks".into());
    }
    Ok(chunks)
}

/// Write prelit geometry without discarding authored identity or narrowing any
/// index. Lighting tools call this after subdivision/compaction, not the legacy
/// RDCITY03 writer, whenever their source contains instance metadata.
pub fn write_geometry(path: &Path, geometry: &[CityGeometry]) -> Result<(), String> {
    use std::io::Write;
    if geometry.is_empty() || geometry.len() > MAX_INSTANCES {
        return Err("invalid city instance count".into());
    }
    if geometry
        .iter()
        .filter_map(|g| g.instance.as_ref())
        .any(|i| !i.max_distance.is_finite())
    {
        return Err("invalid city instance distance".into());
    }
    let metadata: Vec<_> = geometry.iter().map(|g| match &g.instance {
        Some(i) => serde_json::json!({"id":i.id,"asset":i.asset,"building":i.building,"max_distance":i.max_distance}),
        None => Value::Null,
    }).collect();
    for value in &metadata {
        parse_instance(value)?;
    }
    let metadata = serde_json::to_vec(&metadata).map_err(|e| e.to_string())?;
    if metadata.len() > 32 * 1024 * 1024 {
        return Err("city metadata exceeds size limit".into());
    }
    let mut decoded_bytes = 20 + metadata.len();
    let mut bounds = Vec::with_capacity(geometry.len());
    for g in geometry {
        if g.vertices.is_empty()
            || g.vertices.len() > 4_000_000
            || g.indices.is_empty()
            || g.indices.len() > 12_000_000
            || !g.indices.len().is_multiple_of(3)
        {
            return Err("invalid city geometry count".into());
        }
        if g.vertices.iter().any(|v| !v.position.is_finite()) {
            return Err("non-finite city vertex".into());
        }
        if g.indices.iter().any(|&i| i as usize >= g.vertices.len()) {
            return Err("city index outside vertices".into());
        }
        decoded_bytes += 32 + g.vertices.len() * 16 + g.indices.len() * 4;
        if decoded_bytes > MAX_FILE_BYTES {
            return Err("city mesh file is too large".into());
        }
        bounds.push(geometry_bounds(&g.vertices));
    }
    // All framing, metadata and geometry is validated before touching the
    // destination. Stream the bake; never allocate or decode a second scene.
    let temporary = path.with_extension("bin.tmp");
    let file = std::fs::File::create(&temporary).map_err(|e| e.to_string())?;
    let encoder = flate2::write::GzEncoder::new(file, flate2::Compression::default());
    let mut out = std::io::BufWriter::with_capacity(64 * 1024, encoder);
    let write_result = (|| -> std::io::Result<()> {
        out.write_all(b"RDCITY04")?;
        out.write_all(&3_u32.to_le_bytes())?;
        out.write_all(&(metadata.len() as u32).to_le_bytes())?;
        out.write_all(&metadata)?;
        out.write_all(&(geometry.len() as u32).to_le_bytes())?;
        for (g, bounds) in geometry.iter().zip(bounds) {
            for f in bounds
                .min
                .to_array()
                .into_iter()
                .chain(bounds.max.to_array())
            {
                out.write_all(&f.to_le_bytes())?;
            }
            out.write_all(&(g.vertices.len() as u32).to_le_bytes())?;
            out.write_all(&(g.indices.len() as u32).to_le_bytes())?;
            for v in &g.vertices {
                for f in v.position.to_array() {
                    out.write_all(&f.to_le_bytes())?;
                }
                out.write_all(&v.color)?;
            }
            for &i in &g.indices {
                out.write_all(&i.to_le_bytes())?;
            }
        }
        Ok(())
    })();
    write_result.map_err(|e| e.to_string())?;
    let file = out
        .into_inner()
        .map_err(|e| e.to_string())?
        .finish()
        .map_err(|e| e.to_string())?;
    if file.metadata().map_err(|e| e.to_string())?.len() > MAX_FILE_BYTES as u64 {
        return Err("compressed city mesh file is too large".into());
    }
    drop(file);
    std::fs::rename(temporary, path).map_err(|e| e.to_string())
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct VisibilityStats {
    pub total_records: usize,
    pub visited_nodes: usize,
    pub tested_records: usize,
    pub distance_culled_records: usize,
    pub occlusion_culled_records: usize,
    pub interior_occlusion_enabled: bool,
    pub visible_records: usize,
}

#[derive(Clone, Copy)]
struct VisibilityItem {
    bounds: Aabb,
    max_distance: f32,
}
struct BvhNode {
    bounds: Aabb,
    range: std::ops::Range<usize>,
    children: Option<(usize, usize)>,
}
/// Immutable median-split BVH. Large/straddling instances live in exactly one
/// leaf, so no cell assignment can clip a building or duplicate submissions.
struct VisibilityBvh {
    nodes: Vec<BvhNode>,
    order: Vec<usize>,
    items: Vec<VisibilityItem>,
}
impl VisibilityBvh {
    fn new(items: Vec<VisibilityItem>) -> Self {
        let mut bvh = Self {
            order: (0..items.len()).collect(),
            nodes: Vec::new(),
            items,
        };
        if !bvh.order.is_empty() {
            bvh.build(0..bvh.order.len());
        }
        bvh
    }
    fn build(&mut self, range: std::ops::Range<usize>) -> usize {
        let mut bounds = self.items[self.order[range.start]].bounds;
        for &i in &self.order[range.clone()] {
            bounds.min = bounds.min.min(self.items[i].bounds.min);
            bounds.max = bounds.max.max(self.items[i].bounds.max);
        }
        let index = self.nodes.len();
        self.nodes.push(BvhNode {
            bounds,
            range: range.clone(),
            children: None,
        });
        if range.len() > 8 {
            let size = bounds.max - bounds.min;
            let axis = if size.x >= size.y && size.x >= size.z {
                0
            } else if size.y >= size.z {
                1
            } else {
                2
            };
            let items = &self.items;
            self.order[range.clone()].sort_unstable_by(|&a, &b| {
                items[a].bounds.center()[axis]
                    .total_cmp(&items[b].bounds.center()[axis])
                    .then(a.cmp(&b))
            });
            let middle = range.start + range.len() / 2;
            let left = self.build(range.start..middle);
            let right = self.build(middle..range.end);
            self.nodes[index].children = Some((left, right));
        }
        index
    }
    fn visit(&self, eye: Vec3, matrix: Mat4, mut visitor: impl FnMut(usize)) -> VisibilityStats {
        let mut stats = VisibilityStats {
            total_records: self.items.len(),
            ..VisibilityStats::default()
        };
        if !self.nodes.is_empty() {
            self.visit_node(0, eye, &Frustum::new(matrix), &mut stats, &mut visitor);
        }
        stats
    }
    fn visit_node(
        &self,
        index: usize,
        eye: Vec3,
        frustum: &Frustum,
        stats: &mut VisibilityStats,
        visitor: &mut impl FnMut(usize),
    ) {
        stats.visited_nodes += 1;
        let node = &self.nodes[index];
        if !within_distance(node.bounds, eye, CITY_FAR_PLANE) || !frustum.intersects(node.bounds) {
            return;
        }
        if let Some((mut left, mut right)) = node.children {
            let distance = |i: usize| {
                eye.distance_squared(eye.clamp(self.nodes[i].bounds.min, self.nodes[i].bounds.max))
            };
            if distance(right) < distance(left) {
                std::mem::swap(&mut left, &mut right);
            }
            self.visit_node(left, eye, frustum, stats, visitor);
            self.visit_node(right, eye, frustum, stats, visitor);
        } else {
            for &i in &self.order[node.range.clone()] {
                stats.tested_records += 1;
                let item = self.items[i];
                let distance = if item.max_distance > 0. {
                    item.max_distance
                } else {
                    CITY_FAR_PLANE
                };
                if !within_distance(item.bounds, eye, distance) {
                    stats.distance_culled_records += 1;
                    continue;
                }
                if frustum.intersects(item.bounds) {
                    stats.visible_records += 1;
                    visitor(i);
                }
            }
        }
    }
}
struct Frustum {
    planes: [glam::Vec4; 6],
}
impl Frustum {
    fn new(matrix: Mat4) -> Self {
        let rows = matrix.transpose();
        Self {
            planes: [
                rows.w_axis + rows.x_axis,
                rows.w_axis - rows.x_axis,
                rows.w_axis + rows.y_axis,
                rows.w_axis - rows.y_axis,
                rows.w_axis + rows.z_axis,
                rows.w_axis - rows.z_axis,
            ],
        }
    }
    fn intersects(&self, bounds: Aabb) -> bool {
        self.intersects_planes(bounds, false)
    }
    /// A visible ray may cross an opening before reaching the camera near
    /// plane. Rejecting that opening would incorrectly hide geometry beyond it.
    fn intersects_portal(&self, bounds: Aabb) -> bool {
        self.intersects_planes(bounds, true)
    }
    fn intersects_planes(&self, bounds: Aabb, omit_near: bool) -> bool {
        self.planes.iter().enumerate().all(|(index, p)| {
            if omit_near && index == 4 {
                return true;
            }
            let vertex = Vec3::new(
                if p.x >= 0. {
                    bounds.max.x
                } else {
                    bounds.min.x
                },
                if p.y >= 0. {
                    bounds.max.y
                } else {
                    bounds.min.y
                },
                if p.z >= 0. {
                    bounds.max.z
                } else {
                    bounds.min.z
                },
            );
            // Reject only proven outside bounds; keep numerical edge cases.
            (p.truncate().dot(vertex) + p.w).partial_cmp(&-0.0001) != Some(std::cmp::Ordering::Less)
        })
    }
}
fn within_distance(bounds: Aabb, eye: Vec3, distance: f32) -> bool {
    eye.distance_squared(eye.clamp(bounds.min, bounds.max)) <= distance * distance
}

pub fn chunk_visible(bounds: Aabb, eye: Vec3, view_projection: Mat4) -> bool {
    within_distance(bounds, eye, CITY_FAR_PLANE) && Frustum::new(view_projection).intersects(bounds)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        action::ActionEventKind,
        settings::Settings,
        sim::{Input, FIXED_DT},
    };

    fn v4_triangle(metadata: Value, flags: u32) -> Vec<u8> {
        let metadata = serde_json::to_vec(&metadata).unwrap();
        let mut bytes = b"RDCITY04".to_vec();
        bytes.extend(flags.to_le_bytes());
        bytes.extend((metadata.len() as u32).to_le_bytes());
        bytes.extend(metadata);
        bytes.extend(1_u32.to_le_bytes());
        let old = triangle();
        bytes.extend(&old[12..old.len() - 6]);
        for index in [0_u32, 1, 2] {
            bytes.extend(index.to_le_bytes());
        }
        bytes
    }

    #[test]
    fn instance_format_preserves_identity_geometry_and_rejects_bad_metadata() {
        let metadata = serde_json::json!([{"id":17,"asset":"b16_takeaway_coffee_cup","building":"B01","max_distance":120.}]);
        let bytes = v4_triangle(metadata.clone(), 0);
        let decoded = decode_geometry_unlit(&bytes).unwrap();
        let old = decode_geometry_unlit(&triangle()).unwrap();
        assert_eq!(decoded[0].vertices, old[0].vertices);
        assert_eq!(decoded[0].indices, old[0].indices);
        assert_eq!(decoded[0].instance.as_ref().unwrap().id, 17);
        assert_eq!(
            decoded[0].instance.as_ref().unwrap().building.as_deref(),
            Some("B01")
        );
        assert!(
            old[0].instance.is_none(),
            "legacy batches are never mislabeled as instances"
        );
        for flags in [2, 4, u32::MAX] {
            assert!(decode_geometry(&v4_triangle(metadata.clone(), flags)).is_err());
        }
        for broken in [
            serde_json::json!([]),
            serde_json::json!([{"id":-1,"asset":"x"}]),
            serde_json::json!([{"id":0,"asset":""}]),
            serde_json::json!([{"id":0,"asset":"x","max_distance":-1}]),
            serde_json::json!([{"id":0,"asset":"x","max_distance":401}]),
        ] {
            assert!(decode_geometry(&v4_triangle(broken, 0)).is_err());
        }
        let mut bad_index = bytes;
        let end = bad_index.len();
        bad_index[end - 4..].copy_from_slice(&3_u32.to_le_bytes());
        assert!(decode_geometry(&bad_index)
            .unwrap_err()
            .contains("index outside"));
    }

    #[test]
    fn wide_indices_survive_bake_roundtrip_and_legacy_cpu_splitting() {
        let mut vertices = Vec::new();
        for i in 0..65_538 {
            vertices.push(Vertex::new2(
                Vec3::new(i as f32, (i % 3) as f32, 0.),
                Vec2::ZERO,
                Color::WHITE,
            ));
        }
        let geometry = CityGeometry {
            bounds: geometry_bounds(&vertices),
            vertices,
            indices: (0..65_538_u32).collect(),
            instance: Some(InstanceMetadata {
                id: 9,
                asset: "synthetic-wide-asset".into(),
                building: None,
                max_distance: 0.,
            }),
        };
        let path = std::env::temp_dir().join(format!(
            "rust-duty-wide-city-{}-{}.bin",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        write_geometry(&path, std::slice::from_ref(&geometry)).unwrap();
        let bytes = std::fs::read(&path).unwrap();
        let _ = std::fs::remove_file(path);
        let decoded = decode_geometry(&bytes).unwrap();
        assert_eq!(decoded[0].indices.last(), Some(&65_537));
        assert_eq!(decoded[0].vertices, geometry.vertices);
        assert_eq!(decoded[0].instance, geometry.instance);
        let split = decode_meshes(&bytes).unwrap();
        assert!(split.len() > 1);
        let restored: Vec<_> = split
            .iter()
            .flat_map(|c| {
                c.mesh
                    .indices
                    .iter()
                    .map(|&i| c.mesh.vertices[i as usize].position)
            })
            .collect();
        let original: Vec<_> = geometry
            .indices
            .iter()
            .map(|&i| geometry.vertices[i as usize].position)
            .collect();
        assert_eq!(
            restored, original,
            "every indexed vertex of every triangle survives"
        );
        assert!(split
            .iter()
            .all(|c| c.instance == geometry.instance && c.mesh.vertices.len() <= MAX_VERTICES));
    }

    fn corner_reference(bounds: Aabb, matrix: Mat4) -> bool {
        let mut clip = Vec::new();
        for x in [bounds.min.x, bounds.max.x] {
            for y in [bounds.min.y, bounds.max.y] {
                for z in [bounds.min.z, bounds.max.z] {
                    clip.push(matrix * Vec3::new(x, y, z).extend(1.));
                }
            }
        }
        !(clip.iter().all(|p| p.x < -p.w)
            || clip.iter().all(|p| p.x > p.w)
            || clip.iter().all(|p| p.y < -p.w)
            || clip.iter().all(|p| p.y > p.w)
            || clip.iter().all(|p| p.z < -p.w)
            || clip.iter().all(|p| p.z > p.w))
    }

    #[test]
    fn streaming_writer_validates_before_touching_existing_bake() {
        let path = std::env::temp_dir().join(format!(
            "rust-duty-city-writer-{}-{}.bin",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::write(&path, b"previous bake").unwrap();
        for case in 0..5 {
            let mut geometry = decode_geometry_unlit(&triangle()).unwrap();
            match case {
                0 => geometry[0].indices[2] = 3,
                1 => geometry[0].vertices[0].position.x = f32::NAN,
                2 => geometry[0].indices.pop().map(|_| ()).unwrap(),
                3 | 4 => {
                    geometry[0].instance = Some(InstanceMetadata {
                        id: 1,
                        asset: if case == 3 {
                            "fixture".into()
                        } else {
                            "é".repeat(257)
                        },
                        building: None,
                        max_distance: if case == 3 { f32::NAN } else { 0. },
                    })
                }
                _ => unreachable!(),
            }
            assert!(write_geometry(&path, &geometry).is_err());
            assert_eq!(std::fs::read(&path).unwrap(), b"previous bake");
            assert!(
                !path.with_extension("bin.tmp").exists(),
                "invalid input never opens the temporary output"
            );
        }
        let mut geometry = Vec::new();
        for index in 0..3 {
            let mut record = decode_geometry_unlit(&triangle()).unwrap().pop().unwrap();
            record.instance = (index != 0).then(|| InstanceMetadata {
                id: index,
                asset: "fixture".into(),
                building: (index == 2).then(|| "B01".into()),
                max_distance: 0.,
            });
            geometry.push(record);
        }
        write_geometry(&path, &geometry).unwrap();
        let restored = decode_geometry(&std::fs::read(&path).unwrap()).unwrap();
        assert_eq!(restored.len(), geometry.len());
        for (written, read) in geometry.iter().zip(&restored) {
            assert_eq!(written.instance, read.instance);
            assert_eq!(written.indices, read.indices);
            for (a, b) in written.vertices.iter().zip(&read.vertices) {
                assert_eq!(a.position, b.position);
                assert_eq!(a.color, b.color, "compact prelit data is not relit");
            }
        }
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn bvh_matches_brute_force_for_wide_aspect_edges_and_camera_rotations() {
        let items: Vec<_> = (0..2048)
            .map(|i| {
                let center = Vec3::new(
                    ((i * 73) % 503) as f32 - 251.,
                    ((i * 11) % 43) as f32 - 5.,
                    ((i * 41) % 509) as f32 - 254.,
                );
                VisibilityItem {
                    bounds: Aabb::from_center(center, Vec3::splat(0.5 + (i % 7) as f32)),
                    max_distance: if i % 3 == 0 { 120. } else { 0. },
                }
            })
            .collect();
        let bvh = VisibilityBvh::new(items);
        let eye = Vec3::new(3., 1.7, -2.);
        for aspect in [0.75, 16. / 9., 32. / 9.] {
            for yaw in [0_f32, 0.7, 2.3, 4.8] {
                let matrix =
                    Mat4::perspective_rh_gl(60_f32.to_radians(), aspect, 0.035, CITY_FAR_PLANE)
                        * Mat4::look_at_rh(
                            eye,
                            eye + Vec3::new(yaw.sin(), 0.08, -yaw.cos()),
                            Vec3::Y,
                        );
                let mut actual = Vec::new();
                let stats = bvh.visit(eye, matrix, |i| actual.push(i));
                actual.sort_unstable();
                let expected: Vec<_> = bvh
                    .items
                    .iter()
                    .enumerate()
                    .filter_map(|(i, item)| {
                        let distance = if item.max_distance > 0. {
                            item.max_distance
                        } else {
                            CITY_FAR_PLANE
                        };
                        (corner_reference(item.bounds, matrix)
                            && within_distance(item.bounds, eye, distance))
                        .then_some(i)
                    })
                    .collect();
                assert_eq!(actual, expected);
                assert_eq!(stats.visible_records, actual.len());
                assert!(
                    stats.tested_records < stats.total_records,
                    "BVH skips entire invisible branches"
                );
            }
        }
    }

    #[test]
    fn small_prop_distance_is_explicit_and_uses_nearest_bounds_point() {
        let projection =
            Mat4::perspective_rh_gl(60_f32.to_radians(), 16. / 9., 0.035, CITY_FAR_PLANE);
        let bounds = Aabb::from_center(Vec3::new(0., 0., -130.), Vec3::splat(1.));
        let bvh = VisibilityBvh::new(vec![
            VisibilityItem {
                bounds,
                max_distance: 120.,
            },
            VisibilityItem {
                bounds,
                max_distance: 0.,
            },
            VisibilityItem {
                bounds: Aabb::from_center(Vec3::new(0., 0., -130.), Vec3::new(20., 20., 40.)),
                max_distance: 120.,
            },
        ]);
        let mut visible = Vec::new();
        let stats = bvh.visit(Vec3::ZERO, projection, |i| visible.push(i));
        assert_eq!(visible, [1, 2]);
        assert_eq!(stats.distance_culled_records, 1);
        // Near-plane crossings and camera-inside bounds remain visible.
        for bounds in [
            Aabb::from_center(Vec3::ZERO, Vec3::splat(2.)),
            Aabb::from_center(Vec3::new(0., 0., -0.04), Vec3::new(0.02, 0.02, 0.02)),
        ] {
            assert!(chunk_visible(bounds, Vec3::ZERO, projection));
        }
        // A long building whose center lies outside the view still intersects it.
        assert!(chunk_visible(
            Aabb::from_center(Vec3::new(45., 0., -20.), Vec3::new(90., 10., 10.)),
            Vec3::ZERO,
            projection
        ));
    }

    #[test]
    fn prelit_format_is_not_lit_twice() {
        let mut bytes = triangle();
        bytes[..8].copy_from_slice(b"RDCITY02");
        let chunks = decode_meshes(&bytes).unwrap();
        assert_eq!(
            chunks[0].mesh.vertices[0].color,
            Into::<[u8; 4]>::into(Color::new(0.8, 0.5, 0.2, 1.))
        );
    }
    fn triangle() -> Vec<u8> {
        let mut bytes = b"RDCITY01".to_vec();
        bytes.extend(1_u32.to_le_bytes());
        for value in [0_f32, 0., 0., 1., 1., 0.] {
            bytes.extend(value.to_le_bytes());
        }
        bytes.extend(3_u32.to_le_bytes());
        bytes.extend(3_u32.to_le_bytes());
        for position in [[0_f32, 0., 0.], [1., 0., 0.], [0., 1., 0.]] {
            for value in position.into_iter().chain([0., 0., 1., 0.8, 0.5, 0.2, 1.]) {
                bytes.extend(value.to_le_bytes());
            }
        }
        for index in [0_u16, 1, 2] {
            bytes.extend(index.to_le_bytes());
        }
        bytes
    }

    #[test]
    fn binary_preserves_geometry_and_rejects_corruption() {
        let bytes = triangle();
        let chunks = decode_meshes(&bytes).unwrap();
        assert_eq!(chunks[0].mesh.vertices[1].position, Vec3::X);
        assert_eq!(chunks[0].mesh.indices, [0, 1, 2]);
        assert_eq!(chunks[0].mesh.vertices[0].normal.truncate(), Vec3::Z);
        assert!(decode_meshes(&bytes[..bytes.len() - 1]).is_err());
        let mut bad_index = bytes.clone();
        let end = bad_index.len();
        bad_index[end - 2..].copy_from_slice(&3_u16.to_le_bytes());
        assert!(decode_meshes(&bad_index).is_err());
        let mut bad_float = bytes.clone();
        bad_float[44..48].copy_from_slice(&f32::NAN.to_le_bytes());
        assert!(decode_meshes(&bad_float).is_err());
        let mut trailing = bytes;
        trailing.push(0);
        assert!(decode_meshes(&trailing).is_err());
    }

    #[test]
    fn gzip_meshes_preserve_geometry_and_validate_integrity() {
        use std::io::Write;
        let mut encoder = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::fast());
        encoder.write_all(&triangle()).unwrap();
        let bytes = encoder.finish().unwrap();
        let chunks = decode_meshes(&bytes).unwrap();
        assert_eq!(chunks[0].mesh.vertices[1].position, Vec3::X);
        assert_eq!(chunks[0].mesh.indices, [0, 1, 2]);
        assert!(decode_meshes(&bytes[..bytes.len() - 4]).is_err());
        let mut corrupt = bytes;
        let end = corrupt.len();
        corrupt[end - 8] ^= 0xff;
        assert!(decode_meshes(&corrupt).is_err());
    }

    #[test]
    fn loader_reads_companion_geometry_and_rejects_a_blocked_spawn() {
        let temporary = std::env::temp_dir().join(format!(
            "rust-duty-city-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&temporary).unwrap();
        struct Cleanup(PathBuf);
        impl Drop for Cleanup {
            fn drop(&mut self) {
                let _ = std::fs::remove_dir_all(&self.0);
            }
        }
        let _cleanup = Cleanup(temporary.clone());
        let mut manifest = serde_json::json!({
            "schema": "rust-duty-city/v1", "name": "Loader fixture",
            "spawn": {"position": [0., 0., 0.], "yaw_degrees": -90.},
            "supply_position": [8., 0.15, 38.], "mesh_file": "meshes.bin",
            "colliders": [{"min": [-100., -1., -100.], "max": [100., 0., 100.]}]
        });
        let path = temporary.join("level.json");
        std::fs::write(temporary.join("meshes.bin"), triangle()).unwrap();
        std::fs::write(&path, serde_json::to_vec(&manifest).unwrap()).unwrap();
        let city = CityLevel::load(&path).unwrap();
        assert_eq!(city.chunks.len(), 1);
        assert_eq!(city.colliders.len(), 1);
        assert_eq!(city.spawn_yaw, -std::f32::consts::FRAC_PI_2);
        assert_eq!(city.supply_position, Vec3::new(8., 0.15, 38.));
        // An older coarse bake must not erase a modern source's membership.
        manifest["geometry_format"] = "RDCITY04".into();
        std::fs::write(temporary.join("lighting.bin"), triangle()).unwrap();
        std::fs::write(
            temporary.join("meshes.bin"),
            v4_triangle(serde_json::json!([{"id":7,"asset":"fixture"}]), 0),
        )
        .unwrap();
        std::fs::write(&path, serde_json::to_vec(&manifest).unwrap()).unwrap();
        let modern = CityLevel::load(&path).unwrap();
        assert_eq!(modern.chunks[0].instance.as_ref().unwrap().id, 7);
        assert_eq!(modern.mesh_source_path(), temporary.join("meshes.bin"));
        manifest["spawn"]["position"] = serde_json::json!([0., -0.1, 0.]);
        std::fs::write(&path, serde_json::to_vec(&manifest).unwrap()).unwrap();
        assert!(CityLevel::load(&path)
            .err()
            .unwrap()
            .contains("spawn overlaps solid collision"));
    }

    #[test]
    fn selection_defaults_to_city_and_preserves_explicit_range_and_fixture_replays() {
        assert_eq!(
            LevelSelection::from_options(&[], None).unwrap(),
            LevelSelection::CedarJunction
        );
        assert_eq!(
            LevelSelection::from_options(&[], Some("range")).unwrap(),
            LevelSelection::Range
        );
        assert_eq!(
            LevelSelection::from_options(&["--capture-sequence=vault".into()], None).unwrap(),
            LevelSelection::Range
        );
        assert_eq!(
            LevelSelection::from_options(&["--level=city".into()], Some("range")).unwrap(),
            LevelSelection::CedarJunction
        );
        assert!(LevelSelection::from_options(&[], Some("unknown")).is_err());
    }

    #[test]
    fn frustum_culling_keeps_near_and_visible_chunks() {
        let projection =
            Mat4::perspective_rh_gl(60_f32.to_radians(), 16. / 9., 0.035, CITY_FAR_PLANE);
        assert!(chunk_visible(
            Aabb::from_center(Vec3::new(0., 0., -10.), Vec3::splat(2.)),
            Vec3::ZERO,
            projection
        ));
        assert!(!chunk_visible(
            Aabb::from_center(Vec3::new(0., 0., 10.), Vec3::splat(2.)),
            Vec3::ZERO,
            projection
        ));
        assert!(!chunk_visible(
            Aabb::from_center(Vec3::new(80., 0., -10.), Vec3::splat(2.)),
            Vec3::ZERO,
            projection
        ));
        assert!(chunk_visible(
            Aabb::from_center(Vec3::ZERO, Vec3::splat(2.)),
            Vec3::ZERO,
            projection
        ));
    }

    #[test]
    fn level_collision_spawn_and_death_survive_reset() {
        let spawn = Vec3::new(8., 0., 38.);
        let bounds = Aabb::from_center(Vec3::new(0., -0.5, 0.), Vec3::new(220., 1., 220.));
        let mut sim = Simulation::new();
        sim.install_level(vec![Block { bounds, kind: 0 }], spawn, 0.25);
        sim.player.position = Vec3::new(100., 0., 100.);
        sim.reset();
        assert_eq!(sim.player.position, spawn);
        assert_eq!(sim.player.yaw, 0.25);
        assert_eq!(sim.blocks.len(), 1);
        assert!(sim.targets.is_empty() && sim.ramps.is_empty());
        let cfg = Settings::default();
        sim.damage_player(cfg.action.max_health);
        for _ in 0..((cfg.action.respawn_delay / FIXED_DT).ceil() as usize + 2) {
            sim.update(Input::default(), &cfg, FIXED_DT);
        }
        assert_eq!(sim.player.position, spawn);
        assert!(sim
            .action_events
            .iter()
            .any(|event| event.kind == ActionEventKind::Respawned));
    }
}
