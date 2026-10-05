//! Native DX12 world-primitive contract for the public drawing facade.
//!
//! World lines, wire boxes and spheres are recorded through `draw::facade` under
//! one fixture-specified perspective camera, rendered by `WgpuRenderer`, read
//! back as PNG files and judged against pinhole projection computed in this file
//! without glam or renderer code. Expected regions never come from captures.
//! The flat quads, depth-target, alpha, text and readback-stride cases of
//! `examples/renderer_contract.rs` are deliberately not repeated here.
//!
//! Windows, from the repository root, with a fresh output directory:
//!
//! ```text
//! cargo run --locked --no-default-features --features wgpu-runtime --example world_primitives_contract -- --renderer=dx12 --force-fallback-adapter --output-dir evidence/world-primitives-dx12
//! ```
//!
//! This is headless renderer evidence only. The camera and primitives belong to
//! the fixture; nothing here describes an authored scene or the game camera.

#[cfg(feature = "wgpu-runtime")]
fn main() {
    if let Err(error) = fixture::run(std::env::args().skip(1)) {
        eprintln!("world_primitives_contract: {error}");
        std::process::exit(1);
    }
}

#[cfg(not(feature = "wgpu-runtime"))]
fn main() {
    eprintln!(
        "world_primitives_contract requires --features wgpu-runtime; native validation requires Windows DX12"
    );
    std::process::exit(1);
}

#[cfg(any(feature = "wgpu-runtime", test))]
mod fixture {
    use glam::{Mat4, Vec3};
    use image::RgbaImage;
    use serde_json::{json, Value};
    use std::{
        fs,
        path::{Path, PathBuf},
    };
    use vector_range::draw::{facade, Color, Command, DrawList};
    #[cfg(feature = "wgpu-runtime")]
    use vector_range::{
        draw::{BackendInfo, Renderer},
        render::{BackendSelection, WgpuRenderer},
    };

    const WIDTH: u32 = 128;
    const HEIGHT: u32 = 128;
    // Fixture camera: eye (0,0,5) looking at the origin, +Y up, vertical field of
    // view 90 degrees (tan 45 = 1), aspect 1, near 1, far 20.
    const EYE_Z: f64 = 5.;
    const Z_NEAR: f64 = 1.;
    const Z_FAR: f64 = 20.;
    /// Per-channel tolerance, identical to the existing renderer contract.
    const TOLERANCE: u8 = 8;
    /// Aliased 1 px lines light pixels whose centres lie within ~0.71 px of the
    /// projected segment; 1.5 px allows rasterizer rounding but rejects a 2 px shift.
    const LINE_BAND: f64 = 1.5;
    /// No MSAA: a disk edge is ambiguous for at most one pixel on either side.
    const DISK_MARGIN: f64 = 1.;
    /// Presence samples stay this far from segment ends and clip points.
    const END_MARGIN: f64 = 2.5;
    /// Forbidden bands begin this far beyond a visible end (> 2 * LINE_BAND).
    const FORBIDDEN_GAP: f64 = 3.5;
    /// Presence samples this close to a nearer primitive's possible region are skipped.
    const OCCLUDER_MARGIN: f64 = 2.;
    const MIN_PRESENCE_SAMPLES: usize = 4;
    const REPORT: &str = "world-primitives-contract-report.json";
    #[cfg(feature = "wgpu-runtime")]
    const OPAQUE: &str = "opaque-rgba8-rgb-preserved-over-black";
    #[cfg(feature = "wgpu-runtime")]
    const SCOPE: &str = "headless DX12 world-primitive contract (public facade world lines, wire boxes and spheres under a fixture-specified camera); not authored scenes, game cameras, window presentation, native DPI, performance or artistic approval";

    const BACKGROUND: [u8; 3] = [0, 0, 0];
    const RED: [u8; 3] = [255, 0, 0];
    const GREEN: [u8; 3] = [0, 255, 0];
    const BLUE: [u8; 3] = [0, 0, 255];
    const YELLOW: [u8; 3] = [255, 255, 0];
    const CYAN: [u8; 3] = [0, 255, 255];
    const MAGENTA: [u8; 3] = [255, 0, 255];
    const WHITE: [u8; 3] = [255, 255, 255];

    #[derive(Debug, PartialEq, Eq)]
    struct Options {
        force_fallback_adapter: bool,
        output_dir: PathBuf,
    }

    impl Options {
        fn parse(args: impl IntoIterator<Item = impl Into<String>>) -> Result<Self, String> {
            let mut args = args.into_iter().map(Into::into);
            let mut renderer = None;
            let mut output_dir = None;
            let mut force_fallback_adapter = false;
            while let Some(arg) = args.next() {
                match arg.as_str() {
                    "--force-fallback-adapter" => {
                        if force_fallback_adapter {
                            return Err(
                                "--force-fallback-adapter may be specified only once".into()
                            );
                        }
                        force_fallback_adapter = true;
                    }
                    "--renderer" => {
                        let value = args.next().ok_or("--renderer requires dx12")?;
                        set_once(&mut renderer, value, "--renderer")?;
                    }
                    "--output-dir" => {
                        let value = args.next().ok_or("--output-dir requires a directory")?;
                        set_once(&mut output_dir, value, "--output-dir")?;
                    }
                    _ if arg.starts_with("--renderer=") => {
                        set_once(&mut renderer, arg[11..].to_owned(), "--renderer")?;
                    }
                    _ if arg.starts_with("--output-dir=") => {
                        set_once(&mut output_dir, arg[13..].to_owned(), "--output-dir")?;
                    }
                    _ => return Err(format!("unknown fixture argument {arg:?}")),
                }
            }
            if renderer.as_deref() != Some("dx12") {
                return Err(
                    "this fixture requires explicit --renderer=dx12; no other backend is accepted"
                        .into(),
                );
            }
            let output_dir = output_dir
                .filter(|value| !value.trim().is_empty() && !value.starts_with("--"))
                .ok_or("--output-dir requires an explicit nonempty directory")?;
            Ok(Self {
                force_fallback_adapter,
                output_dir: PathBuf::from(output_dir),
            })
        }
    }

    fn set_once(slot: &mut Option<String>, value: String, name: &str) -> Result<(), String> {
        if slot.replace(value).is_some() {
            return Err(format!("{name} may be specified only once"));
        }
        Ok(())
    }

    fn prepare_output(path: &Path) -> Result<(), String> {
        if path.exists() {
            let mut entries = fs::read_dir(path)
                .map_err(|error| format!("read output directory {}: {error}", path.display()))?;
            if entries
                .next()
                .transpose()
                .map_err(|error| format!("read output entry: {error}"))?
                .is_some()
            {
                return Err(format!("output directory {} must be empty; choose a fresh directory so stale evidence cannot pass", path.display()));
            }
        } else {
            fs::create_dir_all(path)
                .map_err(|error| format!("create output directory {}: {error}", path.display()))?;
        }
        Ok(())
    }

    fn read_png(path: &Path, width: u32, height: u32) -> Result<RgbaImage, String> {
        let image = image::io::Reader::open(path)
            .map_err(|error| format!("read PNG {}: {error}", path.display()))?
            .with_guessed_format()
            .map_err(|error| format!("identify PNG {}: {error}", path.display()))?;
        if image.format() != Some(image::ImageFormat::Png) {
            return Err(format!("{} is not a PNG", path.display()));
        }
        let image = image
            .decode()
            .map_err(|error| format!("decode PNG {}: {error}", path.display()))?;
        if image.width() != width
            || image.height() != height
            || image.color() != image::ColorType::Rgba8
        {
            return Err(format!(
                "{} expected {width}x{height} RGBA8, got {}x{} {:?}",
                path.display(),
                image.width(),
                image.height(),
                image.color()
            ));
        }
        Ok(image.into_rgba8())
    }

    fn write_json(path: &Path, value: &Value) -> Result<(), String> {
        let mut bytes =
            serde_json::to_vec_pretty(value).map_err(|error| format!("encode JSON: {error}"))?;
        bytes.push(b'\n');
        fs::write(path, bytes).map_err(|error| format!("write JSON {}: {error}", path.display()))
    }

