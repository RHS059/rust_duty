//! Opt-in, frame-local execution receipts. These record submitted inputs, never
//! infer source completeness: the independent source oracle owns that comparison.
#![cfg_attr(
    not(any(feature = "wgpu-runtime", test)),
    allow(dead_code)
)]
use super::{BlendMode, Color, FilterMode, RenderTarget, Texture, TextureSource, Vertex, WrapMode};
use glam::Mat4;
use serde_json::{json, Value};
use std::{
    cell::RefCell,
    collections::HashMap,
    path::{Path, PathBuf},
};

pub const SCHEMA: &str = "rust-duty-native-visibility-receipt/v1";

/// Column-major IEEE-754 bits; decimal JSON floats are not a bit-exact contract.
pub fn matrix_bits(matrix: Mat4) -> [u32; 16] {
    matrix.to_cols_array().map(f32::to_bits)
}

/// Canonical triangle: three ordered vertices, each position xyz/f32 LE, uv xy/
/// f32 LE, then RGBA/u8. Normals are deliberately absent: neither native shader
/// consumes them. No bounds, vertex deduplication, winding sort or rounding.
pub fn triangle_sha256(vertices: &[Vertex; 3]) -> String {
    let mut bytes = [0_u8; 72];
    for (slot, vertex) in bytes.as_chunks_mut::<24>().0.iter_mut().zip(vertices) {
        for (out, value) in slot[..20].as_chunks_mut::<4>().0.iter_mut().zip(
            vertex
                .position
                .to_array()
                .into_iter()
                .chain(vertex.uv.to_array()),
        ) {
            out.copy_from_slice(&value.to_le_bytes());
        }
        slot[20..24].copy_from_slice(&vertex.color);
    }
    rust_duty_launcher::bytes_hash(&bytes)
}

pub fn triangle_hashes(vertices: &[Vertex], indices: &[u16]) -> Result<Vec<String>, String> {
    if !indices.len().is_multiple_of(3) || indices.iter().any(|&i| usize::from(i) >= vertices.len())
    {
        return Err("visibility receipt requires complete valid triangles".into());
    }
    Ok(indices
        .as_chunks::<3>()
        .0
        .iter()
        .map(|i| {
            triangle_sha256(&[
                vertices[usize::from(i[0])],
                vertices[usize::from(i[1])],
                vertices[usize::from(i[2])],
            ])
        })
        .collect())
}

fn require_sha256(value: &str) -> Result<(), String> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err("visibility digest is not lowercase SHA256".into());
    }
    Ok(())
}

/// Compact ordered geometry identity: hash the concatenated fixed-width ASCII
/// triangle digests, without separators, sorting or deduplication.
pub fn triangle_stream_sha256(triangle_sha256: &[String]) -> Result<String, String> {
    let mut bytes = Vec::with_capacity(triangle_sha256.len() * 64);
    for digest in triangle_sha256 {
        require_sha256(digest)?;
        bytes.extend_from_slice(digest.as_bytes());
    }
    Ok(rust_duty_launcher::bytes_hash(&bytes))
}

