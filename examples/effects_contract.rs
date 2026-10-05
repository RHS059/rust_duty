//! WP3.3 native acceptance for the actual public muzzle-effect emitter.
//!
//! Run on Windows (a fresh output directory is mandatory):
//! cargo run --locked --no-default-features --features wgpu-runtime --example effects_contract -- --renderer=dx12 --force-fallback-adapter --output-dir=artifacts/effects-contract
//! Omit --force-fallback-adapter to request hardware instead of WARP.
//! CPU-only checks: cargo test --locked --no-default-features --example effects_contract
//!
//! Original synthetic shot, no game/private assets or simulation mutations.
//! Fixed screen regions are specified independently of emitted vertices. We
//! test emission at zero coverage, repeat-draw additive accumulation, smoke
//! coverage/tint, unlit brass, expiration, and ordinary opaque geometry after
//! effects. This is not artistic approval or cross-backend depth parity.

#[cfg(feature = "wgpu-runtime")]
fn main() {
    if let Err(error) = fixture::run(std::env::args().skip(1)) {
        eprintln!("effects_contract: {error}");
        std::process::exit(1);
    }
}
#[cfg(not(feature = "wgpu-runtime"))]
fn main() {
    eprintln!("effects_contract requires --features wgpu-runtime and Windows DX12");
    std::process::exit(1);
}

#[cfg(any(feature = "wgpu-runtime", test))]
mod fixture {
    use image::RgbaImage;
    use serde_json::{json, Value};
    use std::{
        fs,
        path::{Path, PathBuf},
    };
    #[cfg(feature = "wgpu-runtime")]
    use vector_range::{
        draw::Renderer,
        render::{BackendSelection, WgpuRenderer},
    };
    use vector_range::{
        draw::{facade::*, Camera, DrawList},
        muzzle_fx::{MuzzleFx, SHELL_LIFE},
        sim::Shot,
    };