    #[cfg(feature = "wgpu-runtime")]
    fn verify_backend(info: &BackendInfo) -> Result<(), String> {
        if info.requested != "dx12" || info.backend != "Dx12" || info.adapter.trim().is_empty() {
            return Err(format!("DX12 evidence requires requested=dx12, actual backend=Dx12 and a named adapter; got {info:?}"));
        }
        Ok(())
    }

    // ---- Independent analytic camera model -------------------------------------

    type P2 = [f64; 2];
    type P3 = [f64; 3];

    fn widen(v: [f32; 3]) -> P3 {
        v.map(f64::from)
    }
    fn add3(a: P3, b: P3) -> P3 {
        std::array::from_fn(|i| a[i] + b[i])
    }
    fn sub3(a: P3, b: P3) -> P3 {
        std::array::from_fn(|i| a[i] - b[i])
    }
    fn dot3(a: P3, b: P3) -> f64 {
        a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    }
    fn cross3(a: P3, b: P3) -> P3 {
        [
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        ]
    }
    fn lerp3(a: P3, b: P3, t: f64) -> P3 {
        std::array::from_fn(|i| a[i] + (b[i] - a[i]) * t)
    }
    fn distance(a: P2, b: P2) -> f64 {
        (a[0] - b[0]).hypot(a[1] - b[1])
    }
    fn segment_distance(p: P2, a: P2, b: P2) -> f64 {
        let d = [b[0] - a[0], b[1] - a[1]];
        let len2 = d[0] * d[0] + d[1] * d[1];
        let t = if len2 == 0. {
            0.
        } else {
            (((p[0] - a[0]) * d[0] + (p[1] - a[1]) * d[1]) / len2).clamp(0., 1.)
        };
        distance(p, [a[0] + d[0] * t, a[1] + d[1] * t])
    }
    /// Point at `gap` pixels from `a` toward `b`.
    fn toward(a: P2, b: P2, gap: f64) -> P2 {
        let len = distance(a, b);
        [
            a[0] + (b[0] - a[0]) * gap / len,
            a[1] + (b[1] - a[1]) * gap / len,
        ]
    }
    /// Distance in front of the eye along its -Z view axis.
    fn view_depth(p: P3) -> f64 {
        EYE_Z - p[2]
    }
    /// Pinhole projection to top-left pixel coordinates. With a negative depth
    /// this is the naive divide that clipping must prevent from appearing.
    fn project(p: P3) -> P2 {
        let d = view_depth(p);
        [
            (p[0] / d + 1.) * f64::from(WIDTH) / 2.,
            (1. - p[1] / d) * f64::from(HEIGHT) / 2.,
        ]
    }
    fn point_at_depth(a: P3, b: P3, depth: f64) -> P3 {
        let (da, db) = (view_depth(a), view_depth(b));
        lerp3(a, b, (depth - da) / (db - da))
    }
    /// The part of a world segment with near <= depth <= far, if any.
    fn clip_to_depth_range(a: P3, b: P3) -> Option<(P3, P3)> {
        let (da, db) = (view_depth(a), view_depth(b));
        if da.max(db) < Z_NEAR || da.min(db) > Z_FAR {
            return None;
        }
        let clamp = |p: P3, d: f64| {
            if d < Z_NEAR {
                point_at_depth(a, b, Z_NEAR)
            } else if d > Z_FAR {
                point_at_depth(a, b, Z_FAR)
            } else {
                p
            }
        };
        Some((clamp(a, da), clamp(b, db)))
    }
    /// Silhouette radius in pixels of an on-axis ball: tan(asin(r / d)) / tan(45 deg).
    fn sphere_silhouette_px(depth: f64, radius: f64) -> f64 {
        f64::from(WIDTH) / 2. * radius / (depth * depth - radius * radius).sqrt()
    }
    /// The twelve edges of an axis-aligned box: corner pairs differing in one axis.
    fn box_edges(center: P3, size: P3) -> Vec<(P3, P3)> {
        let corner = |i: usize| -> P3 {
            std::array::from_fn(|axis| {
                center[axis] + size[axis] / 2. * if i >> axis & 1 == 0 { -1. } else { 1. }
            })
        };
        let mut edges = Vec::new();
        for i in 0..8_usize {
            for j in i + 1..8 {
                if (i ^ j).count_ones() == 1 {
                    edges.push((corner(i), corner(j)));
                }
            }
        }
        edges
    }

    // ---- Fixture scenes -------------------------------------------------------

    #[derive(Clone, Copy, Debug)]
    enum Primitive {
        Line { start: [f32; 3], end: [f32; 3] },
        WireBox { center: [f32; 3], size: [f32; 3] },
        Sphere { center: [f32; 3], radius: f32 },
    }

    #[derive(Clone, Copy, Debug)]
    struct Draw {
        label: &'static str,
        rgb: [u8; 3],
        /// Depth order in every overlap: lower is nearer the eye.
        rank: u32,
        translation: [f32; 3],
        primitive: Primitive,
    }

    #[derive(Clone, Copy, Debug)]
    enum Area {
        Band { a: P2, b: P2 },
        Rect { x0: f64, x1: f64, y0: f64, y1: f64 },
    }
    impl Area {
        fn contains(&self, p: P2) -> bool {
            match *self {
                Self::Band { a, b } => segment_distance(p, a, b) <= LINE_BAND,
                Self::Rect { x0, x1, y0, y1 } => {
                    (x0..=x1).contains(&p[0]) && (y0..=y1).contains(&p[1])
                }
            }
        }
        fn json(&self) -> Value {
            match *self {
                Self::Band { a, b } => {
                    json!({"band": {"from": a, "to": b, "half_width_px": LINE_BAND}})
                }
                Self::Rect { x0, x1, y0, y1 } => json!({"rect": {"x": [x0, x1], "y": [y0, y1]}}),
            }
        }
    }

    #[derive(Clone, Copy, Debug)]
    struct Forbidden {
        label: &'static str,
        area: Area,
    }

    #[derive(Clone, Debug)]
    struct Case {
        filename: &'static str,
        case: &'static str,
        claim: &'static str,
        draws: Vec<Draw>,
        forbidden: Vec<Forbidden>,
    }

    fn line(label: &'static str, rgb: [u8; 3], rank: u32, start: [f32; 3], end: [f32; 3]) -> Draw {
        Draw {
            label,
            rgb,
            rank,
            translation: [0.; 3],
            primitive: Primitive::Line { start, end },
        }
    }

    fn line_ends(draw: &Draw) -> (P3, P3) {
        match draw.primitive {
            Primitive::Line { start, end } => {
                let t = widen(draw.translation);
                (add3(widen(start), t), add3(widen(end), t))
            }
            _ => unreachable!("line_ends is only called on fixture lines"),
        }
    }

    fn perspective_case() -> Case {
        // Rows 24 and 72 and column 8 are pixel centres at their depths.
        let red = line(
            "red world line at depth 5",
            RED,
            0,
            [-3.75, 3.085_937_5, 0.],
            [3.75, 3.085_937_5, 0.],
        );
        let green = line(
            "green world line of equal length at depth 16",
            GREEN,
            0,
            [-3.75, -2.125, -11.],
            [3.75, -2.125, -11.],
        );
        let blue = line(
            "vertical blue world line at depth 5",
            BLUE,
            0,
            [-4.335_937_5, -2.5, 0.],
            [-4.335_937_5, 2.5, 0.],
        );
        let (red_a, red_b) = line_ends(&red);
        let (green_a, green_b) = line_ends(&green);
        let (ga, gb) = (project(green_a), project(green_b));
        let row = ga[1];
        Case {
            filename: "world-line-perspective.png",
            case: "world-line-perspective-scaling",
            claim: "facade world lines land on their analytic projections; equal world lengths shrink by 5/16 at depth 16",
            draws: vec![red, green, blue],
            forbidden: vec![
                Forbidden {
                    label: "row of far green line left of its perspective endpoint",
                    area: Area::Band {
                        a: [project(red_a)[0], row],
                        b: [ga[0] - FORBIDDEN_GAP, row],
                    },
                },
                Forbidden {
                    label: "row of far green line right of its perspective endpoint",
                    area: Area::Band {
                        a: [gb[0] + FORBIDDEN_GAP, row],
                        b: [project(red_b)[0], row],
                    },
                },
            ],
        }
    }