/// Canonical draw-input state shared with the independent source oracle only as
/// a serialization contract. Domain bytes end in NUL; matrices are column-major
/// u32 LE bits, followed by upload presence and optional matrix, texture extent
/// u32 LE, filter (nearest=0/linear=1), wraps (clamp=0/repeat=1), and 64 ASCII
/// texture-content SHA256 bytes. Unsupported texture kinds fail closed.
pub fn draw_input_state_sha256(
    view_projection: Mat4,
    model: Mat4,
    upload_transform: Option<Mat4>,
    texture: &Value,
) -> Result<String, String> {
    if !view_projection.is_finite()
        || !model.is_finite()
        || upload_transform.is_some_and(|matrix| !matrix.is_finite())
    {
        return Err("visibility draw-input state has a non-finite matrix".into());
    }
    if texture["kind"] != "rgba8" {
        return Err("visibility draw-input state requires an RGBA8 source texture".into());
    }
    let mut bytes = b"rust-duty-draw-input-state/v1\0".to_vec();
    for matrix in [view_projection, model] {
        for bits in matrix_bits(matrix) {
            bytes.extend_from_slice(&bits.to_le_bytes());
        }
    }
    bytes.push(u8::from(upload_transform.is_some()));
    if let Some(matrix) = upload_transform {
        for bits in matrix_bits(matrix) {
            bytes.extend_from_slice(&bits.to_le_bytes());
        }
    }
    for axis in ["width", "height"] {
        let extent = texture[axis]
            .as_u64()
            .and_then(|value| u32::try_from(value).ok())
            .filter(|&value| value != 0)
            .ok_or("visibility draw-input state has an invalid texture extent")?;
        bytes.extend_from_slice(&extent.to_le_bytes());
    }
    bytes.push(match texture["sampler"]["filter"].as_str() {
        Some("nearest") => 0,
        Some("linear") => 1,
        _ => return Err("visibility draw-input state has an unsupported filter".into()),
    });
    for axis in ["wrap_x", "wrap_y"] {
        bytes.push(match texture["sampler"][axis].as_str() {
            Some("clamp") => 0,
            Some("repeat") => 1,
            _ => return Err("visibility draw-input state has an unsupported wrap".into()),
        });
    }
    let digest = texture["rgba8_sha256"]
        .as_str()
        .ok_or("visibility draw-input state has no texture-content digest")?;
    require_sha256(digest)?;
    bytes.extend_from_slice(digest.as_bytes());
    Ok(rust_duty_launcher::bytes_hash(&bytes))
}

/// Append fixed 128-byte records (state SHA256 ASCII, triangle SHA256 ASCII).
/// Hashing this frame-wide buffer binds complete ordered inputs independently
/// of physical draw splits. Witness triangles must not enter this accumulator.
pub fn append_ordered_draw_inputs(
    bytes: &mut Vec<u8>,
    state_sha256: &str,
    triangle_sha256: &[String],
) -> Result<(), String> {
    require_sha256(state_sha256)?;
    for digest in triangle_sha256 {
        require_sha256(digest)?;
    }
    for digest in triangle_sha256 {
        bytes.extend_from_slice(state_sha256.as_bytes());
        bytes.extend_from_slice(digest.as_bytes());
    }
    Ok(())
}

/// Content identity, not process-local resource identity. This helper is shared
/// with the source oracle only as a byte serialization contract.
pub fn texture_identity(texture: Option<&Texture>) -> Value {
    let sampler = texture.map_or_else(super::Sampler::default, |t| t.sampler);
    let wrap = |value| match value {
        WrapMode::Clamp => "clamp",
        WrapMode::Repeat => "repeat",
    };
    let mut value = json!({
        "kind":"rgba8", "width":texture.map_or(1, |t| t.width),
        "height":texture.map_or(1, |t| t.height),
        "sampler":{"filter":match sampler.filter { FilterMode::Linear => "linear", FilterMode::Nearest => "nearest" },
            "wrap_x":wrap(sampler.wrap_x),"wrap_y":wrap(sampler.wrap_y)},
    });
    match texture.map(|t| &t.source) {
        None => value["rgba8_sha256"] = json!(rust_duty_launcher::bytes_hash(&[255; 4])),
        Some(TextureSource::Rgba8(bytes)) => {
            value["rgba8_sha256"] = json!(rust_duty_launcher::bytes_hash(bytes))
        }
        Some(TextureSource::Target { depth }) => {
            value["kind"] = json!("render-target");
            value["depth"] = json!(depth);
            value["resource_id"] = json!(texture.expect("target descriptor").id.0);
        }
    }
    value
}

struct Request {
    path: PathBuf,
    target: RenderTarget,
    frame_index: u32,
    identity: String,
}
thread_local! { static REQUEST: RefCell<Option<Request>> = const { RefCell::new(None) }; }

fn sidecar(path: &Path) -> PathBuf {
    let mut name = path.as_os_str().to_owned();
    name.push(".visibility.json");
    PathBuf::from(name)
}

