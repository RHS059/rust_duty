//! Opt-in, frame-local execution receipts. These record submitted inputs, never
//! infer source completeness: the independent source oracle owns that comparison.
#![cfg_attr(not(any(feature = "wgpu-runtime", feature = "legacy-macroquad", test)), allow(dead_code))]
use super::{BlendMode, Color, FilterMode, RenderTarget, Texture, TextureSource, Vertex, WrapMode};
use glam::Mat4;
use serde_json::{json, Value};
use std::{cell::RefCell, collections::HashMap, path::{Path, PathBuf}};

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
    for (slot, vertex) in bytes.chunks_exact_mut(24).zip(vertices) {
        for (out, value) in slot[..20].chunks_exact_mut(4).zip(
            vertex.position.to_array().into_iter().chain(vertex.uv.to_array())
        ) {
            out.copy_from_slice(&value.to_le_bytes());
        }
        slot[20..24].copy_from_slice(&vertex.color);
    }
    rust_duty_launcher::bytes_hash(&bytes)
}

pub fn triangle_hashes(vertices: &[Vertex], indices: &[u16]) -> Result<Vec<String>, String> {
    if !indices.len().is_multiple_of(3) || indices.iter().any(|&i| usize::from(i) >= vertices.len()) {
        return Err("visibility receipt requires complete valid triangles".into());
    }
    Ok(indices.chunks_exact(3).map(|i| triangle_sha256(&[
        vertices[usize::from(i[0])], vertices[usize::from(i[1])], vertices[usize::from(i[2])]
    ])).collect())
}