    fn clip_case() -> Case {
        let far_crossing = line(
            "yellow line from depth 15 to 30 crossing the far plane",
            YELLOW,
            0,
            [12., 3., -10.],
            [12., 3., -25.],
        );
        let near_crossing = line(
            "cyan line from depth 4 to 0.5 crossing the near plane",
            CYAN,
            0,
            [-0.5, -0.25, 1.],
            [-0.5, -0.25, 4.5],
        );
        let beyond_far = line(
            "magenta line entirely at depth 25",
            MAGENTA,
            0,
            [-6., 6., -20.],
            [6., 6., -20.],
        );
        let behind_eye = line(
            "white line entirely behind the eye",
            WHITE,
            0,
            [-1., -1., 7.],
            [1., -1., 7.],
        );
        let (fa, fb) = line_ends(&far_crossing);
        let far_clip = project(point_at_depth(fa, fb, Z_FAR));
        let (na, nb) = line_ends(&near_crossing);
        let near_clip = project(point_at_depth(na, nb, Z_NEAR));
        let (ma, mb) = line_ends(&beyond_far);
        let (wa, wb) = line_ends(&behind_eye);
        Case {
            filename: "world-line-clip-range.png",
            case: "world-line-near-far-and-behind-eye-clipping",
            claim: "world lines are clipped exactly at the camera near/far depths and never wrap from behind the eye",
            draws: vec![far_crossing, near_crossing, beyond_far, behind_eye],
            forbidden: vec![
                Forbidden {
                    label: "yellow line beyond the far plane",
                    area: Area::Band {
                        a: toward(far_clip, project(fb), FORBIDDEN_GAP),
                        b: project(fb),
                    },
                },
                Forbidden {
                    label: "cyan line nearer than the near plane",
                    area: Area::Band {
                        a: toward(near_clip, project(nb), FORBIDDEN_GAP),
                        b: project(nb),
                    },
                },
                Forbidden {
                    label: "magenta line beyond the far plane",
                    area: Area::Band {
                        a: project(ma),
                        b: project(mb),
                    },
                },
                Forbidden {
                    label: "naive divide image of the white line behind the eye",
                    area: Area::Band {
                        a: project(wa),
                        b: project(wb),
                    },
                },
            ],
        }
    }

    fn depth_case(lines_first: bool) -> Case {
        let sphere = Draw {
            label: "blue sphere radius 2 at the origin (depth 3..7)",
            rgb: BLUE,
            rank: 1,
            translation: [0.; 3],
            primitive: Primitive::Sphere {
                center: [0.; 3],
                radius: 2.,
            },
        };
        // Rows 60 and 70 are pixel centres at depths 2 and 8.
        let front = line(
            "yellow world line in front of the sphere at depth 2",
            YELLOW,
            0,
            [-1.5, 0.109_375, 3.],
            [1.5, 0.109_375, 3.],
        );
        let back = line(
            "green world line behind the sphere at depth 8",
            GREEN,
            2,
            [-6., -0.8125, -3.],
            [6., -0.8125, -3.],
        );
        if lines_first {
            Case {
                filename: "world-lines-then-sphere-depth.png",
                case: "world-lines-drawn-first-keep-depth-order",
                claim: "a later sphere cannot cover a nearer earlier line (lines write depth) but covers a farther earlier line",
                draws: vec![front, back, sphere],
                forbidden: Vec::new(),
            }
        } else {
            Case {
                filename: "world-sphere-then-lines-depth.png",
                case: "world-sphere-drawn-first-occludes-farther-line",
                claim: "a later farther line is hidden inside the sphere silhouette while a later nearer line crosses it",
                draws: vec![sphere, front, back],
                forbidden: Vec::new(),
            }
        }
    }

    fn wire_box_case() -> Case {
        let translation = [0.375, -0.25, 0.];
        let draw = Draw {
            label: "magenta wire box size 4 at the origin under a model translation",
            rgb: MAGENTA,
            rank: 0,
            translation,
            primitive: Primitive::WireBox {
                center: [0.; 3],
                size: [4.; 3],
            },
        };
        let t = widen(translation);
        let at = |x: f64, y: f64, z: f64| project(add3([x, y, z], t));
        let front_left = at(-2., 0., 2.)[0];
        let back_min = at(-2., 2., -2.);
        let back_max = at(2., -2., -2.);
        Case {
            filename: "world-wire-box-perspective.png",
            case: "wire-box-model-translation-and-perspective",
            claim: "facade wire boxes apply the model matrix, draw only twelve edges, and shrink the far face by 3/7",
            draws: vec![draw],
            forbidden: vec![
                Forbidden {
                    label: "front-left edge position if the model translation were ignored",
                    area: Area::Band {
                        a: project([-2., -2., 2.]),
                        b: project([-2., 2., 2.]),
                    },
                },
                Forbidden {
                    label: "inside the far face (wireframe must not fill)",
                    area: Area::Rect {
                        x0: back_min[0] + FORBIDDEN_GAP,
                        x1: back_max[0] - FORBIDDEN_GAP,
                        y0: back_min[1] + FORBIDDEN_GAP,
                        y1: back_max[1] - FORBIDDEN_GAP,
                    },
                },
                Forbidden {
                    label: "left side face between near and far edges (no side fill)",
                    area: Area::Rect {
                        x0: front_left + FORBIDDEN_GAP,
                        x1: back_min[0] - FORBIDDEN_GAP,
                        y0: back_min[1] + FORBIDDEN_GAP,
                        y1: back_max[1] - FORBIDDEN_GAP,
                    },
                },
            ],
        }
    }

    fn cases() -> Vec<Case> {
        vec![
            perspective_case(),
            clip_case(),
            depth_case(false),
            depth_case(true),
            wire_box_case(),
        ]
    }

    fn camera() -> facade::Camera3D {
        facade::Camera3D {
            position: Vec3::new(0., 0., EYE_Z as f32),
            target: Vec3::ZERO,
            up: Vec3::Y,
            fovy: std::f32::consts::FRAC_PI_2,
            aspect: Some(1.),
            z_near: Z_NEAR as f32,
            z_far: Z_FAR as f32,
            render_target: None,
        }
    }

    fn camera_json() -> Value {
        json!({"position": [0., 0., EYE_Z], "target": [0., 0., 0.], "up": [0., 1., 0.],
            "fovy_degrees": 90., "aspect": 1., "z_near": Z_NEAR, "z_far": Z_FAR,
            "origin": "fixture-specified via facade::set_camera; not a game or authored camera"})
    }

    fn color(rgb: [u8; 3]) -> Color {
        let [r, g, b] = rgb.map(|v| f32::from(v) / 255.);
        Color::new(r, g, b, 1.)
    }

    fn draw_json(draw: &Draw) -> Value {
        let primitive = match draw.primitive {
            Primitive::Line { start, end } => {
                json!({"facade": "draw_line_3d", "start": start, "end": end})
            }
            Primitive::WireBox { center, size } => {
                json!({"facade": "draw_cube_wires", "center": center, "size": size})
            }
            Primitive::Sphere { center, radius } => {
                json!({"facade": "draw_sphere", "center": center, "radius": radius})
            }
        };
        json!({"label": draw.label, "rgb": draw.rgb, "depth_rank": draw.rank,
            "model_translation": draw.translation, "primitive": primitive})
    }