/// Called only by reference gameplay-ADS capture with an explicit frame witness.
/// No environment flag can silently enable receipts during ordinary play.
pub fn request(
    path: impl Into<PathBuf>,
    target: &RenderTarget,
    frame_index: u32,
    identity: &str,
) -> Result<(), String> {
    super::frame_witness::parse_identity(identity)?;
    let path = path.into();
    if path.as_os_str().is_empty() {
        return Err("visibility capture path is empty".into());
    }
    REQUEST.with(|pending| {
        let mut pending = pending.borrow_mut();
        if pending.is_some() {
            return Err("unconsumed visibility capture request".into());
        }
        // A failed rerun must not leave a successful prior receipt at this name.
        match std::fs::remove_file(sidecar(&path)) {
            Ok(()) => (),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => (),
            Err(e) => return Err(format!("remove stale visibility receipt: {e}")),
        }
        *pending = Some(Request {
            path,
            target: target.clone(),
            frame_index,
            identity: identity.into(),
        });
        Ok(())
    })
}

#[cfg(feature = "wgpu-runtime")]
pub(crate) fn requested() -> bool {
    REQUEST.with(|pending| pending.borrow().is_some())
}

pub(crate) struct FrameReceipt {
    request: Request,
    backend: String,
    events: Vec<Value>,
    draws: Vec<Value>,
    ordered_draw_inputs: Vec<u8>,
    textures: HashMap<Option<super::ResourceId>, Value>,
    witness_hashes: Vec<String>,
    witness_count: usize,
    closed: bool,
}

