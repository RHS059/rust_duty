//! Explicit native contract. The ignored test is invoked by the bounded native
//! workflow; ordinary CPU test runs never silently substitute a software GPU.
use super::{BackendSelection, WgpuRenderer};
use crate::{
    draw::{
        resident::{ResidentDraw, ResidentMesh, RigidVertex, SkinPalette, SkinVertex, Vertices},
        BlendMode, Camera, Color, DrawList, Rect, RenderTarget, Renderer,
    },
    scene_lighting::SceneLighting,
};
use glam::{Mat4, Vec3};
use std::path::PathBuf;
const SIZE: u32 = 64;
fn source(skin: bool, normal: [f32; 3]) -> ResidentMesh {
    let rigid: Vec<_> = [[4., 4., 0.], [20., 4., 0.], [4., 20., 0.]]
        .into_iter()
        .map(|position| RigidVertex {
            position,
            uv: [0.; 2],
            normal,
        })
        .collect();
    ResidentMesh::new(
        if skin {
            Vertices::Skin {
                vertices: rigid
                    .into_iter()
                    .map(|vertex| SkinVertex {
                        vertex,
                        joints: [0, 1, 2, 3, 4, 5, 6, 127],
                        weights: [0.125; 8],
                    })
                    .collect(),
                bones: 128,
            }
        } else {
            Vertices::Rigid(rigid)
        },
        vec![0, 1, 2],
        None,
    )
    .unwrap()
}
fn draw(mesh: ResidentMesh, step: usize) -> ResidentDraw {
    let palette = matches!(mesh.vertices(), Vertices::Skin { .. }).then(|| {
        SkinPalette::new(
            (0..128)
                .map(|i| {
                    Mat4::from_scale_rotation_translation(
                        if i == 127 {
                            Vec3::new(1.5, 0.75, 2.)
                        } else {
                            Vec3::new(1. + (i % 3) as f32 * 0.25, 1. + (i % 2) as f32 * 0.25, 1.)
                        },
                        glam::Quat::IDENTITY,
                        Vec3::new(
                            (step % 3) as f32 + if i == 127 { 3. } else { (i % 7) as f32 * 0.25 },
                            if i == 127 { 2. } else { 0. },
                            0.,
                        ),
                    )
                })
                .collect(),
        )
        .unwrap()
    });
    ResidentDraw::new(
        mesh,
        Mat4::from_scale_rotation_translation(
            Vec3::new(0.75, 1.25, 1.5),
            glam::Quat::IDENTITY,
            Vec3::new((step % 2) as f32 * 8., 0., 0.),
        ),
        SceneLighting {
            direction_to_light: Vec3::new(0.3, 0.8, 0.2).normalize(),
            ambient: 0.25,
            diffuse: 0.75,
        },
        Color::new(0.5, 0.75, 0.25, 1.),
        if step.is_multiple_of(2) { 1. } else { 0.5 },
        palette,
    )
    .unwrap()
}
#[test]
fn native_fixture_distinguishes_late_bones_and_normal_routes() {
    let skin = draw(source(true, [1., 2., 3.]), 0);
    let expected = skin.reference_mesh();
    let mut wrong = skin.palette().unwrap().positions().to_vec();
    wrong[127] = wrong[1];
    let changed = ResidentDraw::new(
        skin.mesh().clone(),
        skin.root(),
        skin.lighting(),
        skin.albedo(),
        skin.alpha(),
        Some(SkinPalette::new(wrong).unwrap()),
    )
    .unwrap()
    .reference_mesh();
    assert_ne!(expected.vertices[0].position, changed.vertices[0].position);
    let Vertices::Skin { vertices, bones } = skin.mesh().vertices() else {
        unreachable!()
    };
    let mut four = vertices.clone();
    for vertex in &mut four {
        vertex.weights = [0.25, 0.25, 0.25, 0.25, 0., 0., 0., 0.];
    }
    let four = ResidentMesh::new(
        Vertices::Skin {
            vertices: four,
            bones: *bones,
        },
        skin.mesh().indices().to_vec(),
        None,
    )
    .unwrap();
    let changed = ResidentDraw::new(
        four,
        skin.root(),
        skin.lighting(),
        skin.albedo(),
        skin.alpha(),
        skin.palette().cloned(),
    )
    .unwrap()
    .reference_mesh();
    assert_ne!(expected.vertices[0].position, changed.vertices[0].position);
    let source = Vec3::new(1., 2., 3.);
    let mut wrong_normal = Vec3::ZERO;
    for (&joint, &weight) in vertices[0].joints.iter().zip(&vertices[0].weights) {
        wrong_normal += skin.palette().unwrap().positions()[usize::from(joint)]
            .transform_vector3(source)
            * weight;
    }
    let wrong_normal = skin.root().transform_vector3(wrong_normal).normalize();
    let wrong_color: [u8; 4] = skin.lighting().shade(skin.albedo(), wrong_normal).into();
    assert_ne!(expected.vertices[0].color, wrong_color);
    let rigid = draw(self::source(false, [1., 2., 3.]), 0);
    let wrong_color: [u8; 4] = rigid.lighting().shade(rigid.albedo(), source).into();
    assert_ne!(rigid.reference_mesh().vertices[0].color, wrong_color);
}