    /// Records one frame through the public facade only.
    fn record_case(case: &Case, capture: &Path) -> Result<DrawList, String> {
        facade::begin_frame(WIDTH, HEIGHT, 1.)?;
        facade::set_camera(&camera());
        facade::clear_background(facade::BLACK);
        for draw in &case.draws {
            let rgb = color(draw.rgb);
            let model = Mat4::from_translation(Vec3::from(draw.translation));
            facade::with_model_matrix(model, || match draw.primitive {
                Primitive::Line { start, end } => {
                    facade::draw_line_3d(start.into(), end.into(), rgb)
                }
                Primitive::WireBox { center, size } => {
                    facade::draw_cube_wires(center.into(), size.into(), rgb)
                }
                Primitive::Sphere { center, radius } => {
                    facade::draw_sphere(center.into(), radius, None, rgb)
                }
            });
        }
        facade::capture_png(None, capture);
        facade::take_draw_list()
    }

    /// Inscribed-ball radius / radius for each submitted sphere mesh. Proves the
    /// mesh is convex around its centre and inside its nominal ball, so its
    /// silhouette lies between the inscribed and nominal ball silhouettes.
    fn sphere_inradius_ratios(list: &DrawList, case: &Case) -> Result<Vec<f64>, String> {
        let spheres: Vec<_> = case
            .draws
            .iter()
            .filter_map(|draw| match draw.primitive {
                Primitive::Sphere { center, radius } => Some((draw, center, radius)),
                _ => None,
            })
            .collect();
        let meshes: Vec<_> = list
            .commands
            .iter()
            .filter_map(|command| match command {
                Command::Mesh { mesh, model, .. } => Some((mesh, *model)),
                _ => None,
            })
            .collect();
        if meshes.len() != spheres.len() {
            return Err(format!(
                "{}: expected {} sphere mesh commands, recorded {}",
                case.filename,
                spheres.len(),
                meshes.len()
            ));
        }
        let mut ratios = Vec::new();
        for ((draw, center, radius), (mesh, model)) in spheres.into_iter().zip(meshes) {
            if model != Mat4::from_translation(Vec3::from(draw.translation)) {
                return Err(format!("{}: sphere model matrix not recorded", draw.label));
            }
            let center = widen(center);
            let radius = f64::from(radius);
            let points: Vec<P3> = mesh
                .vertices
                .iter()
                .map(|vertex| widen(vertex.position.to_array()))
                .collect();
            let outer = points
                .iter()
                .map(|&p| dot3(sub3(p, center), sub3(p, center)).sqrt())
                .fold(0., f64::max);
            let mut inner = f64::INFINITY;
            for triangle in mesh.indices.as_chunks::<3>().0 {
                let [a, b, c] = [0, 1, 2].map(|i| points[usize::from(triangle[i])]);
                let normal = cross3(sub3(b, a), sub3(c, a));
                let length = dot3(normal, normal).sqrt();
                if length <= 1e-9 * radius * radius {
                    continue;
                }
                let side = dot3(normal, sub3(center, a));
                let slack = 1e-5 * length * radius;
                if side.abs() <= slack
                    || points
                        .iter()
                        .any(|&p| dot3(normal, sub3(p, a)) * side.signum() < -slack)
                {
                    return Err(format!(
                        "{}: sphere mesh is not convex around its centre",
                        draw.label
                    ));
                }
                inner = inner.min(side.abs() / length);
            }
            if outer > radius * (1. + 1e-5) || !inner.is_finite() || inner <= 0. {
                return Err(format!(
                    "{}: sphere mesh bounds invalid (outer {outer}, inner {inner})",
                    draw.label
                ));
            }
            ratios.push(inner / radius);
        }
        Ok(ratios)
    }

    // ---- Expected regions -----------------------------------------------------

    #[derive(Clone, Copy, Debug)]
    enum Shape {
        Segment {
            a: P2,
            b: P2,
        },
        /// `definite`/`possible`: inscribed and nominal silhouette radii in pixels.
        Disk {
            center: P2,
            definite: f64,
            possible: f64,
        },
    }
    impl Shape {
        fn possible(&self, p: P2) -> bool {
            match *self {
                Self::Segment { a, b } => segment_distance(p, a, b) <= LINE_BAND,
                Self::Disk {
                    center, possible, ..
                } => distance(p, center) <= possible + DISK_MARGIN,
            }
        }
        fn definite(&self, p: P2) -> bool {
            match *self {
                Self::Segment { .. } => false,
                Self::Disk {
                    center, definite, ..
                } => distance(p, center) <= definite - DISK_MARGIN,
            }
        }
        fn json(&self) -> Value {
            match *self {
                Self::Segment { a, b } => json!({"segment_px": [a, b]}),
                Self::Disk {
                    center,
                    definite,
                    possible,
                } => json!({"disk_px": {"center": center,
                    "inscribed_silhouette_radius": definite, "nominal_silhouette_radius": possible}}),
            }
        }
    }

    #[derive(Clone, Debug)]
    struct Layer {
        label: String,
        rgb: [u8; 3],
        rank: u32,
        shape: Shape,
    }

    fn layers(case: &Case, inradius_ratios: &[f64]) -> Result<Vec<Layer>, String> {
        let mut ratios = inradius_ratios.iter();
        let mut result = Vec::new();
        let mut disks = Vec::new();
        let segment = |result: &mut Vec<Layer>, label: String, draw: &Draw, a: P3, b: P3| {
            if let Some((a, b)) = clip_to_depth_range(a, b) {
                result.push(Layer {
                    label,
                    rgb: draw.rgb,
                    rank: draw.rank,
                    shape: Shape::Segment {
                        a: project(a),
                        b: project(b),
                    },
                });
            }
        };
        for draw in &case.draws {
            let t = widen(draw.translation);
            match draw.primitive {
                Primitive::Line { .. } => {
                    let (a, b) = line_ends(draw);
                    segment(&mut result, draw.label.to_owned(), draw, a, b);
                }
                Primitive::WireBox { center, size } => {
                    for (index, (a, b)) in box_edges(widen(center), widen(size))
                        .into_iter()
                        .enumerate()
                    {
                        segment(
                            &mut result,
                            format!("{} edge {index}", draw.label),
                            draw,
                            add3(a, t),
                            add3(b, t),
                        );
                    }
                }
                Primitive::Sphere { center, radius } => {
                    let ratio = ratios
                        .next()
                        .ok_or("missing inscribed radius for a sphere")?;
                    let center = add3(widen(center), t);
                    let radius = f64::from(radius);
                    let depth = view_depth(center);
                    if center[0] != 0. || center[1] != 0. {
                        return Err(format!(
                            "{}: analytic silhouette requires an on-axis sphere",
                            draw.label
                        ));
                    }
                    if depth - radius < Z_NEAR || depth + radius > Z_FAR {
                        return Err(format!(
                            "{}: sphere must lie inside the depth range",
                            draw.label
                        ));
                    }
                    disks.push(Layer {
                        label: draw.label.to_owned(),
                        rgb: draw.rgb,
                        rank: draw.rank,
                        shape: Shape::Disk {
                            center: project(center),
                            definite: sphere_silhouette_px(depth, radius * ratio),
                            possible: sphere_silhouette_px(depth, radius),
                        },
                    });
                }
            }
        }
        result.extend(disks);
        Ok(result)
    }

    fn matches(pixel: [u8; 4], rgb: [u8; 3]) -> bool {
        pixel[..3]
            .iter()
            .zip(rgb)
            .all(|(&actual, expected)| actual.abs_diff(expected) <= TOLERANCE)
    }

    fn presence_samples(layer: &Layer, all: &[Layer]) -> Vec<P2> {
        let Shape::Segment { a, b } = layer.shape else {
            return Vec::new();
        };
        let length = distance(a, b);
        let mut samples = Vec::new();
        let mut t = END_MARGIN;
        while t <= length - END_MARGIN {
            let s = toward(a, b, t);
            let hidden = all.iter().any(|other| {
                let competing =
                    other.rank < layer.rank || (other.rank == layer.rank && other.rgb != layer.rgb);
                competing
                    && match other.shape {
                        Shape::Segment { a, b } => {
                            segment_distance(s, a, b) <= LINE_BAND + OCCLUDER_MARGIN
                        }
                        Shape::Disk {
                            center, possible, ..
                        } => distance(s, center) <= possible + DISK_MARGIN + OCCLUDER_MARGIN,
                    }
            });
            if !hidden {
                samples.push(s);
            }
            t += 1.;
        }
        samples
    }