impl FrameReceipt {
    pub(crate) fn begin(backend: &str) -> Option<Self> {
        REQUEST
            .with(|pending| pending.borrow_mut().take())
            .map(|request| {
                let witness = super::frame_witness::mesh(
                    request.frame_index,
                    &super::frame_witness::parse_identity(&request.identity)
                        .expect("validated request"),
                );
                Self {
                    request,
                    backend: backend.into(),
                    events: Vec::new(),
                    draws: Vec::new(),
                    ordered_draw_inputs: Vec::new(),
                    textures: HashMap::new(),
                    witness_hashes: triangle_hashes(&witness.vertices, &witness.indices)
                        .expect("valid witness"),
                    witness_count: 0,
                    closed: false,
                }
            })
    }
    pub(crate) fn selects(&self, target: Option<&RenderTarget>) -> bool {
        !self.closed && target.is_some_and(|t| t.texture.id == self.request.target.texture.id)
    }
    pub(crate) fn clear(&mut self, target: Option<&RenderTarget>, color: Color) {
        if self.selects(target) {
            self.events.push(json!({"kind":"clear","rgba_bits":([color.r,color.g,color.b,color.a].map(f32::to_bits)),"depth_bits":1_f32.to_bits()}));
        }
    }
    #[cfg(test)]
    pub(crate) fn unsupported(
        &mut self,
        target: Option<&RenderTarget>,
        kind: &str,
    ) -> Result<(), String> {
        if self.selects(target) {
            Err(format!(
                "visibility receipt does not support target command {kind}"
            ))
        } else {
            Ok(())
        }
    }
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn record_draw(
        &mut self,
        target: Option<&RenderTarget>,
        view_projection: Mat4,
        model: Mat4,
        upload_transform: Option<Mat4>,
        texture: Option<&Texture>,
        blend: BlendMode,
        depth: bool,
        lines: bool,
        triangle_sha256: Vec<String>,
        observed_gl_state: Option<Value>,
    ) -> Result<(), String> {
        if !self.selects(target) {
            return Ok(());
        }
        if lines || triangle_sha256.is_empty() {
            return Err("visibility receipt requires nonempty triangle draws".into());
        }
        if !view_projection.is_finite()
            || !model.is_finite()
            || upload_transform.is_some_and(|m| !m.is_finite())
        {
            return Err("visibility receipt has a non-finite submitted matrix".into());
        }
        let target = &self.request.target.texture;
        let is_witness = triangle_sha256 == self.witness_hashes
            && matrix_bits(view_projection)
                == matrix_bits(super::Camera::screen(target.width, target.height).view_projection)
            && matrix_bits(model) == matrix_bits(Mat4::IDENTITY)
            && texture.is_none()
            && blend == BlendMode::Opaque
            && !depth;
        let texture = self
            .textures
            .entry(texture.map(|t| t.id))
            .or_insert_with(|| texture_identity(texture))
            .clone();
        let gl = self.backend == "OpenGl";
        let associated = texture["kind"] == "render-target";
        let depth_test = depth && !(gl && blend == BlendMode::Additive);
        let state = json!({
            "topology":"triangle-list", "viewport":[0,0,target.width,target.height],
            "scissor":[0,0,target.width,target.height], "depth_range_bits":[0_f32.to_bits(),1_f32.to_bits()],
            "depth_test":depth_test,"depth_write":depth && blend != BlendMode::Additive,
            "depth_compare":if depth_test {"less-equal"} else {"always"},
            "blend":match blend {BlendMode::Opaque=>"opaque",BlendMode::Alpha=>"alpha",BlendMode::Additive=>"additive"},
            "color_blend":match blend {BlendMode::Opaque=>json!(null),BlendMode::Alpha=>json!([if associated {"one"} else {"src-alpha"},"one-minus-src-alpha","add"]),BlendMode::Additive=>json!([if associated {"one"} else {"src-alpha"},"one","add"])},
            "alpha_blend":match blend {BlendMode::Opaque=>json!(null),BlendMode::Alpha=>json!(["one","one-minus-src-alpha","add"]),BlendMode::Additive=>json!(["zero","one","add"])},
            "cull":"none","front_face":"ccw","color_write":"rgba","sample_count":1,
            "clip_depth":if gl {"minus-one-to-one"} else {"zero-to-one"},"depth_clamp":false,
            "fragment":if associated {"associated"} else if blend==BlendMode::Opaque {"associate-straight"} else {"straight"},
            "target_format":"rgba8unorm","observed_gl":observed_gl_state,
        });
        let mut draw = json!({"triangle_count":triangle_sha256.len(),
            "view_projection_bits":matrix_bits(view_projection),"model_bits":matrix_bits(model),
            "upload_transform_bits":upload_transform.map(matrix_bits),"texture":texture,"state":state});
        if is_witness {
            draw["triangle_sha256"] = json!(triangle_sha256);
            self.witness_count += 1;
            self.events.push(json!({"kind":"witness","draw":draw}));
        } else {
            if self.witness_count != 0 {
                return Err("scene draw follows frame witness before Capture".into());
            }
            let state_sha256 =
                draw_input_state_sha256(view_projection, model, upload_transform, &texture)?;
            append_ordered_draw_inputs(
                &mut self.ordered_draw_inputs,
                &state_sha256,
                &triangle_sha256,
            )?;
            self.events
                .push(json!({"kind":"draw","draw_index":self.draws.len()}));
            self.draws.push(draw);
        }
        Ok(())
    }
    pub(crate) fn capture(
        &mut self,
        target: Option<&RenderTarget>,
        path: &Path,
    ) -> Result<(), String> {
        if path != self.request.path {
            return Ok(());
        }
        if self.closed || !self.selects(target) {
            return Err("visibility Capture target/order mismatch".into());
        }
        if self.witness_count != 1
            || self.draws.is_empty()
            || !self.events.iter().any(|e| e["kind"] == "clear")
        {
            return Err("visibility Capture requires a clear, scene triangles and exactly one matching witness".into());
        }
        if self.events.last().is_none_or(|e| e["kind"] != "witness") {
            return Err("visibility witness is not the last target draw before Capture".into());
        }
        self.events.push(json!({"kind":"capture"}));
        self.closed = true;
        Ok(())
    }
    /// The backend calls only after submission validation and matching PNG
    /// readback finish successfully. Dropping this object never writes evidence.
    pub(crate) fn finish(self, captures: &[PathBuf]) -> Result<(), String> {
        if !self.closed || !captures.contains(&self.request.path) {
            return Err("visibility receipt lacks completed ordered readback".into());
        }
        let target = &self.request.target.texture;
        let value = json!({"schema":SCHEMA,"capture_identity":self.request.identity,"frame_index":self.request.frame_index,
            "backend":self.backend,"capture_path":self.request.path.file_name().and_then(|s|s.to_str()),
            "capture_sha256":rust_duty_launcher::file_hash(&self.request.path).map_err(|e| e.to_string())?,
            "target":{"resource_id":target.id.0,"width":target.width,"height":target.height,"depth":matches!(target.source,TextureSource::Target {depth:true})},
            "witness_exclusion":[0,0,super::frame_witness::WIDTH,super::frame_witness::HEIGHT],
            "witness_count":self.witness_count,"triangle_count":self.draws.iter().map(|d|d["triangle_count"].as_u64().unwrap_or(0)).sum::<u64>(),
            "ordered_draw_input_sha256":rust_duty_launcher::bytes_hash(&self.ordered_draw_inputs),
            "draws":self.draws,"events":self.events,"submission_complete":true,"capture_complete":true,
        });
        let path = sidecar(&self.request.path);
        let temporary = path.with_extension("json.pending");
        std::fs::write(
            &temporary,
            serde_json::to_vec(&value).map_err(|e| e.to_string())?,
        )
        .map_err(|e| e.to_string())?;
        std::fs::rename(temporary, path).map_err(|e| e.to_string())
    }
}

