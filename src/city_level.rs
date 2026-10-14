//! Cedar Junction's authored static world, separate from deterministic gameplay.
//!
//! Meshes are decoded and lit once at startup. Spatial chunks are culled against
//! the world camera before being submitted through either rendering backend.
use crate::{
    draw::{facade::draw_mesh_transformed, BlendMode, Color, Mesh, Vertex},
    scene_lighting::SceneLighting,
    sim::{Aabb, Block, Simulation},
};
use glam::{Mat4, Vec2, Vec3};
use serde_json::Value;
use std::path::{Path, PathBuf};

pub const CITY_FAR_PLANE: f32 = 400.;
const MAX_FILE_BYTES: usize = 256 * 1024 * 1024;
const MAX_CHUNKS: usize = 16_384;
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
}

pub struct CityLevel {
    pub name: String,
    pub spawn_position: Vec3,
    pub spawn_yaw: f32,
    pub supply_position: Vec3,
    pub colliders: Vec<Block>,
    pub chunks: Vec<CityChunk>,
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
            let meshes = read_limited(&path.with_file_name(mesh_name), MAX_FILE_BYTES)?;
            let chunks = decode_meshes(&meshes)?;
            Ok(Self {
                name,
                spawn_position,
                spawn_yaw,
                supply_position,
                colliders,
                chunks,
            })
        })();
        result.map_err(|error: String| {
            format!(
                "City level {}: {error}. Use --level=range to open the test range.",
                path.display()
            )
        })
    }

    pub fn install(&self, simulation: &mut Simulation) {
        simulation.install_level(self.colliders.clone(), self.spawn_position, self.spawn_yaw);
    }

    /// The same exact projection used by the camera preserves edge-of-view
    /// buildings even at widescreen aspect ratios or when the player leans.
    pub fn draw(&self, eye: Vec3, view_projection: Mat4) {
        for chunk in &self.chunks {
            if chunk_visible(chunk.bounds, eye, view_projection) {
                draw_mesh_transformed(&chunk.mesh, Mat4::IDENTITY, BlendMode::Opaque);
            }
        }
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

pub fn decode_meshes(bytes: &[u8]) -> Result<Vec<CityChunk>, String> {
    if bytes.len() > MAX_FILE_BYTES {
        return Err("city mesh file is too large".into());
    }
    // Exporters gzip the byte-identical mesh stream to keep detailed authored
    // assets small on disk. Bound the decompressed stream too, and let the
    // decoder verify gzip integrity before parsing any geometry.
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
    if reader.take::<8>()? != *b"RDCITY01" {
        return Err("invalid city mesh magic".into());
    }
    let count = reader.u32()?;
    if count == 0 || count > MAX_CHUNKS {
        return Err("invalid city chunk count".into());
    }
    let lighting = SceneLighting::range();
    let mut chunks = Vec::with_capacity(count);
    for chunk_index in 0..count {
        let bounds = Aabb {
            min: reader.vec3()?,
            max: reader.vec3()?,
        };
        if !bounds.min.cmple(bounds.max).all() {
            return Err(format!("invalid bounds for chunk {chunk_index}"));
        }
        let vertex_count = reader.u32()?;
        let index_count = reader.u32()?;
        if vertex_count == 0
            || vertex_count > MAX_VERTICES
            || index_count == 0
            || index_count > 360_000
            || !index_count.is_multiple_of(3)
        {
            return Err(format!("invalid geometry count for chunk {chunk_index}"));
        }
        let required = vertex_count * 40 + index_count * 2;
        if required > bytes.len() - reader.offset {
            return Err("truncated city geometry".into());
        }
        let mut vertices = Vec::with_capacity(vertex_count);
        for _ in 0..vertex_count {
            let position = reader.vec3()?;
            let normal = reader.vec3()?;
            let rgba = [reader.f32()?, reader.f32()?, reader.f32()?, reader.f32()?];
            if !position.cmpge(bounds.min - Vec3::splat(0.01)).all()
                || !position.cmple(bounds.max + Vec3::splat(0.01)).all()
            {
                return Err(format!("vertex outside chunk {chunk_index} bounds"));
            }
            if rgba.iter().any(|component| !(0. ..=1.).contains(component)) {
                return Err("city vertex color outside 0..1".into());
            }
            let mut vertex = Vertex::new2(
                position,
                Vec2::ZERO,
                lighting.shade(Color::new(rgba[0], rgba[1], rgba[2], rgba[3]), normal),
            );
            vertex.normal = normal.extend(0.);
            vertices.push(vertex);
        }
        let mut indices = Vec::with_capacity(index_count);
        for _ in 0..index_count {
            let index = u16::from_le_bytes(reader.take()?);
            if index as usize >= vertex_count {
                return Err(format!("index outside chunk {chunk_index} vertices"));
            }
            indices.push(index);
        }
        chunks.push(CityChunk {
            bounds,
            mesh: Mesh {
                vertices,
                indices,
                texture: None,
            },
        });
    }
    if reader.offset != bytes.len() {
        return Err("trailing data after city chunks".into());
    }
    Ok(chunks)
}

pub fn chunk_visible(bounds: Aabb, eye: Vec3, view_projection: Mat4) -> bool {
    if eye.distance_squared(eye.clamp(bounds.min, bounds.max)) > CITY_FAR_PLANE * CITY_FAR_PLANE {
        return false;
    }
    let corners = [
        Vec3::new(bounds.min.x, bounds.min.y, bounds.min.z),
        Vec3::new(bounds.min.x, bounds.min.y, bounds.max.z),
        Vec3::new(bounds.min.x, bounds.max.y, bounds.min.z),
        Vec3::new(bounds.min.x, bounds.max.y, bounds.max.z),
        Vec3::new(bounds.max.x, bounds.min.y, bounds.min.z),
        Vec3::new(bounds.max.x, bounds.min.y, bounds.max.z),
        Vec3::new(bounds.max.x, bounds.max.y, bounds.min.z),
        Vec3::new(bounds.max.x, bounds.max.y, bounds.max.z),
    ]
    .map(|point| view_projection * point.extend(1.));
    !(corners.iter().all(|p| p.x < -p.w)
        || corners.iter().all(|p| p.x > p.w)
        || corners.iter().all(|p| p.y < -p.w)
        || corners.iter().all(|p| p.y > p.w)
        || corners.iter().all(|p| p.z < -p.w)
        || corners.iter().all(|p| p.z > p.w))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        action::ActionEventKind,
        settings::Settings,
        sim::{Input, FIXED_DT},
    };

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