    fn present_near(image: &RgbaImage, s: P2, rgb: [u8; 3]) -> bool {
        let (x, y) = (s[0].floor() as i64, s[1].floor() as i64);
        (-1..=1).any(|dy| {
            (-1..=1).any(|dx| {
                let (px, py) = (x + dx, y + dy);
                px >= 0
                    && py >= 0
                    && px < i64::from(image.width())
                    && py < i64::from(image.height())
                    && matches(image.get_pixel(px as u32, py as u32).0, rgb)
            })
        })
    }

    struct Evaluation {
        summary: Value,
        failures: Vec<String>,
    }

    fn pixel_center(x: u32, y: u32) -> P2 {
        [f64::from(x) + 0.5, f64::from(y) + 0.5]
    }

    /// Specification errors return Err; pixel mismatches are listed in `failures`.
    fn evaluate(
        image: &RgbaImage,
        layers: &[Layer],
        forbidden: &[Forbidden],
    ) -> Result<Evaluation, String> {
        if (image.width(), image.height()) != (WIDTH, HEIGHT) {
            return Err("capture extent differs from the fixture camera extent".into());
        }
        let mut failures = Vec::new();
        let mut forbidden_json = Vec::new();
        for region in forbidden {
            let mut pixels = 0_u64;
            let mut lit = 0_u64;
            for (x, y, pixel) in image.enumerate_pixels() {
                let p = pixel_center(x, y);
                if !region.area.contains(p) {
                    continue;
                }
                if let Some(layer) = layers.iter().find(|layer| layer.shape.possible(p)) {
                    return Err(format!(
                        "fixture specification: forbidden region {:?} overlaps {:?}",
                        region.label, layer.label
                    ));
                }
                pixels += 1;
                if !matches(pixel.0, BACKGROUND) {
                    lit += 1;
                }
            }
            if pixels == 0 {
                return Err(format!(
                    "fixture specification: forbidden region {:?} covers no pixel",
                    region.label
                ));
            }
            if lit > 0 {
                failures.push(format!(
                    "{}: {lit}/{pixels} pixels are not background",
                    region.label
                ));
            }
            forbidden_json.push(json!({"label": region.label, "area": region.area.json(),
                "pixels": pixels, "non_background_pixels": lit}));
        }
        let mut violations = 0_u64;
        let mut examples = Vec::new();
        let mut primitive_required = 0_u64;
        let mut background_required = 0_u64;
        let mut matching = vec![0_u64; layers.len()];
        let mut definite_pixels = vec![0_u64; layers.len()];
        let mut opaque = true;
        for (x, y, pixel) in image.enumerate_pixels() {
            let p = pixel_center(x, y);
            opaque &= pixel.0[3] == 255;
            let mut definite = None;
            for (index, layer) in layers.iter().enumerate() {
                if layer.shape.definite(p) {
                    definite_pixels[index] += 1;
                    definite = Some(definite.map_or(layer.rank, |rank: u32| rank.min(layer.rank)));
                }
            }
            let mut allowed = Vec::new();
            let mut ok = definite.is_none() && matches(pixel.0, BACKGROUND);
            if definite.is_none() {
                allowed.push("background");
            }
            for (index, layer) in layers.iter().enumerate() {
                if layer.shape.possible(p) && definite.is_none_or(|rank| layer.rank <= rank) {
                    allowed.push(layer.label.as_str());
                    if matches(pixel.0, layer.rgb) {
                        ok = true;
                        matching[index] += 1;
                    }
                }
            }
            if definite.is_some() {
                primitive_required += 1;
            } else if allowed.len() == 1 {
                background_required += 1;
            }
            if !ok {
                violations += 1;
                if examples.len() < 8 {
                    examples.push(format!("({x},{y}) rgba {:?} allowed {allowed:?}", pixel.0));
                }
            }
        }
        if !opaque {
            failures.push("main capture must have opaque alpha in every pixel".into());
        }
        if violations > 0 {
            failures.push(format!(
                "{violations} pixels violate the analytic visibility map, e.g. {}",
                examples.join("; ")
            ));
        }
        if background_required == 0 {
            return Err("fixture specification: no background-only pixels".into());
        }
        let mut layers_json = Vec::new();
        for (index, layer) in layers.iter().enumerate() {
            let mut entry = json!({"label": layer.label, "rgb": layer.rgb, "depth_rank": layer.rank,
                "shape": layer.shape.json(), "matching_pixels": matching[index]});
            match layer.shape {
                Shape::Segment { .. } => {
                    let samples = presence_samples(layer, layers);
                    if samples.len() < MIN_PRESENCE_SAMPLES {
                        return Err(format!(
                            "fixture specification: {:?} has only {} unoccluded presence samples",
                            layer.label,
                            samples.len()
                        ));
                    }
                    let missing: Vec<_> = samples
                        .iter()
                        .filter(|&&s| !present_near(image, s, layer.rgb))
                        .collect();
                    if !missing.is_empty() {
                        failures.push(format!(
                            "{}: {}/{} presence samples have no matching pixel within 1 px, first at {:?}",
                            layer.label,
                            missing.len(),
                            samples.len(),
                            missing[0]
                        ));
                    }
                    entry["presence_samples"] = json!(samples.len());
                    entry["presence_missing"] = json!(missing.len());
                }
                Shape::Disk { .. } => {
                    if definite_pixels[index] == 0 {
                        return Err(format!(
                            "fixture specification: {:?} has no definite pixels",
                            layer.label
                        ));
                    }
                    entry["definite_pixels"] = json!(definite_pixels[index]);
                }
            }
            layers_json.push(entry);
        }
        Ok(Evaluation {
            summary: json!({
                "pixels": u64::from(WIDTH) * u64::from(HEIGHT),
                "visibility_map_violations": violations, "violation_examples": examples,
                "pixels_requiring_a_primitive": primitive_required,
                "pixels_requiring_background": background_required,
                "layers": layers_json, "forbidden_regions": forbidden_json,
                "thresholds": {"channel_tolerance": TOLERANCE, "line_band_px": LINE_BAND,
                    "disk_margin_px": DISK_MARGIN, "end_margin_px": END_MARGIN,
                    "forbidden_gap_px": FORBIDDEN_GAP, "presence_search_px": 1,
                    "occluder_margin_px": OCCLUDER_MARGIN, "allowed_violations": 0},
            }),
            failures,
        })
    }

    // ---- Native execution -----------------------------------------------------

