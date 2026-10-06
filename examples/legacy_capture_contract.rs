//! Default-framebuffer readback must not affect subsequent untextured draws.
//! cargo run --locked --no-default-features --features legacy-macroquad \
//!   --example legacy_capture_contract -- --output-dir <fresh-directory>
//! Native OpenGL window required. No model assets or simulation are used.

#[cfg(feature = "legacy-macroquad")]
fn main() {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.len() != 2 || args[0] != "--output-dir" || args[1].trim().is_empty() {
        eprintln!("usage: legacy_capture_contract --output-dir <fresh-directory>");
        std::process::exit(2);
    }
    let output = std::path::PathBuf::from(&args[1]);
    macroquad::Window::from_config(
        macroquad::prelude::Conf {
            window_title: "Legacy capture neutrality contract".into(),
            window_width: fixture::SIZE as i32,
            window_height: fixture::SIZE as i32,
            high_dpi: false,
            ..Default::default()
        },
        async move {
            if let Err(error) = fixture::run(&output) {
                eprintln!("legacy_capture_contract: {error}");
                std::process::exit(1);
            }
        },
    );
}

#[cfg(not(feature = "legacy-macroquad"))]
fn main() {
    eprintln!("legacy_capture_contract requires --features legacy-macroquad");
    std::process::exit(2);
}

#[cfg(any(feature = "legacy-macroquad", test))]
mod fixture {
    use glam::{Mat4, Vec2, Vec3};
    use image::RgbaImage;
    use std::path::Path;
    use vector_range::draw::{BlendMode, Camera, Color, DrawList, Mesh, RenderTarget, Vertex};
    #[cfg(feature = "legacy-macroquad")]
    use vector_range::{draw::Renderer, legacy_macroquad::LegacyRenderer};

    // Decorated Windows windows can impose a client width above 64 pixels.
    // Use a normal-sized fixed canvas so the screen and target match exactly.
    pub const SIZE: u32 = 256;
    const GRAY: [u8; 4] = [128, 128, 128, 255];
    const CASES: [(&str, [u8; 4]); 2] =
        [("warm", [204, 51, 26, 255]), ("cool", [26, 102, 204, 255])];

    fn quad(rgba: [u8; 4]) -> Mesh {
        let edge = SIZE as f32;
        let vertices = [(0., 0.), (edge, 0.), (edge, edge), (0., edge)]
            .into_iter()
            .map(|(x, y)| {
                let mut v = Vertex::new2(
                    Vec3::new(x, y, 0.),
                    Vec2::new(x / SIZE as f32, y / SIZE as f32),
                    Color::WHITE,
                );
                v.color = rgba;
                v
            })
            .collect();
        Mesh {
            vertices,
            indices: vec![0, 1, 2, 0, 2, 3],
            texture: None,
        }
    }

    fn record(output: &Path) -> Result<DrawList, String> {
        let target = RenderTarget::new(SIZE, SIZE, true)?;
        let mut target_camera = Camera::screen(SIZE, SIZE);
        target_camera.target = Some(target.clone());
        target_camera.depth_test = true;
        let mut list = DrawList::new(SIZE, SIZE);
        // Allocate the target before the first screen capture. Allocating it
        // afterward could incidentally repair the stale texture binding.
        list.camera(target_camera.clone());
        list.clear(Color::TRANSPARENT);
        list.draw_mesh(&quad(GRAY), Mat4::IDENTITY, BlendMode::Alpha);
        list.capture_png(Some(&target), output.join("baseline.png"));
        for (label, world_color) in CASES {
            list.camera(Camera::screen(SIZE, SIZE));
            list.clear(Color::TRANSPARENT);
            list.draw_mesh(&quad(world_color), Mat4::IDENTITY, BlendMode::Alpha);
            // No text, new texture, or next-frame boundary may intervene.
            list.capture_png(None, output.join(format!("{label}-world.png")));
            list.camera(target_camera.clone());
            list.clear(Color::TRANSPARENT);
            list.draw_mesh(&quad(GRAY), Mat4::IDENTITY, BlendMode::Alpha);
            list.capture_png(Some(&target), output.join(format!("{label}-after.png")));
        }
        Ok(list)
    }