    const WIDTH: u32 = 800;
    const HEIGHT: u32 = 600;
    const REPORT: &str = "effects-contract-report.json";
    // All bounds are [left, top, right, bottom), top-left PNG coordinates.
    const FLASH: [u32; 4] = [380, 250, 485, 350];
    const HALO: [u32; 4] = [445, 270, 480, 330];
    const SMOKE: [u32; 4] = [400, 255, 470, 315];
    const CASING: [u32; 4] = [150, 160, 290, 285];
    const MARKER: [u32; 4] = [610, 460, 730, 530];
    const CLEAR: [u32; 4] = [30, 30, 100, 100];
    const MARKER_RGBA: [u8; 4] = [32, 128, 224, 255];
    const BRASS_RGBA: [u8; 4] = [193, 140, 61, 255];
    const TOLERANCE: u8 = 3;

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
            let mut fallback = false;
            while let Some(arg) = args.next() {
                match arg.as_str() {
                    "--force-fallback-adapter" if !fallback => fallback = true,
                    "--renderer" => set_once(
                        &mut renderer,
                        args.next().ok_or("--renderer requires dx12")?,
                        "renderer",
                    )?,
                    "--output-dir" => set_once(
                        &mut output_dir,
                        args.next().ok_or("--output-dir requires a directory")?,
                        "output-dir",
                    )?,
                    _ if arg.starts_with("--renderer=") => {
                        set_once(&mut renderer, arg[11..].into(), "renderer")?
                    }
                    _ if arg.starts_with("--output-dir=") => {
                        set_once(&mut output_dir, arg[13..].into(), "output-dir")?
                    }
                    _ => return Err(format!("unknown or duplicate fixture argument {arg:?}")),
                }
            }
            if renderer.as_deref() != Some("dx12") {
                return Err(
                    "explicit --renderer=dx12 is required; no alternative backend is accepted"
                        .into(),
                );
            }
            let output_dir = output_dir
                .filter(|s| !s.trim().is_empty() && !s.starts_with("--"))
                .ok_or("--output-dir requires an explicit nonempty directory")?;
            Ok(Self {
                force_fallback_adapter: fallback,
                output_dir: output_dir.into(),
            })
        }
    }
    fn set_once(slot: &mut Option<String>, value: String, flag: &str) -> Result<(), String> {
        if slot.replace(value).is_some() {
            return Err(format!("--{flag} may be specified only once"));
        }
        Ok(())
    }
    fn prepare_output(path: &Path) -> Result<(), String> {
        if path.exists() {
            if fs::read_dir(path)
                .map_err(|e| e.to_string())?
                .next()
                .transpose()
                .map_err(|e| e.to_string())?
                .is_some()
            {
                return Err("output directory must be empty; stale evidence cannot pass".into());
            }
        } else {
            fs::create_dir_all(path).map_err(|e| e.to_string())?;
        }
        Ok(())
    }

    fn shot() -> Shot {
        Shot {
            time: 12.5,
            spread_degrees: 0.75,
            direction: Vec3::X,
            start: Vec3::ZERO,
            end: Vec3::X * 20.,
            hit_target: false,
            headshot: false,
            muzzle: Vec3::Y,
            barrel_forward: Vec3::X,
            barrel_right: Vec3::Z,
            barrel_up: Vec3::Y,
            carrier_velocity: Vec3::ZERO,
        }
    }
    fn effects(age: f32) -> MuzzleFx {
        let mut fx = MuzzleFx::default();
        fx.spawn_shot(&shot());
        fx.update(age, &[], &[]);
        fx
    }
    fn camera(target: RenderTarget) -> Camera3D {
        Camera3D {
            position: Vec3::Y + Vec3::Z,
            target: Vec3::Y,
            up: Vec3::Y,
            fovy: std::f32::consts::FRAC_PI_2,
            aspect: Some(WIDTH as f32 / HEIGHT as f32),
            z_near: 0.01,
            z_far: 10.,
            render_target: Some(target),
        }
    }
    // The fixed 90-degree camera projects all three depths into x=600..740,
    // y=450..540. Their interior probe excludes every triangle/rectangle edge.
    fn marker(z: f32, rgba: [u8; 4]) -> Mesh {
        let d = 1. - z;
        let color = Color::new(
            rgba[0] as f32 / 255.,
            rgba[1] as f32 / 255.,
            rgba[2] as f32 / 255.,
            rgba[3] as f32 / 255.,
        );
        Mesh {
            vertices: [
                (2. / 3., -0.5),
                (17. / 15., -0.5),
                (17. / 15., -0.8),
                (2. / 3., -0.8),
            ]
            .into_iter()
            .map(|(x, y)| Vertex::new(x * d, 1. + y * d, z, 0., 0., color))
            .collect(),
            indices: vec![0, 1, 2, 0, 2, 3],
            texture: None,
        }
    }
    fn check_restored(before: &Camera) -> Result<(), String> {
        let after = current_camera()?;
        if after.view_projection != before.view_projection
            || after.depth_test != before.depth_test
            || after.target.as_ref().map(|t| t.texture.id)
                != before.target.as_ref().map(|t| t.texture.id)
            || current_model_matrix()? != Mat4::IDENTITY
        {
            return Err(
                "effect emitter did not restore the caller's camera/target/model state".into(),
            );
        }
        Ok(())
    }

    #[derive(Clone, Copy, Debug)]
    enum Scene {
        Barrel,
        LiveWorld,
        AgedWorld,
        ExpiredWorld,
    }
    impl Scene {
        fn name(self) -> &'static str {
            match self {
                Self::Barrel => "barrel",
                Self::LiveWorld => "world-live",
                Self::AgedWorld => "world-aged",
                Self::ExpiredWorld => "world-expired",
            }
        }
        fn age(self) -> f32 {
            match self {
                Self::Barrel | Self::LiveWorld => 0.,
                Self::AgedWorld => 0.1,
                Self::ExpiredWorld => SHELL_LIFE,
            }
        }
    }
    struct Recorded {
        list: DrawList,
        files: Vec<String>,
    }
    fn record(scene: Scene, dir: &Path) -> Result<Recorded, String> {
        let target = RenderTarget::new(WIDTH, HEIGHT, true)?;
        let mut fx = effects(scene.age());
        begin_frame(WIDTH, HEIGHT, 1.)?;
        set_camera(&camera(target.clone()));
        clear_background(Color::TRANSPARENT);
        // A background makes a leaked additive blend visible even though the
        // following normal marker is fully opaque. It also initializes depth.
        draw_mesh(&marker(-0.25, [64, 16, 32, 255]));
        let before = current_camera()?;
        let mut files = Vec::new();
        match scene {
            Scene::Barrel => fx.draw_barrel(Vec3::Y, Vec3::X),
            _ => fx.draw_world(Vec3::Y + Vec3::Z, true),
        }
        check_restored(&before)?;
        let name = format!("{}.png", scene.name());
        capture_png(Some(&target), dir.join(&name));
        files.push(name);
        if matches!(scene, Scene::Barrel) {
            fx.draw_barrel(Vec3::Y, Vec3::X);
            check_restored(&before)?;
            files.push("barrel-twice.png".into());
            capture_png(Some(&target), dir.join(files.last().unwrap()));
        }
        // Ordinary public draw_mesh, alpha=1: no explicit camera/model/blend
        // reset after effects. Near must replace background and occlude far.
        draw_mesh(&marker(0.25, MARKER_RGBA));
        draw_mesh(&marker(0., [224, 32, 64, 255]));
        files.push(format!("{}-after-markers.png", scene.name()));
        capture_png(Some(&target), dir.join(files.last().unwrap()));
        let list = take_draw_list()?;
        Ok(Recorded { list, files })
    }

    fn region(
        image: &RgbaImage,
        bounds: [u32; 4],
    ) -> Result<impl Iterator<Item = [u8; 4]> + '_, String> {
        let [left, top, right, bottom] = bounds;
        if left >= right || top >= bottom || right > image.width() || bottom > image.height() {
            return Err(format!(
                "invalid probe bounds {bounds:?} for {:?}",
                image.dimensions()
            ));
        }
        Ok((top..bottom).flat_map(move |y| (left..right).map(move |x| image.get_pixel(x, y).0)))
    }
    fn matching(actual: [u8; 4], expected: [u8; 4]) -> bool {
        actual
            .into_iter()
            .zip(expected)
            .all(|(a, e)| a.abs_diff(e) <= TOLERANCE)
    }
    fn exact_probe(
        image: &RgbaImage,
        label: &str,
        bounds: [u32; 4],
        expected: [u8; 4],
    ) -> Result<Value, String> {
        let mut count = 0;
        for pixel in region(image, bounds)? {
            count += 1;
            if !matching(pixel, expected) {
                return Err(format!(
                    "{label}: expected {expected:?} within {TOLERANCE}, got {pixel:?}"
                ));
            }
        }
        Ok(
            json!({"label":label,"pixel_bounds":bounds,"expected_rgba":expected,"matching_pixels":count,"channel_tolerance":TOLERANCE}),
        )
    }
    fn emission_probe(
        image: &RgbaImage,
        bounds: [u32; 4],
        minimum: usize,
    ) -> Result<Value, String> {
        let pixels: Vec<_> = region(image, bounds)?.collect();
        let count = pixels.iter().filter(|p| p[0] >= 16 && p[3] == 0).count();
        if count < minimum {
            return Err(format!("real effect emission: {count} zero-coverage red-emitting pixels, require {minimum}"));
        }
        Ok(
            json!({"label":"real-effect-zero-coverage-emission","pixel_bounds":bounds,"minimum_red":16,"expected_alpha":0,"matching_pixels":count,"minimum_pixels":minimum}),
        )
    }
    fn repeated_emission(single: &RgbaImage, twice: &RgbaImage) -> Result<Value, String> {
        if single.dimensions() != twice.dimensions() {
            return Err("repeat capture dimensions differ".into());
        }
        let mut unsaturated = 0;
        let mut checked = 0;
        for (a, b) in region(single, FLASH)?.zip(region(twice, FLASH)?) {
            if a[3] != 0 || b[3] != 0 {
                return Err("barrel-only emission changed coverage alpha".into());
            }
            if a[0] >= 8 && a[0] <= 100 {
                unsaturated += 1;
            }
            for channel in 0..3 {
                let expected = (u16::from(a[channel]) * 2).min(255) as u8;
                if b[channel].abs_diff(expected) > TOLERANCE {
                    return Err(format!(
                        "repeated real flash did not add: first {a:?}, second {b:?}"
                    ));
                }
            }
            checked += 1;
        }
        // Without this guard, an invisible emitter or wholly saturated flash
        // could satisfy the equation vacuously. It also rejects a no-op repeat.
        if unsaturated < 32 {
            return Err(format!(
                "repeat invariant needs 32 nontrivial unsaturated pixels, got {unsaturated}"
            ));
        }
        Ok(
            json!({"label":"repeat-real-flash-adds-radiance","pixel_bounds":FLASH,"equation":"twice.rgb = min(255, 2 * once.rgb); both alpha = 0","channel_tolerance":TOLERANCE,"checked_pixels":checked,"unsaturated_pixels":unsaturated,"minimum_unsaturated_pixels":32}),
        )
    }
    fn smoke_probe(image: &RgbaImage) -> Result<Value, String> {
        let mut count = 0;
        for p in region(image, SMOKE)? {
            // At age .1 the flash/light is gone. Source smoke RGB is constant
            // [147,158,163]. Associated RGB tracks alpha through any overlap;
            // this tests coverage and tint without assuming triangle overlap.
            if (20..=230).contains(&p[3]) && p[2] > p[0] {
                let expected =
                    [147, 158, 163].map(|c| ((c as u16 * p[3] as u16 + 127) / 255) as u8);
                if p[..3]
                    .iter()
                    .zip(expected)
                    .all(|(&a, e)| a.abs_diff(e) <= TOLERANCE)
                {
                    count += 1;
                }
            }
        }
        if count < 100 {
            return Err(format!(
                "aged smoke: {count} translucent tint/coverage pixels, require 100"
            ));
        }
        Ok(
            json!({"label":"unlit-aged-smoke-associated-tint","pixel_bounds":SMOKE,"source_rgb":[147,158,163],"alpha_range":[20,230],"matching_pixels":count,"minimum_pixels":100,"channel_tolerance":TOLERANCE}),
        )
    }
    fn casing_probe(image: &RgbaImage) -> Result<Value, String> {
        let count = region(image, CASING)?
            .filter(|&p| matching(p, BRASS_RGBA))
            .count();
        if count < 8 {
            return Err(format!(
                "aged casing: {count} opaque brass pixels, require 8"
            ));
        }
        Ok(
            json!({"label":"unlit-aged-casing-visible","pixel_bounds":CASING,"expected_rgba":BRASS_RGBA,"matching_pixels":count,"minimum_pixels":8,"channel_tolerance":TOLERANCE}),
        )
    }
    fn expired_probe(image: &RgbaImage) -> Result<Value, String> {
        let mut checked = 0;
        for (x, y, p) in image.enumerate_pixels() {
            // Only the deliberately drawn background marker may remain. The
            // one-pixel boundary margin covers projection rounding, not effects.
            if (599..=740).contains(&x) && (449..=540).contains(&y) {
                continue;
            }
            if p.0 != [0, 0, 0, 0] {
                return Err(format!(
                    "expired effects leave pixels at ({x},{y}): {:?}",
                    p.0
                ));
            }
            checked += 1;
        }
        Ok(
            json!({"label":"expired-effects-leave-no-pixels","checked_pixels":checked,"expected_rgba":[0,0,0,0]}),
        )
    }
    fn read_png(path: &Path) -> Result<RgbaImage, String> {
        let reader = image::io::Reader::open(path)
            .map_err(|e| e.to_string())?
            .with_guessed_format()
            .map_err(|e| e.to_string())?;
        if reader.format() != Some(image::ImageFormat::Png) {
            return Err("capture is not PNG".into());
        }
        let image = reader.decode().map_err(|e| e.to_string())?;
        if image.width() != WIDTH
            || image.height() != HEIGHT
            || image.color() != image::ColorType::Rgba8
        {
            return Err(format!(
                "expected {WIDTH}x{HEIGHT} RGBA8 PNG, got {}x{} {:?}",
                image.width(),
                image.height(),
                image.color()
            ));
        }
        Ok(image.into_rgba8())
    }
    fn write_json(path: &Path, value: &Value) -> Result<(), String> {
        let mut bytes = serde_json::to_vec_pretty(value).map_err(|e| e.to_string())?;
        bytes.push(b'\n');
        fs::write(path, bytes).map_err(|e| e.to_string())
    }
    fn verify_backend(info: &BackendInfo) -> Result<(), String> {
        if info.requested != "dx12" || info.backend != "Dx12" || info.adapter.trim().is_empty() {
            return Err(format!("native evidence requires requested=dx12, backend=Dx12, named adapter; got {info:?}"));
        }
        Ok(())
    }

    #[cfg(feature = "wgpu-runtime")]
    pub fn run(args: impl IntoIterator<Item = impl Into<String>>) -> Result<(), String> {
        let options = Options::parse(args)?;
        if !cfg!(target_os = "windows") {
            return Err("native effects acceptance requires Windows DX12; CPU tests cannot produce a native pass".into());
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
        for scene in [
            Scene::Barrel,
            Scene::LiveWorld,
            Scene::AgedWorld,
            Scene::ExpiredWorld,
        ] {
            let recorded = record(scene, &options.output_dir)?;
            let expected: Vec<_> = recorded
                .files
                .iter()
                .map(|f| options.output_dir.join(f))
                .collect();
            let output = renderer.submit(&recorded.list)?;
            if output.captures != expected {
                return Err(format!(
                    "capture sequence differs: {:?} != {expected:?}",
                    output.captures
                ));
            }
            let original = read_png(&expected[0])?;
            for (index, file) in recorded.files.iter().enumerate() {
                let image = read_png(&options.output_dir.join(file))?;
                let mut probes = vec![exact_probe(&image, "untouched-clear", CLEAR, [0, 0, 0, 0])?];
                if file.ends_with("-after-markers.png") {
                    probes.push(exact_probe(
                        &image,
                        "normal-opaque-marker-replaces-background-and-occludes-later-far-marker",
                        MARKER,
                        MARKER_RGBA,
                    )?);
                } else {
                    match scene {
                        Scene::Barrel => {
                            probes.push(emission_probe(&image, FLASH, 100)?);
                            if index == 1 {
                                probes.push(repeated_emission(&original, &image)?);
                            }
                        }
                        Scene::LiveWorld => probes.push(emission_probe(&image, HALO, 200)?),
                        Scene::AgedWorld => {
                            probes.push(smoke_probe(&image)?);
                            probes.push(casing_probe(&image)?);
                        }
                        Scene::ExpiredWorld => probes.push(expired_probe(&image)?),
                    }
                }
                let info = renderer.info();
                verify_backend(info)?;
                let metadata = json!({"schema_version":1,"fixture_case":scene.name(),"filename":file,
                    "requested":info.requested,"backend":info.backend,"adapter":info.adapter,
                    "force_fallback_adapter":options.force_fallback_adapter,
                    "width":WIDTH,"height":HEIGHT,"row_origin":"top-left",
                    "alpha_representation":"raw-associated-emissive-rgba8","diagnostic_raw_target":true,
                    "age_seconds":scene.age(),"probes":probes,"caller_camera_model_restored":true});
                write_json(&options.output_dir.join(format!("{file}.json")), &metadata)?;
                captures.push(metadata);
            }
        }
        let info = renderer.info();
        let report = json!({"schema_version":1,"status":"passed","native_execution":true,
            "requested":info.requested,"backend":info.backend,"adapter":info.adapter,
            "platform":std::env::consts::OS,"force_fallback_adapter":options.force_fallback_adapter,
            "build_version":vector_range::BUILD_VERSION,"build_number":vector_range::BUILD_NUMBER,
            "shot":{"time":12.5,"spread_degrees":0.75,"caliber_mm":5.56,"initial_effect_seed_u32":3787887164_u32,"muzzle":[0,1,0],"barrel_forward":[1,0,0],"barrel_right":[0,0,1],"barrel_up":[0,1,0],"carrier_velocity":[0,0,0]},
            "camera":{"position":[0,1,1],"target":[0,1,0],"fovy_degrees":90,"z_near":0.01,"z_far":10},
            "captures":captures,
            "scope":"actual muzzle_fx public draw API through facade and headless DX12; effect visibility, additive emission, expiration and subsequent normal-geometry state; not window presentation, gameplay, artistic approval or cross-backend depth parity"});
        write_json(&options.output_dir.join(REPORT), &report)?;
        println!(
            "DX12 effects contract passed on {}: {} captures; {}",
            info.adapter,
            captures.len(),
            options.output_dir.join(REPORT).display()
        );
        Ok(())
    }

    #[cfg(test)]
    mod tests {
        use super::*;
        use image::Rgba;
        use std::sync::atomic::{AtomicU64, Ordering};
        use vector_range::draw::Command;
        struct Scratch(PathBuf);
        impl Scratch {
            fn new() -> Self {
                static NEXT: AtomicU64 = AtomicU64::new(0);
                let path = std::env::temp_dir().join(format!(
                    "rust-duty-effects-contract-{}-{}",
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
        fn blank() -> RgbaImage {
            RgbaImage::new(WIDTH, HEIGHT)
        }
        fn fill(image: &mut RgbaImage, bounds: [u32; 4], rgba: [u8; 4]) {
            for y in bounds[1]..bounds[3] {
                for x in bounds[0]..bounds[2] {
                    image.put_pixel(x, y, Rgba(rgba));
                }
            }
        }
        #[test]
        fn arguments_fail_closed() {
            assert!(Options::parse(["--renderer=dx12", "--output-dir=fresh"]).is_ok());
            assert!(
                Options::parse([
                    "--renderer",
                    "dx12",
                    "--output-dir",
                    "fresh",
                    "--force-fallback-adapter"
                ])
                .unwrap()
                .force_fallback_adapter
            );
            for args in [
                vec![],
                vec!["--output-dir=fresh"],
                vec!["--renderer=vulkan", "--output-dir=fresh"],
                vec!["--renderer=dx12"],
                vec!["--renderer=dx12", "--output-dir="],
                vec!["--renderer=dx12", "--output-dir=fresh", "--renderer=dx12"],
                vec![
                    "--renderer=dx12",
                    "--output-dir=fresh",
                    "--force-fallback-adapter",
                    "--force-fallback-adapter",
                ],
            ] {
                assert!(Options::parse(args).is_err());
            }
        }
        #[test]
        fn output_directory_rejects_stale_evidence() {
            let scratch = Scratch::new();
            prepare_output(&scratch.0).unwrap();
            write_json(&scratch.0.join(REPORT), &json!({"status":"passed"})).unwrap();
            assert!(prepare_output(&scratch.0).is_err());
            assert!(prepare_output(&scratch.0.join(REPORT)).is_err());
        }
        #[test]
        fn backend_claims_require_dx12_and_adapter() {
            let mut info = BackendInfo {
                requested: "dx12".into(),
                backend: "Dx12".into(),
                adapter: "test WARP".into(),
            };
            verify_backend(&info).unwrap();
            info.backend = "Vulkan".into();
            assert!(verify_backend(&info).is_err());
            info.backend = "Dx12".into();
            info.adapter.clear();
            assert!(verify_backend(&info).is_err());
        }
        #[test]
        fn fixed_public_effect_states_have_expected_lifetimes() {
            let live = effects(0.);
            assert!(live.flash_intensity() > 0.);
            assert_eq!(live.smoke_count(), 7);
            assert_eq!(live.shell_count(), 1);
            let aged = effects(0.1);
            assert_eq!(aged.flash_intensity(), 0.);
            assert!(aged.lights().is_empty());
            assert_eq!(aged.smoke_count(), 7);
            assert_eq!(aged.shell_count(), 1);
            let expired = effects(SHELL_LIFE);
            assert_eq!(expired.flash_intensity(), 0.);
            assert_eq!(expired.smoke_count(), 0);
            assert_eq!(expired.shell_count(), 0);
        }
        #[test]
        fn scene_uses_public_emitter_and_restores_camera_model_without_gpu() {
            for (scene, additive, alpha, captures) in [
                (Scene::Barrel, 2, 3, 3),
                (Scene::LiveWorld, 3, 11, 2),
                (Scene::AgedWorld, 0, 11, 2),
                (Scene::ExpiredWorld, 0, 3, 2),
            ] {
                let recorded = record(scene, Path::new("unused-cpu-only")).unwrap();
                let meshes: Vec<_> = recorded
                    .list
                    .commands
                    .iter()
                    .filter_map(|c| match c {
                        Command::Mesh { mesh, model, blend } => Some((mesh, model, blend)),
                        _ => None,
                    })
                    .collect();
                assert_eq!(
                    meshes
                        .iter()
                        .filter(|(_, _, b)| **b == BlendMode::Additive)
                        .count(),
                    additive,
                    "{scene:?}"
                );
                assert_eq!(
                    meshes
                        .iter()
                        .filter(|(_, _, b)| **b == BlendMode::Alpha)
                        .count(),
                    alpha,
                    "{scene:?}"
                );
                assert_eq!(recorded.files.len(), captures);
                assert!(meshes
                    .iter()
                    .all(|(m, _, _)| m.texture.is_none() && m.validate().is_ok()));
                for (_, model, blend) in &meshes[meshes.len() - 2..] {
                    assert_eq!(**model, Mat4::IDENTITY);
                    assert_eq!(**blend, BlendMode::Alpha);
                }
            }
        }
        #[test]
        fn aged_effect_geometry_projects_inside_fixed_independent_regions() {
            let recorded = record(Scene::AgedWorld, Path::new("unused-cpu-only")).unwrap();
            let camera = recorded
                .list
                .commands
                .iter()
                .filter_map(|c| match c {
                    Command::Camera(camera) if camera.depth_test => Some(camera),
                    _ => None,
                })
                .next()
                .unwrap();
            let meshes: Vec<_> = recorded
                .list
                .commands
                .iter()
                .filter_map(|c| match c {
                    Command::Mesh { mesh, model, .. } => Some((mesh, model)),
                    _ => None,
                })
                .collect();
            // Skip the background marker; production world draw emits seven
            // puffs followed by one shell. Bounds stay independent constants.
            for (i, (mesh, model)) in meshes[1..9].iter().enumerate() {
                let bounds = if i < 7 { SMOKE } else { CASING };
                for vertex in &mesh.vertices {
                    let ndc = (camera.view_projection * **model).project_point3(vertex.position);
                    let x = (ndc.x + 1.) * WIDTH as f32 * 0.5;
                    let y = (1. - ndc.y) * HEIGHT as f32 * 0.5;
                    assert!(
                        x >= bounds[0] as f32
                            && x <= bounds[2] as f32
                            && y >= bounds[1] as f32
                            && y <= bounds[3] as f32,
                        "effect {i}: ({x},{y}) outside {bounds:?}"
                    );
                }
            }
        }
        #[test]
        fn emission_rejects_black_and_alpha_blended_flash() {
            let mut image = blank();
            exact_probe(&image, "clear", CLEAR, [0, 0, 0, 0]).unwrap();
            assert!(emission_probe(&image, FLASH, 100).is_err());
            assert!(emission_probe(&image, HALO, 200).is_err());
            fill(&mut image, FLASH, [80, 40, 20, 100]);
            assert!(emission_probe(&image, FLASH, 100).is_err());
            fill(&mut image, FLASH, [80, 40, 20, 0]);
            emission_probe(&image, FLASH, 100).unwrap();
        }
        #[test]
        fn repeat_invariant_rejects_noop_black_saturation_and_alpha() {
            let mut once = blank();
            let mut twice = blank();
            assert!(repeated_emission(&once, &twice).is_err());
            fill(&mut once, FLASH, [80, 40, 20, 0]);
            assert!(repeated_emission(&once, &once).is_err());
            fill(&mut twice, FLASH, [160, 80, 40, 0]);
            repeated_emission(&once, &twice).unwrap();
            fill(&mut once, FLASH, [255, 255, 255, 0]);
            fill(&mut twice, FLASH, [255, 255, 255, 0]);
            assert!(repeated_emission(&once, &twice).is_err());
            fill(&mut once, FLASH, [80, 40, 20, 0]);
            fill(&mut twice, FLASH, [160, 80, 40, 1]);
            assert!(repeated_emission(&once, &twice).is_err());
        }
        #[test]
        fn smoke_and_casing_checks_reject_missing_or_wrong_effect() {
            let mut image = blank();
            assert!(smoke_probe(&image).is_err());
            assert!(casing_probe(&image).is_err());
            fill(&mut image, SMOKE, [29, 31, 32, 50]);
            smoke_probe(&image).unwrap();
            fill(&mut image, SMOKE, [147, 158, 163, 255]);
            assert!(smoke_probe(&image).is_err());
            fill(&mut image, CASING, BRASS_RGBA);
            casing_probe(&image).unwrap();
            fill(&mut image, CASING, [193, 140, 61, 0]);
            assert!(casing_probe(&image).is_err());
        }
        #[test]
        fn marker_check_detects_additive_blend_far_overdraw_and_transform_leaks() {
            let mut image = blank();
            assert!(exact_probe(&image, "marker", MARKER, MARKER_RGBA).is_err());
            for bad in [[96, 144, 255, 255], [224, 32, 64, 255]] {
                fill(&mut image, MARKER, bad);
                assert!(exact_probe(&image, "marker", MARKER, MARKER_RGBA).is_err());
            }
            fill(&mut image, MARKER, MARKER_RGBA);
            exact_probe(&image, "marker", MARKER, MARKER_RGBA).unwrap();
        }
        #[test]
        fn expiration_rejects_residual_effect_pixels() {
            let mut image = blank();
            expired_probe(&image).unwrap();
            image.put_pixel(400, 300, Rgba([1, 0, 0, 0]));
            assert!(expired_probe(&image).is_err());
        }
        #[test]
        fn png_contract_requires_rgba8_expected_size_and_valid_bounds() {
            let scratch = Scratch::new();
            let path = scratch.0.join("capture.png");
            blank().save(&path).unwrap();
            read_png(&path).unwrap();
            RgbaImage::new(1, 1).save(&path).unwrap();
            assert!(read_png(&path).is_err());
            image::RgbImage::new(WIDTH, HEIGHT).save(&path).unwrap();
            assert!(read_png(&path).is_err());
            assert!(region(&blank(), [0, 0, 0, 1]).is_err());
            assert!(region(&blank(), [0, 0, WIDTH + 1, 1]).is_err());
        }
    }
}