    #[cfg(feature = "wgpu-runtime")]
    pub fn run(args: impl IntoIterator<Item = impl Into<String>>) -> Result<(), String> {
        let options = Options::parse(args)?;
        if !cfg!(target_os = "windows") {
            return Err("native DX12 world-primitive contract requires Windows; this platform can compile and run CPU helper tests, but cannot produce a native pass".into());
        }
        prepare_output(&options.output_dir)?;
        let mut renderer = pollster::block_on(WgpuRenderer::new_headless(
            WIDTH,
            HEIGHT,
            BackendSelection::Dx12,
            options.force_fallback_adapter,
        ))?;
        verify_backend(renderer.info())?;
        let mut captures = Vec::new();
        for case in cases() {
            let path = options.output_dir.join(case.filename);
            let list = record_case(&case, &path)?;
            let ratios = sphere_inradius_ratios(&list, &case)?;
            let expected = layers(&case, &ratios)?;
            let result = renderer.submit(&list)?;
            if result.captures != [path.clone()] {
                return Err(format!(
                    "{}: capture outputs differ: {:?}",
                    case.filename, result.captures
                ));
            }
            let image = read_png(&path, WIDTH, HEIGHT)?;
            let evaluation = evaluate(&image, &expected, &case.forbidden)?;
            let info = renderer.info();
            verify_backend(info)?;
            let metadata = json!({
                "schema_version": 1, "fixture_case": case.case, "filename": case.filename,
                "claim": case.claim,
                "requested": info.requested, "backend": info.backend, "adapter": info.adapter,
                "renderer": {"requested": info.requested, "backend": info.backend, "adapter": info.adapter},
                "force_fallback_adapter": options.force_fallback_adapter,
                "alpha_representation": OPAQUE, "diagnostic_raw_target": false,
                "row_origin": "top-left",
                "size": {"width": WIDTH, "height": HEIGHT}, "width": WIDTH, "height": HEIGHT,
                "camera": camera_json(),
                "draw_order": case.draws.iter().map(draw_json).collect::<Vec<_>>(),
                "sphere_inscribed_radius_ratios": ratios,
                "checks": evaluation.summary, "failures": evaluation.failures,
            });
            if !evaluation.failures.is_empty() {
                write_json(
                    &options
                        .output_dir
                        .join(format!("{}.failure.json", case.filename)),
                    &metadata,
                )?;
                return Err(format!(
                    "{}: {}",
                    case.filename,
                    evaluation.failures.join("; ")
                ));
            }
            write_json(
                &options.output_dir.join(format!("{}.json", case.filename)),
                &metadata,
            )?;
            captures.push(metadata);
        }
        let info = renderer.info();
        let report = json!({
            "schema_version": 1, "status": "passed", "native_execution": true,
            "requested": info.requested, "backend": info.backend, "adapter": info.adapter,
            "force_fallback_adapter": options.force_fallback_adapter,
            "platform": std::env::consts::OS, "build_version": vector_range::BUILD_VERSION,
            "build_number": vector_range::BUILD_NUMBER, "camera": camera_json(),
            "captures": captures, "scope": SCOPE,
        });
        let report_path = options.output_dir.join(REPORT);
        write_json(&report_path, &report)?;
        println!(
            "DX12 world-primitive contract passed on {}: {} captures; {}",
            info.adapter,
            captures.len(),
            report_path.display()
        );
        Ok(())
    }

    #[cfg(test)]
    mod tests {
        use super::*;
        use image::Rgba;
        use std::sync::atomic::{AtomicU64, Ordering};

        struct Scratch(PathBuf);
        impl Scratch {
            fn new() -> Self {
                static NEXT: AtomicU64 = AtomicU64::new(0);
                let path = std::env::temp_dir().join(format!(
                    "rust-duty-world-primitives-{}-{}",
                    std::process::id(),
                    NEXT.fetch_add(1, Ordering::Relaxed)
                ));
                fs::create_dir(&path).unwrap();
                Self(path)
            }
        }
        impl Drop for Scratch {
            fn drop(&mut self) {
                let _ = fs::remove_dir_all(&self.0);
            }
        }

        fn layers_for(case: &Case) -> Result<Vec<Layer>, String> {
            let list = record_case(case, Path::new(case.filename))?;
            layers(case, &sphere_inradius_ratios(&list, case)?)
        }

        fn expected(case: &Case) -> Vec<Layer> {
            layers_for(case).unwrap()
        }

        /// CPU control painter: ideal 1 px lines and nominal disks in the given order.
        /// Used only to show that the checks accept a correct image and reject defects.
        fn paint(shapes: &[(Shape, [u8; 3])]) -> RgbaImage {
            let mut image = RgbaImage::from_pixel(WIDTH, HEIGHT, Rgba([0, 0, 0, 255]));
            for &(shape, rgb) in shapes {
                let pixel = Rgba([rgb[0], rgb[1], rgb[2], 255]);
                match shape {
                    Shape::Disk {
                        center, possible, ..
                    } => {
                        for y in 0..HEIGHT {
                            for x in 0..WIDTH {
                                if distance(pixel_center(x, y), center) <= possible {
                                    image.put_pixel(x, y, pixel);
                                }
                            }
                        }
                    }
                    Shape::Segment { a, b } => {
                        // Half-pixel accurate DDA: one pixel per major-axis pixel
                        // centre, like aliased line rasterization.
                        let major = usize::from((b[1] - a[1]).abs() > (b[0] - a[0]).abs());
                        let minor = 1 - major;
                        let (lo, hi) = if a[major] <= b[major] { (a, b) } else { (b, a) };
                        let mut centre = (lo[major] - 0.5).ceil() + 0.5;
                        while centre <= hi[major] {
                            let t = if hi[major] == lo[major] {
                                0.
                            } else {
                                (centre - lo[major]) / (hi[major] - lo[major])
                            };
                            let mut q = [0.; 2];
                            q[major] = centre;
                            q[minor] = lo[minor] + (hi[minor] - lo[minor]) * t;
                            if q[0] >= 0.
                                && q[1] >= 0.
                                && q[0] < f64::from(WIDTH)
                                && q[1] < f64::from(HEIGHT)
                            {
                                image.put_pixel(q[0] as u32, q[1] as u32, pixel);
                            }
                            centre += 1.;
                        }
                    }
                }
            }
            image
        }

        /// Far-to-near control image of the expected layers.
        fn reference(layers: &[Layer]) -> RgbaImage {
            let mut ordered: Vec<_> = layers.iter().collect();
            ordered.sort_by_key(|layer| std::cmp::Reverse(layer.rank));
            paint(
                &ordered
                    .iter()
                    .map(|layer| (layer.shape, layer.rgb))
                    .collect::<Vec<_>>(),
            )
        }

        fn passes(image: &RgbaImage, case: &Case, layers: &[Layer]) -> bool {
            evaluate(image, layers, &case.forbidden)
                .unwrap()
                .failures
                .is_empty()
        }

        fn shifted(image: &RgbaImage, dx: i64, dy: i64) -> RgbaImage {
            RgbaImage::from_fn(WIDTH, HEIGHT, |x, y| {
                let (sx, sy) = (i64::from(x) - dx, i64::from(y) - dy);
                if sx < 0 || sy < 0 || sx >= i64::from(WIDTH) || sy >= i64::from(HEIGHT) {
                    Rgba([0, 0, 0, 255])
                } else {
                    *image.get_pixel(sx as u32, sy as u32)
                }
            })
        }

        fn with_extra(base: &RgbaImage, shape: Shape, rgb: [u8; 3]) -> RgbaImage {
            let mut image = base.clone();
            let extra = paint(&[(shape, rgb)]);
            for (x, y, pixel) in extra.enumerate_pixels() {
                if pixel.0[..3] != BACKGROUND {
                    image.put_pixel(x, y, *pixel);
                }
            }
            image
        }

        fn segment(a: P3, b: P3) -> Shape {
            Shape::Segment {
                a: project(a),
                b: project(b),
            }
        }

        #[test]
        fn cli_requires_explicit_dx12_and_output_directory() {
            let options = Options::parse([
                "--renderer=dx12",
                "--force-fallback-adapter",
                "--output-dir",
                "out",
            ])
            .unwrap();
            assert_eq!(
                options,
                Options {
                    force_fallback_adapter: true,
                    output_dir: PathBuf::from("out")
                }
            );
            assert!(
                !Options::parse(["--renderer", "dx12", "--output-dir=out"])
                    .unwrap()
                    .force_fallback_adapter
            );
            for args in [
                vec![],
                vec!["--renderer=dx12"],
                vec!["--output-dir=out"],
                vec!["--renderer"],
                vec!["--renderer=dx12", "--output-dir"],
                vec!["--renderer=dx12", "--output-dir="],
                vec!["--renderer=dx12", "--output-dir=out", "--unknown"],
                vec!["--renderer=dx12", "--renderer=dx12", "--output-dir=out"],
                vec!["--renderer=dx12", "--output-dir=out", "--output-dir=out"],
                vec![
                    "--renderer=dx12",
                    "--output-dir=out",
                    "--force-fallback-adapter",
                    "--force-fallback-adapter",
                ],
            ] {
                assert!(Options::parse(args.clone()).is_err(), "accepted {args:?}");
            }
            for backend in ["auto", "vulkan", "metal", "gl", "DX12", ""] {
                assert!(Options::parse([
                    format!("--renderer={backend}"),
                    "--output-dir=out".into()
                ])
                .is_err());
            }
        }

