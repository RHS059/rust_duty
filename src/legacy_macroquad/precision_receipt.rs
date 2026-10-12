//! Capture capability measurements that do not mutate rendering bindings/resources. Never an acceptance gate.
//!
//! The parent calls this only on an initialized Windows OpenGL render thread,
//! for a validated invocation/frame-witness identity. No shader, texture, FBO,
//! program, sample mode, or binding is changed by this module.
use serde_json::{json, Value};

const GL_VERTEX_SHADER: u32 = 0x8B31;
const GL_FRAGMENT_SHADER: u32 = 0x8B30;
const GL_LOW_FLOAT: u32 = 0x8DF0;
const GL_MEDIUM_FLOAT: u32 = 0x8DF1;
const GL_HIGH_FLOAT: u32 = 0x8DF2;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct Precision {
    range: [i32; 2],
    bits: i32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum QueryFailure {
    Unavailable(&'static str),
    InvalidResult,
    GlError(u32),
    FatalGlError(u32),
    PreexistingGlError(u32),
}

impl QueryFailure {
    fn value(self) -> Value {
        match self {
            Self::Unavailable(reason) => json!({"status":"unavailable","reason":reason}),
            Self::InvalidResult => json!({"status":"unavailable","reason":"invalid_query_result"}),
            Self::GlError(code) => json!({"status":"error","gl_error":code}),
            Self::FatalGlError(code) => json!({"status":"blocked","fatal_gl_error":code}),
            Self::PreexistingGlError(code) => {
                json!({"status":"blocked","preexisting_gl_error":code})
            }
        }
    }
}

trait Queries {
    fn subpixel_bits(&mut self) -> Result<i32, QueryFailure>;
    fn precision(&mut self, stage: u32, qualifier: u32) -> Result<Precision, QueryFailure>;
}

fn valid_precision(value: Precision) -> Result<Precision, QueryFailure> {
    if value.range == [0, 0] && value.bits == 0 {
        return Err(QueryFailure::Unavailable("precision_not_supported"));
    }
    if value.bits <= 0 || value.range.iter().any(|&v| v < 0) {
        return Err(QueryFailure::InvalidResult);
    }
    Ok(value)
}

fn preserve_preexisting_error<T>(
    value: Result<T, QueryFailure>,
) -> Result<Result<T, QueryFailure>, String> {
    match value {
        Err(QueryFailure::PreexistingGlError(code)) => Err(format!(
            "GL capability capture stopped on pre-existing GL error 0x{code:04x}; error was observed, not ignored"
        )),
        Err(QueryFailure::FatalGlError(code)) => Err(format!(
            "GL capability capture stopped on fatal query error 0x{code:04x}; no further query or readback is safe"
        )),
        other => Ok(other),
    }
}

fn collect(
    identity: &str,
    adapter: &str,
    version: &str,
    query: &mut impl Queries,
) -> Result<Value, String> {
    let subpixel = preserve_preexisting_error(query.subpixel_bits())?;
    let subpixel = match subpixel {
        Ok(bits) if bits > 0 => json!({"status":"reported","bits":bits}),
        Ok(_) => QueryFailure::InvalidResult.value(),
        Err(error) => error.value(),
    };
    let mut measurements = serde_json::Map::new();
    for (name, stage, qualifier) in [
        ("vertex_high_float", GL_VERTEX_SHADER, GL_HIGH_FLOAT),
        ("vertex_low_float", GL_VERTEX_SHADER, GL_LOW_FLOAT),
        ("fragment_medium_float", GL_FRAGMENT_SHADER, GL_MEDIUM_FLOAT),
        ("fragment_low_float", GL_FRAGMENT_SHADER, GL_LOW_FLOAT),
    ] {
        let result = preserve_preexisting_error(query.precision(stage, qualifier))?
            .and_then(valid_precision);
        let value = match result {
            Ok(precision) => {
                json!({"status":"reported","range":precision.range,"precision_bits":precision.bits})
            }
            Err(error) => error.value(),
        };
        measurements.insert(name.into(), value);
    }
    let complete = subpixel["status"] == "reported"
        && measurements.values().all(|row| row["status"] == "reported");
    Ok(json!({
        "schema":"rust-duty-gl-precision-receipt/v1",
        "capture_identity":identity,
        "backend":"OpenGl",
        "platform":"windows",
        "architecture":"x86_64",
        "phase":"capture_before_readback",
        "adapter":adapter,
        "gl_version":version,
        "subpixel":subpixel,
        "shader_precision":measurements,
        "measurement_complete":complete,
        "raster_error_bounds_verified":false,
        "procedure_resolution":"already_loaded_app_local_opengl32_only",
        "gl_error_observation":"Consumes error flags; aborts on the first pre-existing or fatal query error.",
        "acceptance_verdict":null,
        "scope":"Reported context capabilities only. Does not establish compiler, clipping, interpolation, source completeness or capture acceptance."
    }))
}

/// Limit the probe to a known core API; pointer presence is not feature proof.
fn desktop_gl_4_1(version: &str) -> bool {
    let Some(token) = version.split_whitespace().next() else {
        return false;
    };
    let Some((major, rest)) = token.split_once('.') else {
        return false;
    };
    if major.is_empty() || !major.bytes().all(|b| b.is_ascii_digit()) {
        return false;
    }
    let minor: String = rest.chars().take_while(char::is_ascii_digit).collect();
    match (major.parse::<u32>(), minor.parse::<u32>()) {
        (Ok(major), Ok(minor)) => (major, minor) >= (4, 1),
        _ => false,
    }
}

/// WGL may return small integer sentinels or -1 for unsupported procedures.
fn valid_wgl_address(address: usize) -> bool {
    !matches!(address, 0..=3) && address != usize::MAX
}

pub(super) fn target_capture(
    identity: &str,
    target: u64,
    width: u32,
    height: u32,
    depth: bool,
    capture_path: &std::path::Path,
) -> Value {
    json!({
        "schema":"rust-duty-gl-target-capture-receipt/v1",
        "capture_identity":identity,
        "target_resource_id":target,
        "capture_path":capture_path.to_string_lossy(),
        "width":width,"height":height,"depth":depth,
        "miniquad_sample_count_parameter":0,
        "allocation":"plain_non_resolving_texture_target",
        "evidence_basis":"Source-owned macroquad render_target_ex parameters, miniquad 0.4.8 GL_TEXTURE_2D path.",
        "queried_framebuffer_samples":null,
        "phase":"capture_before_readback",
        "acceptance_verdict":null
    })
}

#[cfg(all(windows, target_arch = "x86_64"))]
mod native {
    use super::*;
    use macroquad::miniquad as mq;
    use std::ffi::{c_char, c_void};

    type GetPrecision = unsafe extern "system" fn(u32, u32, *mut i32, *mut i32);

    type GetCurrentContext = unsafe extern "system" fn() -> *mut c_void;
    type GetWglProcAddress = unsafe extern "system" fn(*const c_char) -> *const c_void;

    // Kernel32 is already a Windows process dependency. In particular, do not
    // statically import opengl32 or call LoadLibrary: ordinary DX launches must
    // not acquire a GL loading/initialization side effect from this diagnostic.
    #[link(name = "kernel32")]
    extern "system" {
        fn GetModuleHandleW(name: *const u16) -> *mut c_void;
        fn GetProcAddress(module: *mut c_void, name: *const c_char) -> *const c_void;
    }

    struct NativeQueries {
        get_precision: Option<GetPrecision>,
        unavailable: &'static str,
        current_context: bool,
    }

    impl NativeQueries {
        /// Caller must own the initialized OpenGL context on this render thread.
        unsafe fn new(version: &str) -> Self {
            // Restrict to the independently staged app-local GL module. A
            // full path avoids ambiguous basename selection if another module
            // named opengl32.dll is loaded. Missing/non-Unicode paths stay
            // explicitly unavailable; this code never loads a fallback DLL.
            let unavailable = |reason| Self {
                get_precision: None,
                unavailable: reason,
                current_context: false,
            };
            let Ok(executable) = std::env::current_exe() else {
                return unavailable("current_executable_unavailable");
            };
            let Some(directory) = executable.parent() else {
                return unavailable("current_executable_directory_unavailable");
            };
            let module_path = directory.join("opengl32.dll");
            let Some(module_path) = module_path.to_str() else {
                return unavailable("app_local_gl_path_not_unicode");
            };
            let module_path: Vec<u16> = module_path.encode_utf16().chain(Some(0)).collect();
            // SAFETY: Valid NUL-terminated UTF-16 path. GetModuleHandleW only
            // observes an already-loaded module; no reference count is added.
            // Miniquad's live WindowsDisplay owns the module throughout this
            // synchronous render-thread call, so it cannot be unloaded here.
            let module = unsafe { GetModuleHandleW(module_path.as_ptr()) };
            if module.is_null() {
                return unavailable("app_local_opengl32_not_already_loaded");
            }
            // SAFETY: A live module handle and static NUL-terminated export
            // names. These lookups do not load or invoke either export.
            let context_address =
                unsafe { GetProcAddress(module, c"wglGetCurrentContext".as_ptr()) };
            let lookup_address = unsafe { GetProcAddress(module, c"wglGetProcAddress".as_ptr()) };
            if !valid_wgl_address(context_address as usize)
                || !valid_wgl_address(lookup_address as usize)
            {
                return unavailable("required_wgl_export_unavailable");
            }
            // SAFETY: Named, validated WGL exports with their exact Windows-x64
            // system ABI/signatures. Pointers stay local to the live module.
            let get_context =
                unsafe { std::mem::transmute::<*const c_void, GetCurrentContext>(context_address) };
            let get_wgl_proc =
                unsafe { std::mem::transmute::<*const c_void, GetWglProcAddress>(lookup_address) };
            // SAFETY: Query only; no context is created, switched or released.
            let current_context = unsafe { !get_context().is_null() };
            if !current_context {
                return unavailable("no_current_wgl_context");
            }
            // This deliberately narrow probe supports the desktop core API
            // from 4.1 onward. It does not infer support from a nonnull address
            // or probe extensions on older/core contexts. Older contexts remain
            // explicitly unavailable, even if an extension might support it.
            if !desktop_gl_4_1(version) {
                return Self {
                    get_precision: None,
                    unavailable: "probe_requires_desktop_gl_4_1_or_newer",
                    current_context,
                };
            }
            // SAFETY: Static NUL-terminated ASCII name. Querying a procedure
            // address does not invoke it or mutate any OpenGL binding.
            let address = unsafe { get_wgl_proc(c"glGetShaderPrecisionFormat".as_ptr()) };
            let get_precision = if valid_wgl_address(address as usize) {
                // SAFETY: The named OpenGL procedure has this exact APIENTRY
                // (Windows system) ABI and signature. All WGL sentinel values
                // were rejected before the function pointer is constructed.
                Some(unsafe { std::mem::transmute::<*const c_void, GetPrecision>(address) })
            } else {
                None
            };
            Self {
                get_precision,
                unavailable: "glGetShaderPrecisionFormat_unavailable",
                current_context,
            }
        }

        fn preflight(&self) -> Result<(), QueryFailure> {
            if !self.current_context {
                return Err(QueryFailure::Unavailable(self.unavailable));
            }
            // SAFETY: Initialized miniquad GL dispatch and current render-thread
            // context were established before constructing this query object.
            // A pre-existing error is reported and aborts the capture startup;
            // it is never drained/hidden to make the measurement look clean.
            let error = unsafe { mq::gl::glGetError() };
            if error == mq::gl::GL_NO_ERROR {
                Ok(())
            } else {
                Err(QueryFailure::PreexistingGlError(error))
            }
        }

        fn result<T>(&self, value: T) -> Result<T, QueryFailure> {
            // SAFETY: Same initialized/current context; records only the error
            // from the immediately preceding read-only query.
            let error = unsafe { mq::gl::glGetError() };
            if error == mq::gl::GL_NO_ERROR {
                Ok(value)
            } else if matches!(error, 0x0505 | 0x0507) {
                // GL_OUT_OF_MEMORY may leave undefined state; GL_CONTEXT_LOST
                // invalidates further operations. Neither is just a missing cap.
                Err(QueryFailure::FatalGlError(error))
            } else {
                Err(QueryFailure::GlError(error))
            }
        }
    }

    impl Queries for NativeQueries {
        fn subpixel_bits(&mut self) -> Result<i32, QueryFailure> {
            self.preflight()?;
            let mut value = -1;
            // SAFETY: GL_SUBPIXEL_BITS is an integer scalar query and value is
            // valid writable storage for exactly one GLint.
            unsafe { mq::gl::glGetIntegerv(mq::gl::GL_SUBPIXEL_BITS, &mut value) };
            self.result(value)
        }

        fn precision(&mut self, stage: u32, qualifier: u32) -> Result<Precision, QueryFailure> {
            self.preflight()?;
            let function = self
                .get_precision
                .ok_or(QueryFailure::Unavailable(self.unavailable))?;
            let mut value = Precision {
                range: [-1; 2],
                bits: -1,
            };
            // SAFETY: Validated named procedure and system ABI. Constants are
            // known shader/float-precision enums. GL writes two range integers
            // and one precision integer into live, correctly sized storage.
            unsafe { function(stage, qualifier, value.range.as_mut_ptr(), &mut value.bits) };
            self.result(value)
        }
    }

    /// Must be called only after verifying the initialized backend is OpenGL.
    pub(super) unsafe fn measure(
        identity: &str,
        adapter: &str,
        version: &str,
    ) -> Result<Value, String> {
        // SAFETY: The render-thread/context precondition is carried by caller.
        let mut query = unsafe { NativeQueries::new(version) };
        collect(identity, adapter, version, &mut query)
    }
}

#[cfg(all(windows, target_arch = "x86_64"))]
pub(super) unsafe fn measure(
    identity: &str,
    adapter: &str,
    version: &str,
) -> Result<Value, String> {
    // SAFETY: Caller verifies an initialized native OpenGL render-thread context.
    unsafe { native::measure(identity, adapter, version) }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Fake {
        subpixel: Result<i32, QueryFailure>,
        precision: Result<Precision, QueryFailure>,
        calls: Vec<(u32, u32)>,
    }
    impl Queries for Fake {
        fn subpixel_bits(&mut self) -> Result<i32, QueryFailure> {
            self.subpixel
        }
        fn precision(&mut self, stage: u32, qualifier: u32) -> Result<Precision, QueryFailure> {
            self.calls.push((stage, qualifier));
            self.precision
        }
    }
    fn supported() -> Fake {
        Fake {
            subpixel: Ok(8),
            precision: Ok(Precision {
                range: [127, 127],
                bits: 23,
            }),
            calls: vec![],
        }
    }
    #[test]
    fn all_queries_and_identity_are_recorded_without_acceptance() {
        let mut q = supported();
        let r = collect(&"a".repeat(64), "actual adapter", "actual version", &mut q).unwrap();
        assert_eq!(r["measurement_complete"], true);
        assert!(r["acceptance_verdict"].is_null());
        assert_eq!(r["raster_error_bounds_verified"], false);
        assert_eq!(r["subpixel"]["bits"], 8);
        assert_eq!(
            q.calls,
            vec![
                (GL_VERTEX_SHADER, GL_HIGH_FLOAT),
                (GL_VERTEX_SHADER, GL_LOW_FLOAT),
                (GL_FRAGMENT_SHADER, GL_MEDIUM_FLOAT),
                (GL_FRAGMENT_SHADER, GL_LOW_FLOAT)
            ]
        );
    }
    #[test]
    fn missing_function_is_explicit_and_has_no_invented_precision() {
        let mut q = supported();
        q.precision = Err(QueryFailure::Unavailable("missing"));
        let r = collect("identity", "adapter", "version", &mut q).unwrap();
        assert_eq!(r["measurement_complete"], false);
        let p = &r["shader_precision"]["vertex_high_float"];
        assert_eq!(p["status"], "unavailable");
        assert!(p.get("precision_bits").is_none());
    }
    #[test]
    fn zero_or_negative_query_results_never_become_reported_capabilities() {
        for p in [
            Precision {
                range: [0, 0],
                bits: 0,
            },
            Precision {
                range: [-1, 127],
                bits: 23,
            },
            Precision {
                range: [127, 127],
                bits: -1,
            },
        ] {
            let mut q = supported();
            q.precision = Ok(p);
            q.subpixel = Ok(-1);
            assert_eq!(
                collect("id", "a", "v", &mut q).unwrap()["measurement_complete"],
                false
            );
        }
    }
    #[test]
    fn preexisting_gl_errors_are_not_hidden_or_followed_by_queries() {
        let mut q = supported();
        q.subpixel = Err(QueryFailure::PreexistingGlError(0x0502));
        assert!(collect("id", "a", "v", &mut q)
            .unwrap_err()
            .contains("pre-existing GL error"));
        assert!(q.calls.is_empty());
    }
    #[test]
    fn fatal_query_errors_stop_before_any_further_measurement() {
        for code in [0x0505, 0x0507] {
            let mut q = supported();
            q.precision = Err(QueryFailure::FatalGlError(code));
            let error = collect("id", "a", "v", &mut q).unwrap_err();
            assert!(error.contains("fatal query error"));
            assert!(error.contains(&format!("0x{code:04x}")));
            assert_eq!(q.calls.len(), 1);
        }
    }

    #[test]
    fn query_errors_are_recorded_and_leave_measurement_incomplete() {
        let mut q = supported();
        q.precision = Err(QueryFailure::GlError(0x0500));
        let r = collect("id", "a", "v", &mut q).unwrap();
        assert_eq!(r["measurement_complete"], false);
        assert_eq!(
            r["shader_precision"]["vertex_high_float"]["gl_error"],
            0x0500
        );
    }
    #[test]
    fn advertised_core_support_is_required_independently_of_pointer_presence() {
        for version in [
            "4.1 Mesa",
            "4.5 (Compatibility Profile) Mesa",
            "4.6.0 Vendor",
            "5.0 Vendor",
        ] {
            assert!(desktop_gl_4_1(version));
        }
        for version in [
            "",
            "3.3 Mesa",
            "4.0 Mesa",
            "OpenGL ES 3.2 Mesa",
            "malformed",
            "4.x",
        ] {
            assert!(!desktop_gl_4_1(version));
        }
        assert!(valid_wgl_address(0x10000));
        assert!(!desktop_gl_4_1("3.3 Mesa"));
    }

    #[test]
    fn every_documented_wgl_sentinel_is_rejected() {
        for address in [0, 1, 2, 3, usize::MAX] {
            assert!(!valid_wgl_address(address));
        }
        assert!(valid_wgl_address(0x10000));
    }
    #[test]
    fn target_receipt_is_source_evidence_not_a_default_framebuffer_query() {
        let r = target_capture("id", 9, 960, 540, true, std::path::Path::new("0000.png"));
        assert_eq!(r["miniquad_sample_count_parameter"], 0);
        assert!(r["queried_framebuffer_samples"].is_null());
        assert_eq!(r["target_resource_id"], 9);
        assert_eq!(r["capture_path"], "0000.png");
        assert!(r["acceptance_verdict"].is_null());
    }
}