/// Content identity, not process-local resource identity. This helper is shared
/// with the source oracle only as a byte serialization contract.
pub fn texture_identity(texture: Option<&Texture>) -> Value {
    let sampler = texture.map_or_else(super::Sampler::default, |t| t.sampler);
    let wrap = |value| match value { WrapMode::Clamp => "clamp", WrapMode::Repeat => "repeat" };
    let mut value = json!({
        "kind":"rgba8", "width":texture.map_or(1, |t| t.width),
        "height":texture.map_or(1, |t| t.height),
        "sampler":{"filter":match sampler.filter { FilterMode::Linear => "linear", FilterMode::Nearest => "nearest" },
            "wrap_x":wrap(sampler.wrap_x),"wrap_y":wrap(sampler.wrap_y)},
    });
    match texture.map(|t| &t.source) {
        None => value["rgba8_sha256"] = json!(rust_duty_launcher::bytes_hash(&[255; 4])),
        Some(TextureSource::Rgba8(bytes)) => value["rgba8_sha256"] = json!(rust_duty_launcher::bytes_hash(bytes)),
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
pub fn request(path: impl Into<PathBuf>, target: &RenderTarget, frame_index: u32, identity: &str) -> Result<(), String> {
    super::frame_witness::parse_identity(identity)?;
    let path = path.into();
    if path.as_os_str().is_empty() { return Err("visibility capture path is empty".into()); }
    REQUEST.with(|pending| {
        let mut pending = pending.borrow_mut();
        if pending.is_some() { return Err("unconsumed visibility capture request".into()); }
        // A failed rerun must not leave a successful prior receipt at this name.
        match std::fs::remove_file(sidecar(&path)) {
            Ok(()) => (),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => (),
            Err(e) => return Err(format!("remove stale visibility receipt: {e}")),
        }
        *pending = Some(Request { path, target: target.clone(), frame_index, identity: identity.into() });
        Ok(())
    })
}

#[cfg(feature = "wgpu-runtime")]
pub(crate) fn requested() -> bool { REQUEST.with(|pending| pending.borrow().is_some()) }

pub(crate) struct FrameReceipt {
    request: Request,
    backend: String,
    events: Vec<Value>,
    draws: Vec<Value>,
    textures: HashMap<Option<super::ResourceId>, Value>,
    witness_hashes: Vec<String>,
    witness_count: usize,
    closed: bool,
}

impl FrameReceipt {
    pub(crate) fn begin(backend: &str) -> Option<Self> {
        REQUEST.with(|pending| pending.borrow_mut().take()).map(|request| {
            let witness = super::frame_witness::mesh(request.frame_index,
                &super::frame_witness::parse_identity(&request.identity).expect("validated request"));
            Self { request, backend: backend.into(), events: Vec::new(), draws: Vec::new(),
                textures: HashMap::new(), witness_hashes: triangle_hashes(&witness.vertices, &witness.indices).expect("valid witness"),
                witness_count: 0, closed: false }
        })
    }
    pub(crate) fn selects(&self, target: Option<&RenderTarget>) -> bool {
        !self.closed && target.is_some_and(|t| t.texture.id == self.request.target.texture.id)
    }
    pub(crate) fn clear(&mut self, target: Option<&RenderTarget>, color: Color) {
        if self.selects(target) {
            self.events.push(json!({"kind":"clear","rgba_bits":[color.r,color.g,color.b,color.a].map(f32::to_bits),"depth_bits":1_f32.to_bits()}));
        }
    }
    #[cfg(any(feature = "legacy-macroquad", test))]
    pub(crate) fn unsupported(&mut self, target: Option<&RenderTarget>, kind: &str) -> Result<(), String> {
        if self.selects(target) { Err(format!("visibility receipt does not support target command {kind}")) } else { Ok(()) }
    }
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn record_draw(&mut self, target: Option<&RenderTarget>, view_projection: Mat4, model: Mat4,
        upload_transform: Option<Mat4>, texture: Option<&Texture>, blend: BlendMode, depth: bool,
        lines: bool, triangle_sha256: Vec<String>, observed_gl_state: Option<Value>) -> Result<(), String>
    {
        if !self.selects(target) { return Ok(()); }
        if lines || triangle_sha256.is_empty() { return Err("visibility receipt requires nonempty triangle draws".into()); }
        if !view_projection.is_finite() || !model.is_finite() || upload_transform.is_some_and(|m| !m.is_finite()) {
            return Err("visibility receipt has a non-finite submitted matrix".into());
        }
        let target = &self.request.target.texture;
        let is_witness = triangle_sha256 == self.witness_hashes
            && matrix_bits(view_projection) == matrix_bits(super::Camera::screen(target.width, target.height).view_projection)
            && matrix_bits(model) == matrix_bits(Mat4::IDENTITY)
            && texture.is_none() && blend == BlendMode::Opaque && !depth;
        let texture = self.textures.entry(texture.map(|t| t.id)).or_insert_with(|| texture_identity(texture)).clone();
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
        let draw = json!({"triangle_count":triangle_sha256.len(),"triangle_sha256":triangle_sha256,
            "view_projection_bits":matrix_bits(view_projection),"model_bits":matrix_bits(model),
            "upload_transform_bits":upload_transform.map(matrix_bits),"texture":texture,"state":state});
        if is_witness {
            self.witness_count += 1;
            self.events.push(json!({"kind":"witness","draw":draw}));
        } else {
            if self.witness_count != 0 { return Err("scene draw follows frame witness before Capture".into()); }
            self.events.push(json!({"kind":"draw","draw_index":self.draws.len()}));
            self.draws.push(draw);
        }
        Ok(())
    }
    pub(crate) fn capture(&mut self, target: Option<&RenderTarget>, path: &Path) -> Result<(), String> {
        if path != self.request.path { return Ok(()); }
        if self.closed || !self.selects(target) { return Err("visibility Capture target/order mismatch".into()); }
        if self.witness_count != 1 || self.draws.is_empty() || !self.events.iter().any(|e| e["kind"] == "clear") {
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
        if !self.closed || !captures.contains(&self.request.path) { return Err("visibility receipt lacks completed ordered readback".into()); }
        let target = &self.request.target.texture;
        let value = json!({"schema":SCHEMA,"capture_identity":self.request.identity,"frame_index":self.request.frame_index,
            "backend":self.backend,"capture_path":self.request.path.file_name().and_then(|s|s.to_str()),
            "capture_sha256":rust_duty_launcher::file_hash(&self.request.path).map_err(|e| e.to_string())?,
            "target":{"resource_id":target.id.0,"width":target.width,"height":target.height,"depth":matches!(target.source,TextureSource::Target {depth:true})},
            "witness_exclusion":[0,0,super::frame_witness::WIDTH,super::frame_witness::HEIGHT],
            "witness_count":self.witness_count,"triangle_count":self.draws.iter().map(|d|d["triangle_count"].as_u64().unwrap_or(0)).sum::<u64>(),
            "draws":self.draws,"events":self.events,"submission_complete":true,"capture_complete":true,
        });
        let path = sidecar(&self.request.path);
        let temporary = path.with_extension("json.pending");
        std::fs::write(&temporary, serde_json::to_vec(&value).map_err(|e|e.to_string())?).map_err(|e|e.to_string())?;
        std::fs::rename(temporary, path).map_err(|e|e.to_string())
    }
}

/// Interpret the exact serialized uniform slot handed to the upload API.
#[cfg(any(feature = "wgpu-runtime", test))]
pub(crate) fn packed_matrix(bytes: &[u8]) -> Result<Mat4, String> {
    if bytes.len() != 64 { return Err("visibility matrix slot is not 64 bytes".into()); }
    let mut values = [0_f32; 16];
    for (value, bytes) in values.iter_mut().zip(bytes.chunks_exact(4)) {
        *value = f32::from_le_bytes(bytes.try_into().expect("four-byte chunk"));
    }
    let matrix = Mat4::from_cols_array(&values);
    if !matrix.is_finite() { return Err("visibility upload matrix is non-finite".into()); }
    Ok(matrix)
}

/// Hash actual packed vertex/index ranges, including order and multiplicity.
/// The first 24 bytes of a native vertex are the canonical position/uv/color.
#[cfg(any(feature = "wgpu-runtime", test))]
pub(crate) fn packed_triangle_hashes(vertices: &[u8], indices: &[u8], stride: usize) -> Result<Vec<String>, String> {
    if stride < 24 || !vertices.len().is_multiple_of(stride) || !indices.len().is_multiple_of(6) {
        return Err("visibility packed triangle extent is invalid".into());
    }
    indices.chunks_exact(6).map(|triangle| {
        let mut bytes = [0_u8; 72];
        for (out, index) in bytes.chunks_exact_mut(24).zip(triangle.chunks_exact(2)) {
            let offset = usize::from(u16::from_le_bytes(index.try_into().expect("u16 index"))) * stride;
            let input = vertices.get(offset..offset + 24).ok_or("visibility packed index out of range")?;
            out.copy_from_slice(input);
        }
        Ok(rust_duty_launcher::bytes_hash(&bytes))
    }).collect()
}

#[cfg(feature = "legacy-macroquad")]
pub(crate) fn check_gl_error() -> Result<(), String> {
    // SAFETY: called only by LegacyRenderer on its verified current GL thread.
    let error = unsafe { macroquad::miniquad::gl::glGetError() };
    if error != 0 { return Err(format!("visibility draw stopped on GL error 0x{error:04x}")); }
    Ok(())
}

/// Exact inputs of a successfully created material, retained only for witnessed
/// capture runs. Miniquad 0.4.8 detaches its vertex shader after linking, so that
/// stage cannot honestly be labelled a live-source query. The selected owned
/// material handle is bound and flushed before its stable program ID is read.
#[cfg(feature = "legacy-macroquad")]
#[cfg_attr(not(all(windows, target_arch = "x86_64")), allow(dead_code))]
pub(crate) struct MaterialSource {
    pub(crate) material_id: u32,
    vertex_sha256: String,
    fragment_sha256: String,
    program: Option<u32>,
}
#[cfg(feature = "legacy-macroquad")]
#[cfg_attr(not(all(windows, target_arch = "x86_64")), allow(dead_code))]
impl MaterialSource {
    pub(crate) fn created(material_id: u32, vertex: &str, fragment: &str) -> Self {
        Self { material_id, vertex_sha256: rust_duty_launcher::bytes_hash(vertex.as_bytes()),
            fragment_sha256: rust_duty_launcher::bytes_hash(fragment.as_bytes()), program: None }
    }
}

/// Read back the actual live shader uniforms after the capture-only chunk flush.
/// This detects inherited Macroquad model-stack state, not just requested model.
#[cfg(all(feature = "legacy-macroquad", windows, target_arch = "x86_64"))]
pub(crate) fn observe_gl(width: u32, height: u32, blend: BlendMode, depth: bool, associated: bool, creation: &mut MaterialSource) -> Result<(Mat4, Mat4, Value), String> {
    use macroquad::miniquad::gl;
    use std::ffi::{c_char, c_void, CStr};
    type GetUniform = unsafe extern "system" fn(u32, i32, *mut f32);
    type GetLocation = unsafe extern "system" fn(u32, *const c_char) -> i32;
    type GetFloat = unsafe extern "system" fn(u32, *mut f32);
    type GetAttached = unsafe extern "system" fn(u32, i32, *mut i32, *mut u32);
    type GetShaderInt = unsafe extern "system" fn(u32, u32, *mut i32);
    type GetShaderSource = unsafe extern "system" fn(u32, i32, *mut i32, *mut c_char);
    type GetActive = unsafe extern "system" fn(u32, u32, i32, *mut i32, *mut i32, *mut u32, *mut c_char);
    type WglLookup = unsafe extern "system" fn(*const c_char) -> *const c_void;
    #[link(name = "kernel32")]
    extern "system" {
        fn GetModuleHandleW(name: *const u16) -> *mut c_void;
        fn GetProcAddress(module: *mut c_void, name: *const c_char) -> *const c_void;
    }
    let valid = |pointer: *const c_void| !matches!(pointer as usize, 0..=3) && pointer as usize != usize::MAX;
    let executable = std::env::current_exe().map_err(|e| e.to_string())?;
    let module_path = executable.parent().ok_or("GL executable has no parent")?.join("opengl32.dll");
    let name: Vec<u16> = module_path.to_str().ok_or("GL module path is not Unicode")?.encode_utf16().chain(Some(0)).collect();
    // SAFETY: observation of the already loaded, app-local GL module only. No
    // DLL loading or context switching is added to ordinary DX/GL launches.
    let module = unsafe { GetModuleHandleW(name.as_ptr()) };
    if module.is_null() { return Err("visibility uniforms require already-loaded app-local OpenGL".into()); }
    let address = unsafe { GetProcAddress(module, c"wglGetProcAddress".as_ptr()) };
    if !valid(address) { return Err("visibility WGL lookup is unavailable".into()); }
    let lookup = unsafe { std::mem::transmute::<*const c_void, WglLookup>(address) };
    let resolve = |name: &CStr| -> Result<*const c_void, String> {
        let address = unsafe { lookup(name.as_ptr()) };
        let address = if valid(address) { address } else { unsafe { GetProcAddress(module, name.as_ptr()) } };
        if valid(address) { Ok(address) } else { Err(format!("visibility GL procedure unavailable: {}", name.to_string_lossy())) }
    };
    let get_uniform = unsafe { std::mem::transmute::<*const c_void, GetUniform>(resolve(c"glGetUniformfv")?) };
    let get_location = unsafe { std::mem::transmute::<*const c_void, GetLocation>(resolve(c"glGetUniformLocation")?) };
    let get_float = unsafe { std::mem::transmute::<*const c_void, GetFloat>(resolve(c"glGetFloatv")?) };
    let get_attached = unsafe { std::mem::transmute::<*const c_void, GetAttached>(resolve(c"glGetAttachedShaders")?) };
    let get_shader_int = unsafe { std::mem::transmute::<*const c_void, GetShaderInt>(resolve(c"glGetShaderiv")?) };
    let get_shader_source = unsafe { std::mem::transmute::<*const c_void, GetShaderSource>(resolve(c"glGetShaderSource")?) };
    let get_program_int = unsafe { std::mem::transmute::<*const c_void, GetShaderInt>(resolve(c"glGetProgramiv")?) };
    let get_active_uniform = unsafe { std::mem::transmute::<*const c_void, GetActive>(resolve(c"glGetActiveUniform")?) };
    let get_active_attribute = unsafe { std::mem::transmute::<*const c_void, GetActive>(resolve(c"glGetActiveAttrib")?) };
    check_gl_error()?;
    let integer = |name| {
        let mut value = 0;
        unsafe { gl::glGetIntegerv(name, &mut value); }
        value
    };
    let four = |name| {
        let mut values = [0_i32; 4];
        unsafe { gl::glGetIntegerv(name, values.as_mut_ptr()); }
        values
    };
    let program = integer(0x8B8D); // GL_CURRENT_PROGRAM
    if program <= 0 { return Err("visibility draw has no bound GL program".into()); }
    let mut attached = [0_u32; 3];
    let mut attached_count = 0;
    unsafe { get_attached(program as u32, 3, &mut attached_count, attached.as_mut_ptr()); }
    if attached_count != 1 { return Err("visibility GL program differs from pinned Miniquad detached-vertex linkage".into()); }
    if creation.program.is_some_and(|expected| expected != program as u32) {
        return Err("visibility material changed its linked GL program".into());
    }
    creation.program = Some(program as u32);
    let mut shaders = vec![json!({"stage":"vertex","source_sha256":creation.vertex_sha256,
        "provenance":"material-creation-input"})];
    for shader in &attached[..1] {
        let mut kind = 0;
        let mut length = 0;
        unsafe { get_shader_int(*shader, 0x8B4F, &mut kind); get_shader_int(*shader, 0x8B88, &mut length); }
        if kind != 0x8B30 { return Err("visibility GL linked fragment shader is missing".into()); }
        let stage = "fragment";
        if !(1..=65536).contains(&length) { return Err("visibility GL shader source length is invalid".into()); }
        let mut source = vec![0_u8; length as usize];
        let mut written = 0;
        unsafe { get_shader_source(*shader, length, &mut written, source.as_mut_ptr().cast()); }
        if written < 0 || written as usize >= source.len() { return Err("visibility GL shader source read was incomplete".into()); }
        source.truncate(written as usize);
        let source_sha256 = rust_duty_launcher::bytes_hash(&source);
        if source_sha256 != creation.fragment_sha256 { return Err(format!("visibility live GL {stage} shader differs from material creation source")); }
        shaders.push(json!({"stage":stage,"source_sha256":source_sha256,"provenance":"live-attached-shader"}));
    }
    shaders.sort_by_key(|shader| if shader["stage"] == "vertex" { 0 } else { 1 });
    if shaders[0]["stage"] != "vertex" || shaders[1]["stage"] != "fragment" {
        return Err("visibility GL shader stage inventory is incomplete".into());
    }
    let interface = |query: GetActive, count_name: u32, expected: &[(&str, u32)]| -> Result<Vec<Value>, String> {
        let mut count = 0;
        unsafe { get_program_int(program as u32, count_name, &mut count); }
        if count != expected.len() as i32 { return Err("visibility GL active shader interface count differs".into()); }
        let mut rows = Vec::new();
        for index in 0..count {
            let mut name = [0_u8; 128];
            let mut length = 0;
            let mut size = 0;
            let mut kind = 0;
            unsafe { query(program as u32, index as u32, 128, &mut length, &mut size, &mut kind, name.as_mut_ptr().cast()); }
            if !(1..128).contains(&length) || size != 1 { return Err("visibility GL active shader interface is unsupported".into()); }
            let name = std::str::from_utf8(&name[..length as usize]).map_err(|e|e.to_string())?;
            if !expected.contains(&(name, kind)) { return Err(format!("visibility GL shader interface differs at {name}")); }
            rows.push(json!({"name":name,"gl_type":kind,"size":size}));
        }
        rows.sort_by(|a,b| a["name"].as_str().cmp(&b["name"].as_str()));
        if rows.windows(2).any(|pair| pair[0]["name"] == pair[1]["name"]) { return Err("visibility GL shader interface repeats a binding".into()); }
        Ok(rows)
    };
    let uniforms = interface(get_active_uniform, 0x8B86, &[("Model",0x8B5C),("Projection",0x8B5C),("Texture",0x8B5E)])?;
    let attributes = interface(get_active_attribute, 0x8B89, &[("position",0x8B51),("texcoord",0x8B50),("color0",0x8B52)])?;
    let uniform = |name: &CStr| -> Result<Mat4, String> {
        let location = unsafe { get_location(program as u32, name.as_ptr()) };
        if location < 0 { return Err(format!("visibility draw lacks {} uniform", name.to_string_lossy())); }
        let mut values = [f32::NAN; 16];
        unsafe { get_uniform(program as u32, location, values.as_mut_ptr()); }
        let matrix = Mat4::from_cols_array(&values);
        if !matrix.is_finite() { return Err("visibility GL uniform query is non-finite".into()); }
        Ok(matrix)
    };
    let projection = uniform(c"Projection")?;
    let model = uniform(c"Model")?;
    let viewport = four(0x0BA2);
    let scissor = four(0x0C10);
    let scissor_enabled = integer(0x0C11) != 0;
    let depth_test = integer(0x0B71) != 0;
    let depth_write_mask = integer(0x0B72) != 0;
    // GL_DEPTH_WRITEMASK alone is not effective writing when depth testing is disabled.
    let depth_write = depth_test && depth_write_mask;
    let depth_compare = integer(0x0B74);
    let cull = integer(0x0B44) != 0;
    let blend_enabled = integer(0x0BE2) != 0;
    let color_mask = four(0x0C23);
    let blend_rgb = [integer(0x80C9), integer(0x80C8), integer(0x8009)];
    let blend_alpha = [integer(0x80CB), integer(0x80CA), integer(0x883D)];
    let front_face = integer(0x0B46);
    let depth_clamp = integer(0x864F) != 0;
    let alpha_to_coverage = integer(0x809E) != 0;
    let sample_coverage = integer(0x80A0) != 0;
    let rasterizer_discard = integer(0x8C89) != 0;
    let mut depth_range = [f32::NAN; 2];
    unsafe { get_float(0x0B70, depth_range.as_mut_ptr()); }
    check_gl_error()?;
    let extent = [0, 0, width as i32, height as i32];
    let effective_depth = depth && blend != BlendMode::Additive;
    let src = if associated { 1 } else { 0x0302 };
    let expected_rgb = [src, if blend == BlendMode::Alpha { 0x0303 } else { 1 }, 0x8006];
    let expected_alpha = if blend == BlendMode::Alpha { [1,0x0303,0x8006] } else { [0,1,0x8006] };
    if viewport != extent || (scissor_enabled && scissor != extent) || cull
        || depth_test != effective_depth || depth_write != effective_depth
        || (effective_depth && depth_compare != 0x0203) || color_mask != [1; 4]
        || front_face != 0x0901 || depth_clamp || alpha_to_coverage || sample_coverage || rasterizer_discard
        || depth_range.map(f32::to_bits) != [0_f32.to_bits(),1_f32.to_bits()]
        || blend_enabled != (blend != BlendMode::Opaque)
        || (blend_enabled && (blend_rgb != expected_rgb || blend_alpha != expected_alpha))
    { return Err("visibility draw has unsupported actual GL raster/depth/blend state".into()); }
    Ok((projection, model, json!({"verified":true,"program":program,"material_id":creation.material_id,
        "material_binding":"created-owned-material-selected-then-flushed","shaders":shaders,
        "uniforms":uniforms,"attributes":attributes,"viewport":viewport,"scissor":scissor,
        "scissor_enabled":scissor_enabled,"depth_test":depth_test,"depth_write":depth_write,"depth_write_mask":depth_write_mask,
        "depth_compare":depth_compare,"cull":cull,"blend_enabled":blend_enabled,
        "blend_rgb":blend_rgb,"blend_alpha":blend_alpha,"color_mask":color_mask,
        "front_face":front_face,"depth_clamp":depth_clamp,"alpha_to_coverage":alpha_to_coverage,
        "sample_coverage":sample_coverage,"rasterizer_discard":rasterizer_discard,
        "depth_range_bits":depth_range.map(f32::to_bits)})))
}

#[cfg(all(feature = "legacy-macroquad", not(all(windows, target_arch = "x86_64"))))]
pub(crate) fn observe_gl(_width: u32, _height: u32, _blend: BlendMode, _depth: bool, _associated: bool, _creation: &mut MaterialSource) -> Result<(Mat4, Mat4, Value), String> {
    Err("native visibility GL uniform receipts require Windows x86_64 app-local OpenGL".into())
}

#[cfg(test)]
mod tests {
    use super::*;
    use glam::{Vec2, Vec3};

    fn triangle() -> [Vertex; 3] {
        [Vec3::ZERO, Vec3::X, Vec3::Y].map(|p| Vertex::new2(p, Vec2::ZERO, Color::WHITE))
    }
    fn receipt(frame_index: u32) -> FrameReceipt {
        let request = Request { path: PathBuf::from("native-frame.png"), target: RenderTarget::new(960,540,true).unwrap(), frame_index, identity: "42".repeat(32) };
        let witness = super::super::frame_witness::mesh(frame_index, &[0x42;32]);
        FrameReceipt { request, backend:"Dx12".into(),events:Vec::new(),draws:Vec::new(),textures:HashMap::new(),
            witness_hashes:triangle_hashes(&witness.vertices,&witness.indices).unwrap(),witness_count:0,closed:false }
    }
    fn scene(receipt: &mut FrameReceipt) {
        let target = receipt.request.target.clone();
        receipt.clear(Some(&target),Color::new(0.14,0.19,0.24,1.));
        receipt.record_draw(Some(&target),Mat4::IDENTITY,Mat4::IDENTITY,Some(Mat4::IDENTITY),None,
            BlendMode::Alpha,true,false,vec![triangle_sha256(&triangle())],None).unwrap();
    }
    fn witness(receipt: &mut FrameReceipt, frame_index: u32, projection: Mat4) {
        let target = receipt.request.target.clone();
        let witness = super::super::frame_witness::mesh(frame_index,&[0x42;32]);
        receipt.record_draw(Some(&target),projection,Mat4::IDENTITY,Some(projection),None,
            BlendMode::Opaque,false,false,triangle_hashes(&witness.vertices,&witness.indices).unwrap(),None).unwrap();
    }
    #[test]
    fn canonical_hash_preserves_every_vertex_bit_order_and_duplicate() {
        let original = triangle();
        let expected = triangle_sha256(&original);
        assert_eq!(expected, "27a90387439cb417b211716e702332d3177781c4edcd37791733093585aa8a97");
        for changed in [
            [original[1],original[0],original[2]],
            {let mut t=original;t[1].position.x=0.5;t},
            {let mut t=original;t[0].uv.x=0.5;t},
            {let mut t=original;t[0].color[3]=254;t},
            {let mut t=original;t[0].position.x=-0.;t},
        ] { assert_ne!(triangle_sha256(&changed),expected); }
        assert_eq!(triangle_hashes(&original,&[0,1,2,0,1,2]).unwrap(),vec![expected.clone(),expected]);
        assert!(triangle_hashes(&original,&[0,1]).is_err());
        assert!(triangle_hashes(&original,&[0,1,3]).is_err());
    }
    #[test]
    fn actual_upload_ranges_bind_geometry_and_matrix_mutations() {
        let original = triangle();
        let mut packed = Vec::new();
        for vertex in original {
            for value in vertex.position.to_array().into_iter().chain(vertex.uv.to_array()) {packed.extend(value.to_le_bytes());}
            packed.extend(vertex.color);packed.extend([0_u8;16]);
        }
        let indices=[0,0,1,0,2,0];
        let expected=packed_triangle_hashes(&packed,&indices,40).unwrap();
        assert_eq!(expected,vec![triangle_sha256(&original)]);
        packed[40..44].copy_from_slice(&0.5_f32.to_le_bytes());
        assert_ne!(packed_triangle_hashes(&packed,&indices,40).unwrap(),expected);
        assert!(packed_triangle_hashes(&packed,&indices[..4],40).is_err());
        assert!(packed_triangle_hashes(&packed,&[0,0,1,0,3,0],40).is_err());
        let mut matrix:Vec<_>=Mat4::IDENTITY.to_cols_array().into_iter().flat_map(f32::to_le_bytes).collect();
        assert_eq!(matrix_bits(packed_matrix(&matrix).unwrap()),matrix_bits(Mat4::IDENTITY));
        matrix[..4].copy_from_slice(&0.5_f32.to_le_bytes());
        assert_ne!(matrix_bits(packed_matrix(&matrix).unwrap()),matrix_bits(Mat4::IDENTITY));
    }
    #[test]
    fn requires_scene_clear_exact_witness_and_matching_ordered_capture() {
        let mut valid=receipt(7);scene(&mut valid);
        witness(&mut valid,7,super::super::Camera::screen(960,540).view_projection);
        let target=valid.request.target.clone();
        valid.capture(Some(&target),Path::new("native-frame.png")).unwrap();
        assert!(valid.closed);
        assert!(valid.finish(&[]).is_err());
        for (frame, projection) in [(8,super::super::Camera::screen(960,540).view_projection),(7,Mat4::IDENTITY)] {
            let mut invalid=receipt(7);scene(&mut invalid);witness(&mut invalid,frame,projection);
            let target=invalid.request.target.clone();
            assert!(invalid.capture(Some(&target),Path::new("native-frame.png")).is_err());
        }
        let mut missing=receipt(7);
        let target=missing.request.target.clone();
        missing.clear(Some(&target),Color::WHITE);
        witness(&mut missing,7,super::super::Camera::screen(960,540).view_projection);
        assert!(missing.capture(Some(&target),Path::new("native-frame.png")).is_err());
    }
    #[test]
    fn target_swaps_unsupported_commands_and_post_witness_scene_fail_closed() {
        let mut current=receipt(0);scene(&mut current);
        let target=current.request.target.clone();
        assert!(current.unsupported(Some(&target),"lines").is_err());
        assert!(current.unsupported(None,"unrelated world lines").is_ok());
        witness(&mut current,0,super::super::Camera::screen(960,540).view_projection);
        let other=RenderTarget::new(960,540,true).unwrap();
        assert!(current.capture(Some(&other),Path::new("native-frame.png")).is_err());
        assert!(current.record_draw(Some(&target),Mat4::IDENTITY,Mat4::IDENTITY,Some(Mat4::IDENTITY),None,
            BlendMode::Alpha,true,false,vec![triangle_sha256(&triangle())],None).is_err());
    }
    #[test]
    fn texture_identity_binds_content_extent_and_sampler() {
        let original=Texture::rgba8(1,1,&[255;4],super::super::Sampler::default()).unwrap();
        assert_eq!(texture_identity(None),texture_identity(Some(&original)));
        let changed=Texture::rgba8(1,1,&[255,255,255,254],super::super::Sampler::default()).unwrap();
        assert_ne!(texture_identity(Some(&original)),texture_identity(Some(&changed)));
        let sampler=super::super::Sampler { filter:FilterMode::Nearest, ..super::super::Sampler::default() };
        let changed=Texture::rgba8(1,1,&[255;4],sampler).unwrap();
        assert_ne!(texture_identity(Some(&original)),texture_identity(Some(&changed)));
    }
}