        #[test]
        fn analytic_projection_matches_the_facade_camera_without_rendering() {
            facade::begin_frame(WIDTH, HEIGHT, 1.).unwrap();
            facade::set_camera(&camera());
            let view_projection = facade::current_camera().unwrap().view_projection;
            facade::take_draw_list().unwrap();
            for point in [
                [0., 0., 0.],
                [-3.75, 3.085_937_5, 0.],
                [3.75, -2.125, -11.],
                [12., 3., -15.],
                [-0.5, -0.25, 4.],
                [2.375, 1.75, 2.],
                [-1.625, -2.25, -2.],
            ] {
                let ndc = view_projection.project_point3(Vec3::from(point.map(|v: f64| v as f32)));
                let actual = [
                    (f64::from(ndc.x) + 1.) * f64::from(WIDTH) / 2.,
                    (1. - f64::from(ndc.y)) * f64::from(HEIGHT) / 2.,
                ];
                let analytic = project(point);
                assert!(
                    distance(actual, analytic) < 1e-3,
                    "{point:?}: {actual:?} vs {analytic:?}"
                );
            }
            // OpenGL clip depth: the analytic near/far constants are the camera's.
            for (depth, ndc_z) in [(Z_NEAR, -1.), (Z_FAR, 1.)] {
                let p = Vec3::new(0.25, -0.25, (EYE_Z - depth) as f32);
                assert!((f64::from(view_projection.project_point3(p).z) - ndc_z).abs() < 1e-4);
            }
        }

        #[test]
        fn analytic_constants_are_pixel_centres_and_clip_points() {
            let red = project([0., 3.085_937_5, 0.]);
            let green = project([3.75, -2.125, -11.]);
            let blue = project([-4.335_937_5, 0., 0.]);
            assert_eq!((red[1], green, blue[0]), (24.5, [79., 72.5], 8.5));
            assert_eq!(project([0., 0.109_375, 3.])[1], 60.5);
            assert_eq!(project([0., -0.8125, -3.])[1], 70.5);
            let far = project(point_at_depth([12., 3., -10.], [12., 3., -25.], Z_FAR));
            assert!(distance(far, [102.4, 54.4]) < 1e-9);
            let near = project(point_at_depth(
                [-0.5, -0.25, 1.],
                [-0.5, -0.25, 4.5],
                Z_NEAR,
            ));
            assert!(distance(near, [32., 80.]) < 1e-9);
            assert!(clip_to_depth_range([-6., 6., -20.], [6., 6., -20.]).is_none());
            assert!(clip_to_depth_range([-1., -1., 7.], [1., -1., 7.]).is_none());
            assert!((sphere_silhouette_px(5., 2.) - 64. * 2. / 21_f64.sqrt()).abs() < 1e-12);
        }

        fn sorted_pair(a: P3, b: P3) -> [P3; 2] {
            let mut pair = [a, b];
            pair.sort_by(|a, b| a.partial_cmp(b).unwrap());
            pair
        }

        #[test]
        fn facade_records_world_primitives_with_model_and_independent_box_edges() {
            for case in cases() {
                let list = record_case(&case, Path::new(case.filename)).unwrap();
                assert_eq!((list.width, list.height), (WIDTH, HEIGHT));
                let Command::Camera(camera) = &list.commands[1] else {
                    panic!("perspective camera missing")
                };
                assert!(camera.depth_test && camera.target.is_none());
                assert!(matches!(list.commands[2], Command::Clear(_)));
                assert!(matches!(
                    list.commands.last(),
                    Some(Command::Capture { target: None, path }) if path == Path::new(case.filename)
                ));
                let primitives = &list.commands[3..list.commands.len() - 1];
                assert_eq!(primitives.len(), case.draws.len());
                for (command, draw) in primitives.iter().zip(&case.draws) {
                    let translation = Mat4::from_translation(Vec3::from(draw.translation));
                    match (command, draw.primitive) {
                        (Command::Lines { lines, model }, Primitive::Line { start, end }) => {
                            assert_eq!(*model, translation);
                            assert_eq!(lines.len(), 1);
                            assert_eq!((lines[0].start, lines[0].end), (start.into(), end.into()));
                            assert_eq!(lines[0].color, color(draw.rgb));
                        }
                        (Command::Lines { lines, model }, Primitive::WireBox { center, size }) => {
                            assert_eq!(*model, translation);
                            let mut recorded: Vec<_> = lines
                                .iter()
                                .map(|line| {
                                    sorted_pair(
                                        widen(line.start.to_array()),
                                        widen(line.end.to_array()),
                                    )
                                })
                                .collect();
                            let mut independent: Vec<_> = box_edges(widen(center), widen(size))
                                .into_iter()
                                .map(|(a, b)| sorted_pair(a, b))
                                .collect();
                            recorded.sort_by(|a, b| a.partial_cmp(b).unwrap());
                            independent.sort_by(|a, b| a.partial_cmp(b).unwrap());
                            assert_eq!(recorded, independent);
                        }
                        (Command::Mesh { model, .. }, Primitive::Sphere { .. }) => {
                            assert_eq!(*model, translation);
                        }
                        other => panic!("unexpected facade command for {}: {other:?}", draw.label),
                    }
                }
                for ratio in sphere_inradius_ratios(&list, &case).unwrap() {
                    assert!(ratio > 0.9 && ratio < 1., "inscribed ratio {ratio}");
                }
            }
        }

        fn first_mesh(list: &mut DrawList) -> &mut vector_range::draw::Mesh {
            list.commands
                .iter_mut()
                .find_map(|command| match command {
                    Command::Mesh { mesh, .. } => Some(mesh),
                    _ => None,
                })
                .expect("sphere mesh missing")
        }

        #[test]
        fn inradius_proof_rejects_meshes_outside_or_not_around_the_ball() {
            let case = depth_case(false);
            let mut list = record_case(&case, Path::new("x.png")).unwrap();
            let original = first_mesh(&mut list).clone();
            first_mesh(&mut list).vertices[40].position *= 1.1;
            assert!(sphere_inradius_ratios(&list, &case).is_err());
            let mesh = first_mesh(&mut list);
            *mesh = original;
            for vertex in &mut mesh.vertices {
                vertex.position.x += 3.;
            }
            assert!(sphere_inradius_ratios(&list, &case).is_err());
        }

        #[test]
        fn sidecar_descriptions_name_every_case_draw_and_the_camera() {
            let all = cases();
            let mut names: Vec<_> = all.iter().map(|case| (case.case, case.filename)).collect();
            names.sort_unstable();
            names.dedup();
            assert_eq!(names.len(), all.len());
            for case in &all {
                assert!(case.filename.ends_with(".png") && !case.claim.trim().is_empty());
                for draw in &case.draws {
                    let value = draw_json(draw);
                    assert_eq!(value["label"], draw.label);
                    assert_eq!(value["depth_rank"], draw.rank);
                    assert!(value["primitive"]["facade"]
                        .as_str()
                        .unwrap()
                        .starts_with("draw_"));
                }
            }
            let camera = camera_json();
            assert_eq!(
                (camera["z_near"].as_f64(), camera["z_far"].as_f64()),
                (Some(Z_NEAR), Some(Z_FAR))
            );
            assert_eq!(camera["fovy_degrees"].as_f64(), Some(90.));
        }

        #[test]
        fn correct_control_images_pass_every_case() {
            for case in cases() {
                let layers = expected(&case);
                let evaluation = evaluate(&reference(&layers), &layers, &case.forbidden).unwrap();
                assert!(
                    evaluation.failures.is_empty(),
                    "{}: {:?}",
                    case.filename,
                    evaluation.failures
                );
                assert_eq!(evaluation.summary["visibility_map_violations"], 0);
            }
        }