    fn inspect(image: &RgbaImage, expected: [u8; 4]) -> Result<(), String> {
        if image.dimensions() != (SIZE, SIZE) {
            return Err(format!(
                "expected {SIZE}x{SIZE}, got {:?}",
                image.dimensions()
            ));
        }
        for y in 4..SIZE - 4 {
            for x in 4..SIZE - 4 {
                let actual = image.get_pixel(x, y).0;
                if actual != expected {
                    return Err(format!(
                        "pixel ({x},{y}) is {actual:?}, expected {expected:?}"
                    ));
                }
            }
        }
        Ok(())
    }

    #[cfg(feature = "legacy-macroquad")]
    pub fn run(output: &Path) -> Result<(), String> {
        if output.exists()
            && std::fs::read_dir(output)
                .map_err(|e| e.to_string())?
                .next()
                .is_some()
        {
            return Err("output directory must be empty".into());
        }
        std::fs::create_dir_all(output).map_err(|e| e.to_string())?;
        let list = record(output)?;
        let mut renderer = LegacyRenderer::new("gl")?;
        let result = renderer.submit(&list)?;
        if result.captures.len() != 5 {
            return Err(format!(
                "expected five captures, got {}",
                result.captures.len()
            ));
        }
        for (filename, expected) in [
            ("baseline.png", GRAY),
            ("warm-world.png", CASES[0].1),
            ("warm-after.png", GRAY),
            ("cool-world.png", CASES[1].1),
            ("cool-after.png", GRAY),
        ] {
            let image = image::open(output.join(filename))
                .map_err(|e| e.to_string())?
                .into_rgba8();
            inspect(&image, expected).map_err(|e| format!("{filename}: {e}"))?;
        }
        let info = renderer.info();
        let report = serde_json::json!({
            "schema": "rust-duty-legacy-capture-neutrality/v1",
            "status": "passed", "backend": info.backend, "adapter": info.adapter,
            "extent": [SIZE, SIZE], "captures": result.captures,
            "interior_pixels_per_capture": (SIZE - 8) * (SIZE - 8),
            "channel_tolerance": 0,
            "scope": "same-submission default readback followed by untextured alpha mesh into preallocated depth target"
        });
        std::fs::write(
            output.join("report.json"),
            serde_json::to_vec_pretty(&report).map_err(|e| e.to_string())?,
        )
        .map_err(|e| e.to_string())?;
        println!("Legacy capture neutrality passed on {}", info.adapter);
        Ok(())
    }

    #[cfg(test)]
    mod tests {
        use super::*;
        use image::Rgba;
        use vector_range::draw::Command;

        #[test]
        fn fixed_expected_pixels_accept_valid_control() {
            inspect(&RgbaImage::from_pixel(SIZE, SIZE, Rgba(GRAY)), GRAY).unwrap();
        }
        #[test]
        fn checker_rejects_screenshot_modulation_and_wrong_extent() {
            for color in [[102, 25, 13, 255], [13, 51, 102, 255]] {
                assert!(inspect(&RgbaImage::from_pixel(SIZE, SIZE, Rgba(color)), GRAY).is_err());
            }
            assert!(inspect(&RgbaImage::from_pixel(1, 1, Rgba(GRAY)), GRAY).is_err());
        }
        #[test]
        fn captures_surround_real_untextured_draws_without_intervening_text() {
            let list = record(Path::new("unused")).unwrap();
            let checkpoints: Vec<_> = list
                .commands
                .iter()
                .enumerate()
                .filter_map(|(i, c)| {
                    matches!(c, Command::Capture { target: None, .. }).then_some(i)
                })
                .collect();
            assert_eq!(checkpoints.len(), 2);
            for i in checkpoints {
                assert!(
                    matches!(&list.commands[i - 1], Command::Mesh { mesh, .. } if mesh.texture.is_none())
                );
                assert!(matches!(&list.commands[i + 1], Command::Camera(c) if c.target.is_some()));
                assert!(matches!(&list.commands[i + 2], Command::Clear(_)));
                assert!(
                    matches!(&list.commands[i + 3], Command::Mesh { mesh, .. } if mesh.texture.is_none())
                );
                assert!(matches!(
                    &list.commands[i + 4],
                    Command::Capture {
                        target: Some(_),
                        ..
                    }
                ));
            }
        }
    }
}