fn camera(target: &RenderTarget) -> Camera {
    let mut camera = Camera::screen(SIZE, SIZE);
    camera.target = Some(target.clone());
    camera
}
fn emit(
    list: &mut DrawList,
    target: &RenderTarget,
    draw: &ResidentDraw,
    native: bool,
    clear: bool,
) {
    list.camera(camera(target));
    if clear {
        list.clear(Color::TRANSPARENT);
    }
    if native {
        list.draw_resident(draw.clone(), Mat4::IDENTITY, BlendMode::Alpha);
    } else {
        list.draw_mesh(&draw.reference_mesh(), Mat4::IDENTITY, BlendMode::Alpha);
    }
}
fn snapshot(list: &mut DrawList, from: &RenderTarget, to: &RenderTarget) {
    list.camera(camera(to));
    list.clear(Color::TRANSPARENT);
    list.draw_texture(
        &from.texture,
        Rect::new(0., 0., SIZE as f32, SIZE as f32),
        Color::WHITE,
    );
}
fn directory() -> PathBuf {
    let path = std::env::var_os("RUST_DUTY_RESIDENT_TEST_OUTPUT")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            std::env::temp_dir().join(format!("rust-duty-resident-{}", std::process::id()))
        });
    std::fs::create_dir(&path).expect("native evidence directory must be fresh");
    path
}
#[test]
#[ignore = "explicit native DX12/WARP or Linux Vulkan hardware contract"]
fn native_resident_poses_preserve_order_and_queued_results() {
    let backend = if cfg!(target_os = "windows") {
        BackendSelection::Dx12
    } else {
        BackendSelection::Vulkan
    };
    let mut renderer = pollster::block_on(WgpuRenderer::new_headless(
        SIZE,
        SIZE,
        backend,
        cfg!(target_os = "windows"),
    ))
    .expect("required native adapter unavailable");
    assert!(renderer.supports_resident_meshes());
    let actual = renderer.gpu.actual_adapter_info();
    if cfg!(target_os = "windows") {
        assert_eq!(actual.device_type, wgpu::DeviceType::Cpu);
    } else {
        assert!(
            matches!(
                actual.device_type,
                wgpu::DeviceType::DiscreteGpu | wgpu::DeviceType::IntegratedGpu
            ),
            "Linux native proof requires hardware GPU: {actual:?}"
        );
    }
    eprintln!("resident actual adapter: {actual:?}");
    if cfg!(target_os = "windows") {
        assert_eq!(renderer.info().backend, "Dx12");
    } else {
        assert_eq!(renderer.info().backend, "Vulkan");
    }
    let output = directory();
    let sources = [
        source(false, [1., 2., 3.]),
        source(true, [1., 2., 3.]),
        source(false, [1e30, 0., 0.]),
        source(false, [1e-30, 0., 0.]),
        source(false, [0.; 3]),
    ];
    let mut pairs = Vec::new();
    for step in 0..12 {
        if step == 9 {
            let invalid = DrawList::new(0, SIZE);
            assert!(renderer.submit(&invalid).is_err());
        }
        if step == 10 {
            renderer.resident.disable_retention_for_test();
        }
        let mesh = sources[step % sources.len()].clone();
        let first = draw(mesh.clone(), step);
        let second = draw(mesh, step + 1);
        let cpu = RenderTarget::new(SIZE, SIZE, false).unwrap();
        let native = RenderTarget::new(SIZE, SIZE, false).unwrap();
        let cpu_mid = RenderTarget::new(SIZE, SIZE, false).unwrap();
        let native_mid = RenderTarget::new(SIZE, SIZE, false).unwrap();
        let mut list = DrawList::new(SIZE, SIZE);
        emit(&mut list, &cpu, &first, false, true);
        emit(&mut list, &native, &first, true, true);
        snapshot(&mut list, &cpu, &cpu_mid);
        snapshot(&mut list, &native, &native_mid);
        emit(&mut list, &cpu, &second, false, false);
        emit(&mut list, &native, &second, true, false);
        let result = renderer.submit(&list).unwrap();
        assert_eq!(result.resident.draws, 2);
        assert_eq!(
            result.resident.cache_misses,
            u64::from(!(5..9).contains(&step))
        );
        assert_eq!(
            result.resident.cache_hits,
            if !(5..9).contains(&step) { 1 } else { 2 }
        );
        assert_eq!(result.resident.transient_meshes, u64::from(step >= 10));
        assert_eq!(
            result.resident.vertex_bytes_uploaded == 0,
            (5..9).contains(&step)
        );
        pairs.push((cpu_mid, native_mid));
        pairs.push((cpu, native));
    }
    // Asymmetric texture, perspective depth, occlusion and every supported
    // blend representation use the same immutable source and explicit cameras.
    let texture = crate::draw::Texture::rgba8(
        2,
        2,
        &[
            255, 32, 64, 255, 32, 255, 64, 255, 64, 32, 255, 255, 240, 200, 32, 255,
        ],
        crate::draw::Sampler::default(),
    )
    .unwrap();
    let geometry = ResidentMesh::new(
        Vertices::Rigid(vec![
            RigidVertex {
                position: [-0.75, -0.75, 0.],
                uv: [0., 0.],
                normal: [0., 0., 1.],
            },
            RigidVertex {
                position: [0.75, -0.75, 0.],
                uv: [1., 0.],
                normal: [0., 0., 1.],
            },
            RigidVertex {
                position: [-0.75, 0.75, 0.],
                uv: [0., 1.],
                normal: [0., 0., 1.],
            },
        ]),
        vec![0, 1, 2],
        Some(texture),
    )
    .unwrap();
    for blend in [BlendMode::Alpha, BlendMode::Opaque, BlendMode::Additive] {
        let cpu = RenderTarget::new(SIZE, SIZE, true).unwrap();
        let native = RenderTarget::new(SIZE, SIZE, true).unwrap();
        let mut list = DrawList::new(SIZE, SIZE);
        for (target, resident) in [(&cpu, false), (&native, true)] {
            list.camera(Camera {
                view_projection: Mat4::perspective_rh_gl(1.0, 1., 0.1, 10.),
                target: Some(target.clone()),
                depth_test: true,
            });
            list.clear(Color::TRANSPARENT);
            for (z, color, alpha) in [
                (-3., Color::new(0.25, 0.5, 1., 1.), 1.),
                (-2., Color::WHITE, 0.5),
                (-4., Color::new(1., 0.25, 0.5, 1.), 1.),
            ] {
                let draw = ResidentDraw::new(
                    geometry.clone(),
                    Mat4::from_translation(Vec3::new(0., 0., z)),
                    SceneLighting {
                        direction_to_light: Vec3::Z,
                        ambient: 0.25,
                        diffuse: 0.75,
                    },
                    color,
                    alpha,
                    None,
                )
                .unwrap();
                if resident {
                    list.draw_resident(draw, Mat4::IDENTITY, blend);
                } else {
                    list.draw_mesh(&draw.reference_mesh(), Mat4::IDENTITY, blend);
                }
            }
        }
        assert_eq!(renderer.submit(&list).unwrap().resident.draws, 3);
        pairs.push((cpu, native));
    }
    // No capture command, map registration, or blocking poll happened before
    // all twelve changing-pose submissions. Copying intermediates was GPU-only.
    let mut captures = DrawList::new(SIZE, SIZE);
    for (i, (cpu, native)) in pairs.iter().enumerate() {
        captures.capture_png(Some(cpu), output.join(format!("{i:02}-cpu.png")));
        captures.capture_png(Some(native), output.join(format!("{i:02}-native.png")));
    }
    assert_eq!(renderer.submit(&captures).unwrap().captures.len(), 54);
    let mut report = Vec::new();
    for i in 0..pairs.len() {
        let a = image::open(output.join(format!("{i:02}-cpu.png")))
            .unwrap()
            .to_rgba8();
        let b = image::open(output.join(format!("{i:02}-native.png")))
            .unwrap()
            .to_rgba8();
        let changed = a
            .as_raw()
            .iter()
            .zip(b.as_raw())
            .filter(|(a, b)| a != b)
            .count();
        let max = a
            .as_raw()
            .iter()
            .zip(b.as_raw())
            .map(|(a, b)| a.abs_diff(*b))
            .max()
            .unwrap();
        let foreground = a.pixels().filter(|p| p.0.iter().any(|v| *v != 0)).count();
        report.push(serde_json::json!({"pair":i,"changed_channels":changed,"max_channel_delta":max,"foreground_pixels":foreground}));
    }
    std::fs::write(
        output.join("pixel-report.json"),
        serde_json::to_vec_pretty(&report).unwrap(),
    )
    .unwrap();
    for row in &report {
        assert!(row["foreground_pixels"].as_u64().unwrap() > 50);
        assert_eq!(
            row["max_channel_delta"], 0,
            "native synthetic exact-pixel mismatch: {row}"
        );
    }
    // Recreating the device/renderer necessarily starts a fresh resident cache.
    drop(renderer);
    let mut renderer = pollster::block_on(WgpuRenderer::new_headless(
        SIZE,
        SIZE,
        backend,
        cfg!(target_os = "windows"),
    ))
    .unwrap();
    let mut list = DrawList::new(SIZE, SIZE);
    list.draw_resident(
        draw(sources[0].clone(), 0),
        Mat4::IDENTITY,
        BlendMode::Alpha,
    );
    assert_eq!(renderer.submit(&list).unwrap().resident.cache_misses, 1);
    super::resident_vertex_probe::verify_exact_unorm(&mut renderer, &output);
    eprintln!("resident native contract: 12 queued pose frames and 3 textured perspective frames, 27 exact pixel pairs, cold/warm uploads and fresh-device cache passed");
}