/// Interpret the exact serialized uniform slot handed to the upload API.
#[cfg(any(feature = "wgpu-runtime", test))]
pub(crate) fn packed_matrix(bytes: &[u8]) -> Result<Mat4, String> {
    if bytes.len() != 64 {
        return Err("visibility matrix slot is not 64 bytes".into());
    }
    let mut values = [0_f32; 16];
    for (value, bytes) in values.iter_mut().zip(bytes.as_chunks::<4>().0) {
        *value = f32::from_le_bytes(*bytes);
    }
    let matrix = Mat4::from_cols_array(&values);
    if !matrix.is_finite() {
        return Err("visibility upload matrix is non-finite".into());
    }
    Ok(matrix)
}

/// Hash actual packed vertex/index ranges, including order and multiplicity.
/// The first 24 bytes of a native vertex are the canonical position/uv/color.
#[cfg(any(feature = "wgpu-runtime", test))]
pub(crate) fn packed_triangle_hashes(
    vertices: &[u8],
    indices: &[u8],
    stride: usize,
) -> Result<Vec<String>, String> {
    if stride < 24 || !vertices.len().is_multiple_of(stride) || !indices.len().is_multiple_of(6) {
        return Err("visibility packed triangle extent is invalid".into());
    }
    indices
        .as_chunks::<6>()
        .0
        .iter()
        .map(|triangle| {
            let mut bytes = [0_u8; 72];
            for (out, index) in bytes
                .as_chunks_mut::<24>()
                .0
                .iter_mut()
                .zip(triangle.as_chunks::<2>().0)
            {
                let offset = usize::from(u16::from_le_bytes(*index)) * stride;
                let input = vertices
                    .get(offset..offset + 24)
                    .ok_or("visibility packed index out of range")?;
                out.copy_from_slice(input);
            }
            Ok(rust_duty_launcher::bytes_hash(&bytes))
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use glam::{Vec2, Vec3};

    fn triangle() -> [Vertex; 3] {
        [Vec3::ZERO, Vec3::X, Vec3::Y].map(|p| Vertex::new2(p, Vec2::ZERO, Color::WHITE))
    }
    fn receipt(frame_index: u32) -> FrameReceipt {
        let request = Request {
            path: PathBuf::from("native-frame.png"),
            target: RenderTarget::new(960, 540, true).unwrap(),
            frame_index,
            identity: "42".repeat(32),
        };
        let witness = super::super::frame_witness::mesh(frame_index, &[0x42; 32]);
        FrameReceipt {
            request,
            backend: "Dx12".into(),
            events: Vec::new(),
            draws: Vec::new(),
            ordered_draw_inputs: Vec::new(),
            textures: HashMap::new(),
            witness_hashes: triangle_hashes(&witness.vertices, &witness.indices).unwrap(),
            witness_count: 0,
            closed: false,
        }
    }
    fn scene(receipt: &mut FrameReceipt) {
        let target = receipt.request.target.clone();
        receipt.clear(Some(&target), Color::new(0.14, 0.19, 0.24, 1.));
        receipt
            .record_draw(
                Some(&target),
                Mat4::IDENTITY,
                Mat4::IDENTITY,
                Some(Mat4::IDENTITY),
                None,
                BlendMode::Alpha,
                true,
                false,
                vec![triangle_sha256(&triangle())],
                None,
            )
            .unwrap();
    }
    fn witness(receipt: &mut FrameReceipt, frame_index: u32, projection: Mat4) {
        let target = receipt.request.target.clone();
        let witness = super::super::frame_witness::mesh(frame_index, &[0x42; 32]);
        receipt
            .record_draw(
                Some(&target),
                projection,
                Mat4::IDENTITY,
                Some(projection),
                None,
                BlendMode::Opaque,
                false,
                false,
                triangle_hashes(&witness.vertices, &witness.indices).unwrap(),
                None,
            )
            .unwrap();
    }
    #[test]
    fn request_is_single_use_frame_bound_and_removes_stale_success() {
        use std::sync::atomic::{AtomicU64, Ordering};
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let directory = std::env::temp_dir().join(format!(
            "rust-duty-visibility-request-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir_all(&directory).unwrap();
        let path = directory.join("0007.png");
        let target = RenderTarget::new(960, 540, true).unwrap();
        let identity = "42".repeat(32);
        let stale = sidecar(&path);
        std::fs::write(&stale, b"prior successful receipt").unwrap();
        assert!(FrameReceipt::begin("Dx12").is_none());
        request(path.clone(), &target, 7, &identity).unwrap();
        assert!(!stale.exists());
        assert!(request(path.clone(), &target, 8, &identity).is_err());
        let receipt = FrameReceipt::begin("Dx12").unwrap();
        assert_eq!(receipt.request.path, path);
        assert_eq!(receipt.request.frame_index, 7);
        assert_eq!(receipt.request.identity, identity);
        assert_eq!(receipt.request.target.texture.id, target.texture.id);
        assert_eq!(receipt.backend, "Dx12");
        assert!(FrameReceipt::begin("OpenGl").is_none());
        drop(receipt);
        assert!(!stale.exists());
        request(path.clone(), &target, 8, &identity).unwrap();
        let next = FrameReceipt::begin("OpenGl").unwrap();
        assert_eq!(next.request.frame_index, 8);
        assert_eq!(next.backend, "OpenGl");
        assert!(next.finish(&[]).is_err());
        assert!(!stale.exists());
        std::fs::remove_dir(directory).unwrap();
    }
    #[test]
    fn canonical_hash_preserves_every_vertex_bit_order_and_duplicate() {
        let original = triangle();
        let expected = triangle_sha256(&original);
        assert_eq!(
            expected,
            "27a90387439cb417b211716e702332d3177781c4edcd37791733093585aa8a97"
        );
        for changed in [
            [original[1], original[0], original[2]],
            {
                let mut t = original;
                t[1].position.x = 0.5;
                t
            },
            {
                let mut t = original;
                t[0].uv.x = 0.5;
                t
            },
            {
                let mut t = original;
                t[0].color[3] = 254;
                t
            },
            {
                let mut t = original;
                t[0].position.x = -0.;
                t
            },
        ] {
            assert_ne!(triangle_sha256(&changed), expected);
        }
        assert_eq!(
            triangle_hashes(&original, &[0, 1, 2, 0, 1, 2]).unwrap(),
            vec![expected.clone(), expected]
        );
        assert!(triangle_hashes(&original, &[0, 1]).is_err());
        assert!(triangle_hashes(&original, &[0, 1, 3]).is_err());
    }
    #[test]
    fn compact_input_state_has_fixed_bytes_and_binds_every_input() {
        let texture = texture_identity(None);
        let original = draw_input_state_sha256(
            Mat4::IDENTITY,
            Mat4::IDENTITY,
            Some(Mat4::IDENTITY),
            &texture,
        )
        .unwrap();
        assert_eq!(
            original,
            "07821c444dd5613337ff95c79afa993f95ab10a7c6df9fdcdc78f61e4c9361b2"
        );
        let changed = Mat4::from_scale(Vec3::splat(0.5));
        for (projection, model, upload) in [
            (changed, Mat4::IDENTITY, Some(Mat4::IDENTITY)),
            (Mat4::IDENTITY, changed, Some(Mat4::IDENTITY)),
            (Mat4::IDENTITY, Mat4::IDENTITY, Some(changed)),
            (Mat4::IDENTITY, Mat4::IDENTITY, None),
        ] {
            assert_ne!(
                draw_input_state_sha256(projection, model, upload, &texture).unwrap(),
                original
            );
        }
        for (pointer, value) in [
            ("/width", json!(2)),
            ("/height", json!(2)),
            ("/sampler/filter", json!("nearest")),
            ("/sampler/wrap_x", json!("repeat")),
            ("/sampler/wrap_y", json!("repeat")),
            ("/rgba8_sha256", json!("00".repeat(32))),
        ] {
            let mut changed = texture.clone();
            *changed.pointer_mut(pointer).unwrap() = value;
            assert_ne!(
                draw_input_state_sha256(
                    Mat4::IDENTITY,
                    Mat4::IDENTITY,
                    Some(Mat4::IDENTITY),
                    &changed,
                )
                .unwrap(),
                original
            );
        }
        for (pointer, value) in [
            ("/kind", json!("render-target")),
            ("/width", json!(0)),
            ("/height", json!(u64::MAX)),
            ("/sampler/filter", json!("unknown")),
            ("/sampler/wrap_x", json!("unknown")),
            ("/rgba8_sha256", json!("AA".repeat(32))),
        ] {
            let mut invalid = texture.clone();
            *invalid.pointer_mut(pointer).unwrap() = value;
            assert!(draw_input_state_sha256(
                Mat4::IDENTITY,
                Mat4::IDENTITY,
                Some(Mat4::IDENTITY),
                &invalid,
            )
            .is_err());
        }
    }
    #[test]
    fn compact_stream_preserves_order_multiplicity_and_state_across_splits() {
        let hashes = vec!["11".repeat(32), "22".repeat(32), "11".repeat(32)];
        let state = "33".repeat(32);
        let mut whole = Vec::new();
        append_ordered_draw_inputs(&mut whole, &state, &hashes).unwrap();
        let mut split = Vec::new();
        append_ordered_draw_inputs(&mut split, &state, &hashes[..1]).unwrap();
        append_ordered_draw_inputs(&mut split, &state, &hashes[1..]).unwrap();
        assert_eq!(whole, split);
        assert_eq!(whole.len(), 3 * 128);
        assert_eq!(
            triangle_stream_sha256(&hashes).unwrap(),
            rust_duty_launcher::bytes_hash(hashes.concat().as_bytes())
        );
        let expected = rust_duty_launcher::bytes_hash(&whole);
        for changed in [
            hashes[..2].to_vec(),
            vec![hashes[1].clone(), hashes[0].clone(), hashes[2].clone()],
            vec![hashes[0].clone(), hashes[1].clone(), "44".repeat(32)],
        ] {
            let mut bytes = Vec::new();
            append_ordered_draw_inputs(&mut bytes, &state, &changed).unwrap();
            assert_ne!(rust_duty_launcher::bytes_hash(&bytes), expected);
            assert_ne!(
                triangle_stream_sha256(&changed).unwrap(),
                triangle_stream_sha256(&hashes).unwrap()
            );
        }
        let mut changed_state = Vec::new();
        append_ordered_draw_inputs(&mut changed_state, &"55".repeat(32), &hashes).unwrap();
        assert_ne!(rust_duty_launcher::bytes_hash(&changed_state), expected);
        assert!(append_ordered_draw_inputs(&mut whole, &state, &["invalid".into()]).is_err());
        assert!(triangle_stream_sha256(&["invalid".into()]).is_err());
        assert_eq!(whole, split);
    }
    #[test]
    fn compact_scene_receipts_exclude_exact_witness_from_ordered_input_digest() {
        let mut current = receipt(7);
        scene(&mut current);
        let before_witness = current.ordered_draw_inputs.clone();
        assert_eq!(before_witness.len(), 128);
        assert!(current.draws[0].get("triangle_sha256").is_none());
        assert!(current.draws[0].get("triangle_stream_sha256").is_none());
        assert_eq!(current.draws[0]["triangle_count"], 1);
        witness(
            &mut current,
            7,
            super::super::Camera::screen(960, 540).view_projection,
        );
        assert_eq!(current.ordered_draw_inputs, before_witness);
        let witness = &current.events.last().unwrap()["draw"];
        assert_eq!(
            witness["triangle_sha256"].as_array().unwrap().len(),
            current.witness_hashes.len()
        );
        assert!(witness.get("triangle_stream_sha256").is_none());
    }
    #[test]
    fn actual_upload_ranges_bind_geometry_and_matrix_mutations() {
        let original = triangle();
        let mut packed = Vec::new();
        for vertex in original {
            for value in vertex
                .position
                .to_array()
                .into_iter()
                .chain(vertex.uv.to_array())
            {
                packed.extend(value.to_le_bytes());
            }
            packed.extend(vertex.color);
            packed.extend([0_u8; 16]);
        }
        let indices = [0, 0, 1, 0, 2, 0];
        let expected = packed_triangle_hashes(&packed, &indices, 40).unwrap();
        assert_eq!(expected, vec![triangle_sha256(&original)]);
        packed[40..44].copy_from_slice(&0.5_f32.to_le_bytes());
        assert_ne!(
            packed_triangle_hashes(&packed, &indices, 40).unwrap(),
            expected
        );
        assert!(packed_triangle_hashes(&packed, &indices[..4], 40).is_err());
        assert!(packed_triangle_hashes(&packed, &[0, 0, 1, 0, 3, 0], 40).is_err());
        let mut matrix: Vec<_> = Mat4::IDENTITY
            .to_cols_array()
            .into_iter()
            .flat_map(f32::to_le_bytes)
            .collect();
        assert_eq!(
            matrix_bits(packed_matrix(&matrix).unwrap()),
            matrix_bits(Mat4::IDENTITY)
        );
        matrix[..4].copy_from_slice(&0.5_f32.to_le_bytes());
        assert_ne!(
            matrix_bits(packed_matrix(&matrix).unwrap()),
            matrix_bits(Mat4::IDENTITY)
        );
    }
    #[test]
    fn requires_scene_clear_exact_witness_and_matching_ordered_capture() {
        let mut valid = receipt(7);
        scene(&mut valid);
        witness(
            &mut valid,
            7,
            super::super::Camera::screen(960, 540).view_projection,
        );
        let target = valid.request.target.clone();
        valid
            .capture(Some(&target), Path::new("native-frame.png"))
            .unwrap();
        assert!(valid.closed);
        assert!(valid.finish(&[]).is_err());
        for (frame, projection) in [
            (8, super::super::Camera::screen(960, 540).view_projection),
            (7, Mat4::IDENTITY),
        ] {
            let mut invalid = receipt(7);
            scene(&mut invalid);
            witness(&mut invalid, frame, projection);
            let target = invalid.request.target.clone();
            assert!(invalid
                .capture(Some(&target), Path::new("native-frame.png"))
                .is_err());
        }
        let mut missing = receipt(7);
        let target = missing.request.target.clone();
        missing.clear(Some(&target), Color::WHITE);
        witness(
            &mut missing,
            7,
            super::super::Camera::screen(960, 540).view_projection,
        );
        assert!(missing
            .capture(Some(&target), Path::new("native-frame.png"))
            .is_err());
    }
    #[test]
    fn target_swaps_unsupported_commands_and_post_witness_scene_fail_closed() {
        let mut current = receipt(0);
        scene(&mut current);
        let target = current.request.target.clone();
        assert!(current.unsupported(Some(&target), "lines").is_err());
        assert!(current.unsupported(None, "unrelated world lines").is_ok());
        witness(
            &mut current,
            0,
            super::super::Camera::screen(960, 540).view_projection,
        );
        let other = RenderTarget::new(960, 540, true).unwrap();
        assert!(current
            .capture(Some(&other), Path::new("native-frame.png"))
            .is_err());
        assert!(current
            .record_draw(
                Some(&target),
                Mat4::IDENTITY,
                Mat4::IDENTITY,
                Some(Mat4::IDENTITY),
                None,
                BlendMode::Alpha,
                true,
                false,
                vec![triangle_sha256(&triangle())],
                None
            )
            .is_err());
    }
    #[test]
    fn texture_identity_binds_content_extent_and_sampler() {
        let original = Texture::rgba8(1, 1, &[255; 4], super::super::Sampler::default()).unwrap();
        assert_eq!(texture_identity(None), texture_identity(Some(&original)));
        let changed = Texture::rgba8(
            1,
            1,
            &[255, 255, 255, 254],
            super::super::Sampler::default(),
        )
        .unwrap();
        assert_ne!(
            texture_identity(Some(&original)),
            texture_identity(Some(&changed))
        );
        let sampler = super::super::Sampler {
            filter: FilterMode::Nearest,
            ..super::super::Sampler::default()
        };
        let changed = Texture::rgba8(1, 1, &[255; 4], sampler).unwrap();
        assert_ne!(
            texture_identity(Some(&original)),
            texture_identity(Some(&changed))
        );
    }
}