        #[test]
        fn one_pixel_offsets_pass_but_three_pixel_offsets_and_flips_fail() {
            for case in cases() {
                let layers = expected(&case);
                let image = reference(&layers);
                assert!(
                    passes(&shifted(&image, 0, 1), &case, &layers),
                    "{}",
                    case.filename
                );
                assert!(
                    !passes(&shifted(&image, 3, 0), &case, &layers),
                    "{}",
                    case.filename
                );
                assert!(
                    !passes(&shifted(&image, 0, 3), &case, &layers),
                    "{}",
                    case.filename
                );
                assert!(
                    !passes(&image::imageops::flip_vertical(&image), &case, &layers),
                    "{}",
                    case.filename
                );
            }
        }

        #[test]
        fn blank_swapped_and_translucent_captures_fail() {
            for case in cases() {
                let layers = expected(&case);
                let image = reference(&layers);
                let blank = RgbaImage::from_pixel(WIDTH, HEIGHT, Rgba([0, 0, 0, 255]));
                assert!(!passes(&blank, &case, &layers));
                let swapped = RgbaImage::from_fn(WIDTH, HEIGHT, |x, y| {
                    let p = image.get_pixel(x, y);
                    Rgba([p[2], p[0], p[1], p[3]])
                });
                assert!(!passes(&swapped, &case, &layers), "{}", case.filename);
                let mut translucent = image.clone();
                translucent.get_pixel_mut(0, 0).0[3] = 254;
                assert!(!passes(&translucent, &case, &layers));
            }
        }

        #[test]
        fn missing_perspective_division_fails() {
            let case = perspective_case();
            let layers = expected(&case);
            // The far green line drawn with the near red line's screen length.
            let mut wrong: Vec<_> = layers.iter().map(|l| (l.shape, l.rgb)).collect();
            wrong[1].0 = Shape::Segment {
                a: [project([-3.75, 0., 0.])[0], 72.5],
                b: [project([3.75, 0., 0.])[0], 72.5],
            };
            assert!(!passes(&paint(&wrong), &case, &layers));
        }

        #[test]
        fn missing_near_far_or_eye_clipping_fails() {
            let case = clip_case();
            let layers = expected(&case);
            let image = reference(&layers);
            assert!(passes(&image, &case, &layers));
            for (draw, rgb) in case.draws.iter().zip([YELLOW, CYAN, MAGENTA, WHITE]) {
                let (a, b) = line_ends(draw);
                assert!(
                    !passes(&with_extra(&image, segment(a, b), rgb), &case, &layers),
                    "{}",
                    draw.label
                );
            }
            // Clipping too early is also rejected: drop the far-crossing line.
            let early: Vec<_> = layers[1..].iter().map(|l| (l.shape, l.rgb)).collect();
            assert!(!passes(&paint(&early), &case, &layers));
        }

        #[test]
        fn painter_order_or_missing_line_depth_writes_fail() {
            for lines_first in [false, true] {
                let case = depth_case(lines_first);
                let layers = expected(&case);
                assert!(passes(&reference(&layers), &case, &layers));
                let by_rank = |rank| {
                    let layer = layers.iter().find(|l| l.rank == rank).unwrap();
                    (layer.shape, layer.rgb)
                };
                let (front, sphere, back) = (by_rank(0), by_rank(1), by_rank(2));
                // Farther green line painted after the sphere (depth test ignored).
                assert!(!passes(&paint(&[sphere, front, back]), &case, &layers));
                // Sphere painted over the nearer yellow line (line depth not written).
                assert!(!passes(&paint(&[back, front, sphere]), &case, &layers));
            }
        }

        #[test]
        fn ignored_model_matrix_filled_box_or_flat_box_fails() {
            let case = wire_box_case();
            let layers = expected(&case);
            let untranslated: Vec<_> = box_edges([0.; 3], [4.; 3])
                .into_iter()
                .map(|(a, b)| (segment(a, b), MAGENTA))
                .collect();
            assert!(!passes(&paint(&untranslated), &case, &layers));
            let filled = with_extra(
                &reference(&layers),
                Shape::Disk {
                    center: project([0.375, -0.25, -2.]),
                    definite: 0.,
                    possible: 12.,
                },
                MAGENTA,
            );
            assert!(!passes(&filled, &case, &layers));
            // Equal near and far faces (no perspective) are rejected.
            let flat: Vec<_> = box_edges([0.375, -0.25, 2.], [4., 4., 0.])
                .into_iter()
                .map(|(a, b)| (segment(a, b), MAGENTA))
                .collect();
            assert!(!passes(&paint(&flat), &case, &layers));
        }

        #[test]
        fn inconsistent_specifications_are_errors_not_passes() {
            let case = perspective_case();
            let layers = expected(&case);
            let image = reference(&layers);
            let overlapping = [Forbidden {
                label: "overlaps red",
                area: Area::Band {
                    a: [20., 24.5],
                    b: [30., 24.5],
                },
            }];
            assert!(evaluate(&image, &layers, &overlapping).is_err());
            let empty = [Forbidden {
                label: "outside",
                area: Area::Rect {
                    x0: 200.,
                    x1: 210.,
                    y0: 0.,
                    y1: 1.,
                },
            }];
            assert!(evaluate(&image, &layers, &empty).is_err());
            let short = [Layer {
                label: "too short".into(),
                rgb: RED,
                rank: 0,
                shape: Shape::Segment {
                    a: [10., 10.5],
                    b: [12., 10.5],
                },
            }];
            assert!(evaluate(&image, &short, &[]).is_err());
            assert!(evaluate(&RgbaImage::new(64, 64), &layers, &[]).is_err());
            let base = depth_case(false);
            let off_axis = Case {
                draws: vec![Draw {
                    translation: [0.5, 0., 0.],
                    ..base.draws[0]
                }],
                ..base
            };
            assert!(layers_for(&off_axis).is_err());
        }

        #[test]
        fn output_and_png_io_failures_are_errors_and_do_not_publish_a_report() {
            let scratch = Scratch::new();
            let output = scratch.0.join("out");
            prepare_output(&output).unwrap();
            prepare_output(&output).unwrap();
            let png = output.join("control.png");
            let case = wire_box_case();
            let layers = expected(&case);
            reference(&layers).save(&png).unwrap();
            let image = read_png(&png, WIDTH, HEIGHT).unwrap();
            assert!(passes(&image, &case, &layers));
            assert!(read_png(&png, 65, HEIGHT).is_err());
            assert!(read_png(&output.join("missing.png"), WIDTH, HEIGHT).is_err());
            assert!(prepare_output(&output).is_err());
            assert!(prepare_output(&png).is_err());
            let invalid = output.join("invalid.png");
            fs::write(&invalid, b"not an image").unwrap();
            assert!(read_png(&invalid, 1, 1).is_err());
            assert!(write_json(&png.join("bad.json"), &json!({"status":"passed"})).is_err());
            assert!(!output.join(REPORT).exists());
        }

        #[cfg(feature = "wgpu-runtime")]
        #[test]
        fn backend_identity_cannot_be_faked_by_request_alone() {
            let valid = BackendInfo {
                requested: "dx12".into(),
                backend: "Dx12".into(),
                adapter: "Microsoft Basic Render Driver".into(),
            };
            verify_backend(&valid).unwrap();
            for invalid in [
                BackendInfo {
                    backend: "Vulkan".into(),
                    ..valid.clone()
                },
                BackendInfo {
                    backend: "Gl".into(),
                    ..valid.clone()
                },
                BackendInfo {
                    adapter: " ".into(),
                    ..valid.clone()
                },
                BackendInfo {
                    requested: "auto".into(),
                    ..valid
                },
            ] {
                assert!(verify_backend(&invalid).is_err());
            }
        }

        #[cfg(all(feature = "wgpu-runtime", not(target_os = "windows")))]
        #[test]
        fn non_windows_native_run_is_an_error_without_artifacts() {
            let scratch = Scratch::new();
            let output = scratch.0.join("not-created");
            let error = run([
                "--renderer=dx12".to_owned(),
                "--force-fallback-adapter".into(),
                format!("--output-dir={}", output.display()),
            ])
            .unwrap_err();
            assert!(error.contains("requires Windows"));
            assert!(!output.exists());
        }
    }
}
