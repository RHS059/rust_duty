//! Native destination-reuse proof, separate from the immutable finite probe.
//! Requires DX12/WARP: missing initialization fails these tests on Windows.
//! The queue proof submits every changed frame before any map or CPU GPU-wait.
#![cfg(target_os = "windows")]

use super::{
    arena::{clip_matrix, DrawSlice, FrameArena},
    capture::{padded_bytes_per_row, unpack_rows},
    device::{BackendSelection, Gpu},
    mesh::{FragmentKind, FrameGeometry, Pipelines},
    target::{GpuTexture, COLOR_FORMAT},
    upload_cache::{UploadCache, MAX_SLOTS, RETAINED_BYTES},
    WgpuRenderer,
};
use crate::draw::{
    BlendMode, Camera, Color, DrawList, Mesh, RenderTarget, Renderer, Sampler, Texture, Vertex,
};
use glam::{Mat4, Vec3};
use std::{path::PathBuf, sync::mpsc, time::Duration};

const WIDTH: u32 = 64;
const HEIGHT: u32 = 64;

fn warp() -> Gpu {
    let gpu = pollster::block_on(Gpu::new(BackendSelection::Dx12, true, None, WIDTH, HEIGHT))
        .expect("native upload-reuse proof requires DX12/WARP; initialization must not skip");
    assert_eq!(gpu.info.backend, "Dx12");
    gpu
}

fn mesh(seed: usize, ordinal: usize) -> Mesh {
    let x = 2. + (ordinal % 3) as f32 * 18. + (seed % 2) as f32;
    let y = 2. + ((ordinal / 3) % 3) as f32 * 18.;
    let color = Color::new(
        (64 + seed * 23 % 180) as f32 / 255.,
        (48 + ordinal * 37 % 190) as f32 / 255.,
        (32 + seed * 17 % 200) as f32 / 255.,
        1.,
    );
    Mesh {
        vertices: [(x, y), (x + 14., y), (x, y + 14.), (x + 14., y + 14.)]
            .map(|(x, y)| Vertex::new(x, y, 0., 0., 0., color))
            .to_vec(),
        // A single triangle has an odd number of u16 indices. Changing the
        // triangle's half makes a stale index upload visible, even without culling.
        indices: if seed.is_multiple_of(2) {
            vec![0, 1, 2]
        } else {
            vec![1, 3, 2]
        },
        texture: None,
    }
}

fn model(seed: usize) -> Mat4 {
    Mat4::from_translation(Vec3::new((seed % 3) as f32, (seed / 3 % 2) as f32, 0.))
}

struct Batch {
    arena: FrameArena,
    slices: Vec<DrawSlice>,
}

fn batch(gpu: &Gpu, seed: usize, ordinal: usize, draws: usize) -> Batch {
    let limits = gpu.device.limits();
    let mut arena = FrameArena::new(
        limits.min_uniform_buffer_offset_alignment,
        limits.max_buffer_size,
    )
    .unwrap();
    let slices = (0..draws)
        .map(|draw| {
            let mesh = mesh(seed, ordinal + draw);
            arena
                .try_append(
                    &mesh.vertices,
                    &mesh.indices,
                    clip_matrix(Camera::screen(WIDTH, HEIGHT).view_projection, model(seed)),
                )
                .unwrap()
                .expect("small synthetic draw must fit the arena")
        })
        .collect();
    Batch { arena, slices }
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct Handles(wgpu::Buffer, wgpu::Buffer, wgpu::BindGroup);

fn handles(geometry: &FrameGeometry) -> Handles {
    Handles(
        geometry.vertices.clone(),
        geometry.indices.clone(),
        geometry.transform.clone(),
    )
}

fn copy_pixels(
    gpu: &Gpu,
    encoder: &mut wgpu::CommandEncoder,
    texture: &wgpu::Texture,
) -> wgpu::Buffer {
    let row = padded_bytes_per_row(WIDTH).unwrap();
    let buffer = gpu.device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("deferred upload-reuse pixel comparison"),
        size: u64::from(row) * u64::from(HEIGHT),
        usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
        mapped_at_creation: false,
    });
    encoder.copy_texture_to_buffer(
        wgpu::TexelCopyTextureInfo {
            texture,
            mip_level: 0,
            origin: wgpu::Origin3d::ZERO,
            aspect: wgpu::TextureAspect::All,
        },
        wgpu::TexelCopyBufferInfo {
            buffer: &buffer,
            layout: wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(row),
                rows_per_image: Some(HEIGHT),
            },
        },
        wgpu::Extent3d {
            width: WIDTH,
            height: HEIGHT,
            depth_or_array_layers: 1,
        },
    );
    buffer
}

struct NativeFixture {
    gpu: Gpu,
    pipelines: Pipelines,
    pipeline: wgpu::RenderPipeline,
    white: GpuTexture,
    targets: [GpuTexture; 2],
}

impl NativeFixture {
    fn new() -> Self {
        let gpu = warp();
        let mut pipelines = Pipelines::new(&gpu.device);
        let pipeline = pipelines.pipeline(
            &gpu.device,
            COLOR_FORMAT,
            false,
            false,
            BlendMode::Opaque,
            FragmentKind::AssociateStraight,
        );
        let white = GpuTexture::new(
            &gpu.device,
            &gpu.queue,
            &pipelines.texture_layout,
            &Texture::rgba8(1, 1, &[255; 4], Sampler::default()).unwrap(),
        )
        .unwrap();
        let targets = std::array::from_fn(|_| {
            GpuTexture::new(
                &gpu.device,
                &gpu.queue,
                &pipelines.texture_layout,
                &RenderTarget::new(WIDTH, HEIGHT, false).unwrap().texture,
            )
            .unwrap()
        });
        Self {
            gpu,
            pipelines,
            pipeline,
            white,
            targets,
        }
    }

    fn encode(
        &self,
        encoder: &mut wgpu::CommandEncoder,
        target_index: usize,
        batches: &[Batch],
        geometry: &[Option<FrameGeometry>],
    ) -> [wgpu::Buffer; 2] {
        let target = &self.targets[target_index];
        super::frame::clear(encoder, target, Color::TRANSPARENT);
        let mut checkpoint = None;
        for (batch, geometry) in batches.iter().zip(geometry) {
            for slice in &batch.slices {
                let geometry = geometry.as_ref().expect("nonempty draw has geometry");
                {
                    let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                        label: Some("upload-reuse synthetic production-pipeline draw"),
                        color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                            view: &target.view,
                            depth_slice: None,
                            resolve_target: None,
                            ops: wgpu::Operations {
                                load: wgpu::LoadOp::Load,
                                store: wgpu::StoreOp::Store,
                            },
                        })],
                        ..Default::default()
                    });
                    pass.set_pipeline(&self.pipeline);
                    pass.set_bind_group(0, &geometry.transform, &[slice.matrix_offset]);
                    pass.set_bind_group(1, &self.white.binding, &[]);
                    pass.set_vertex_buffer(0, geometry.vertices.slice(slice.vertices.clone()));
                    pass.set_index_buffer(
                        geometry.indices.slice(slice.indices.clone()),
                        wgpu::IndexFormat::Uint16,
                    );
                    pass.draw_indexed(0..slice.count, 0, 0..1);
                }
                if checkpoint.is_none() {
                    checkpoint = Some(copy_pixels(&self.gpu, encoder, &target.texture));
                }
            }
        }
        [
            checkpoint.unwrap_or_else(|| copy_pixels(&self.gpu, encoder, &target.texture)),
            copy_pixels(&self.gpu, encoder, &target.texture),
        ]
    }
}

/// All map registrations and the only blocking poll are after all frame submits.
fn read_after_submissions(gpu: &Gpu, buffers: &[wgpu::Buffer]) -> Vec<Vec<u8>> {
    let (tx, rx) = mpsc::channel();
    for (index, buffer) in buffers.iter().enumerate() {
        let tx = tx.clone();
        buffer
            .slice(..)
            .map_async(wgpu::MapMode::Read, move |result| {
                let _ = tx.send((index, result));
            });
    }
    drop(tx);
    gpu.device
        .poll(wgpu::PollType::Wait {
            submission_index: None,
            timeout: Some(Duration::from_secs(60)),
        })
        .expect("complete all queued synthetic frames");
    for _ in buffers {
        let (index, result) = rx.recv_timeout(Duration::from_secs(5)).unwrap();
        result.unwrap_or_else(|error| panic!("readback {index}: {error}"));
    }
    let pixels = buffers
        .iter()
        .map(|buffer| {
            let mapped = buffer.slice(..).get_mapped_range().unwrap();
            let pixels = unpack_rows(&mapped, WIDTH, HEIGHT).unwrap();
            drop(mapped);
            buffer.unmap();
            pixels
        })
        .collect();
    gpu.check_errors().unwrap();
    pixels
}

#[test]
fn changed_frames_without_cpu_waits_match_fresh_immutable_uploads() {
    let fixture = NativeFixture::new();
    let scope = fixture
        .gpu
        .device
        .push_error_scope(wgpu::ErrorFilter::Validation);
    let mut cache = UploadCache::default();
    let mut observations = Vec::new();
    let mut previous = Vec::<Handles>::new();
    let mut before_empty = None;
    // Repeated sizes, growth, shrink, several slots, an empty frame, then a
    // slot-count overflow. Even the uncached arena must retain its own pixels.
    let cases: &[&[usize]] = &[
        &[1],
        &[1],
        &[9],
        &[1],
        &[1, 1, 1],
        &[1, 1, 1],
        &[],
        &[1],
        &[1, 1, 1, 1, 1, 1, 1, 1, 1],
    ];
    for (frame, counts) in cases.iter().enumerate() {
        cache.begin_frame().unwrap();
        let batches: Vec<_> = if counts.is_empty() {
            vec![batch(&fixture.gpu, frame, 0, 0)]
        } else {
            counts
                .iter()
                .enumerate()
                .map(|(index, &draws)| batch(&fixture.gpu, frame, index, draws))
                .collect()
        };
        let reused: Vec<_> = batches
            .iter()
            .enumerate()
            .map(|(index, batch)| {
                cache
                    .upload(
                        &fixture.gpu.device,
                        &fixture.gpu.queue,
                        &fixture.pipelines,
                        index,
                        &batch.arena,
                    )
                    .unwrap()
            })
            .collect();
        let immutable: Vec<_> = batches
            .iter()
            .map(|batch| {
                fixture
                    .pipelines
                    .upload_geometry(&fixture.gpu.device, &batch.arena)
            })
            .collect();
        let current: Vec<_> = reused.iter().flatten().map(handles).collect();
        match frame {
            1 | 3 => {
                assert_eq!(
                    current, previous,
                    "same-size and shrinking frames must reuse handles"
                );
                assert_eq!(cache.stats.allocations, 0);
                assert_eq!(cache.stats.reuses, 3);
                assert_eq!(cache.stats.bindings, 0);
            }
            2 => {
                assert_ne!(current[0].0, previous[0].0, "vertex growth must allocate");
                assert_ne!(current[0].1, previous[0].1, "index growth must allocate");
                assert_ne!(current[0].2, previous[0].2, "uniform growth must rebind");
                assert_eq!(cache.stats.allocations, 3);
            }
            4 | 5 => {
                assert_eq!(current[0], previous[0]);
                for left in 0..current.len() {
                    for right in left + 1..current.len() {
                        assert_ne!(current[left].0, current[right].0);
                        assert_ne!(current[left].1, current[right].1);
                        assert_ne!(current[left].2, current[right].2);
                    }
                }
                if frame == 5 {
                    assert_eq!(current, previous);
                    assert_eq!(cache.stats.reuses, 9);
                    assert_eq!(cache.stats.allocations, 0);
                    before_empty = Some(current[0].clone());
                }
            }
            6 => {
                assert!(reused.iter().all(Option::is_none));
                assert_eq!(cache.stats.allocations, 0);
                assert_eq!(cache.stats.reuses, 0);
            }
            7 => {
                assert_ne!(current[0], before_empty.clone().unwrap());
                assert_eq!(cache.stats.allocations, 3);
            }
            8 => {
                assert_eq!(counts.len(), MAX_SLOTS + 1);
                assert_eq!(cache.stats.uncached_arenas, 1);
            }
            _ => {}
        }
        assert!(cache.retained_bytes() <= RETAINED_BYTES);
        let mut encoder =
            fixture
                .gpu
                .device
                .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                    label: Some("changed frame with immutable control"),
                });
        let [reuse_mid, reuse_final] = fixture.encode(&mut encoder, 0, &batches, &reused);
        let [fresh_mid, fresh_final] = fixture.encode(&mut encoder, 1, &batches, &immutable);
        observations.extend([reuse_mid, fresh_mid, reuse_final, fresh_final]);
        fixture.gpu.queue.submit([encoder.finish()]);
        cache.submitted();
        if frame == 6 {
            assert_eq!(
                cache.retained_bytes(),
                0,
                "empty frame trims every idle slot"
            );
        }
        previous = current;
    }
    let pixels = read_after_submissions(&fixture.gpu, &observations);
    let validation = pollster::block_on(scope.pop());
    assert!(
        validation.is_none(),
        "native upload validation: {validation:?}"
    );
    for (frame, pair) in pixels.as_chunks::<4>().0.iter().enumerate() {
        assert_eq!(pair[0], pair[1], "frame {frame} mid-frame checkpoint");
        assert_eq!(pair[2], pair[3], "frame {frame} final pixels");
        eprintln!(
            "upload_reuse_native frame={frame} mid_sha256={} final_sha256={} matched_pairs=2",
            rust_duty_launcher::bytes_hash(&pair[0]),
            rust_duty_launcher::bytes_hash(&pair[2]),
        );
        if frame == 6 {
            assert!(pair[2].iter().all(|&byte| byte == 0));
        } else {
            assert!(pair[2]
                .as_chunks::<4>()
                .0
                .iter()
                .any(|pixel| pixel[3] == 255));
        }
    }
    assert_ne!(
        pixels[2], pixels[6],
        "consecutive input changes must be visible"
    );
    assert_ne!(
        pixels[8], pixels[10],
        "later draws must change the growth-frame checkpoint"
    );
    eprintln!(
        "upload_reuse_native queued_frames=9 matched_pixel_pairs=18 cpu_waits_between_submits=0"
    );
}

#[test]
fn uncached_fallback_and_abandoned_writes_match_immutable_pixels() {
    let fixture = NativeFixture::new();
    let scope = fixture
        .gpu
        .device
        .push_error_scope(wgpu::ErrorFilter::Validation);
    let mut cache = UploadCache::for_test(true, 0);
    let mut observations = Vec::new();
    for seed in 0..3 {
        cache.begin_frame().unwrap();
        let batches = [batch(&fixture.gpu, seed, 0, 1)];
        let reused = [cache
            .upload(
                &fixture.gpu.device,
                &fixture.gpu.queue,
                &fixture.pipelines,
                0,
                &batches[0].arena,
            )
            .unwrap()];
        let fresh = [fixture
            .pipelines
            .upload_geometry(&fixture.gpu.device, &batches[0].arena)];
        assert_eq!(cache.stats.uncached_arenas, 1);
        assert_eq!(cache.stats.allocations, 3);
        assert_eq!(cache.stats.reuses, 0);
        assert_eq!(cache.retained_bytes(), 0);
        let mut encoder = fixture
            .gpu
            .device
            .create_command_encoder(&Default::default());
        let reused = fixture.encode(&mut encoder, 0, &batches, &reused);
        let fresh = fixture.encode(&mut encoder, 1, &batches, &fresh);
        observations.extend([
            reused[0].clone(),
            fresh[0].clone(),
            reused[1].clone(),
            fresh[1].clone(),
        ]);
        fixture.gpu.queue.submit([encoder.finish()]);
        cache.submitted();
    }
    // Abandon staged writes without a submit. A following valid frame flushes
    // both sets of writes, so its destinations must be newly allocated.
    let mut cache = UploadCache::default();
    cache.begin_frame().unwrap();
    let abandoned = batch(&fixture.gpu, 4, 0, 1);
    let old = cache
        .upload(
            &fixture.gpu.device,
            &fixture.gpu.queue,
            &fixture.pipelines,
            0,
            &abandoned.arena,
        )
        .unwrap()
        .unwrap();
    let replacement = batch(&fixture.gpu, 5, 3, 1);
    let duplicate = cache
        .upload(
            &fixture.gpu.device,
            &fixture.gpu.queue,
            &fixture.pipelines,
            0,
            &replacement.arena,
        )
        .err()
        .expect("a live slot cannot be written twice before submit");
    assert!(duplicate.contains("slot written twice"));
    cache.clear();
    assert_eq!(cache.retained_bytes(), 0);
    cache.begin_frame().unwrap();
    let batches = [replacement];
    let next = cache
        .upload(
            &fixture.gpu.device,
            &fixture.gpu.queue,
            &fixture.pipelines,
            0,
            &batches[0].arena,
        )
        .unwrap()
        .unwrap();
    assert_ne!(old.vertices, next.vertices);
    assert_ne!(old.indices, next.indices);
    assert_ne!(old.transform, next.transform);
    assert_eq!(cache.stats.allocations, 3);
    let reused = [Some(next)];
    let fresh = [fixture
        .pipelines
        .upload_geometry(&fixture.gpu.device, &batches[0].arena)];
    let mut encoder = fixture
        .gpu
        .device
        .create_command_encoder(&Default::default());
    let [reuse_mid, reuse_final] = fixture.encode(&mut encoder, 0, &batches, &reused);
    let [fresh_mid, fresh_final] = fixture.encode(&mut encoder, 1, &batches, &fresh);
    observations.extend([reuse_mid, fresh_mid, reuse_final, fresh_final]);
    fixture.gpu.queue.submit([encoder.finish()]);
    cache.submitted();

    let pixels = read_after_submissions(&fixture.gpu, &observations);
    let validation = pollster::block_on(scope.pop());
    assert!(
        validation.is_none(),
        "fallback/recovery validation: {validation:?}"
    );
    for (index, pair) in pixels.as_chunks::<2>().0.iter().enumerate() {
        assert_eq!(pair[0], pair[1]);
        assert!(pair[0]
            .as_chunks::<4>()
            .0
            .iter()
            .any(|pixel| pixel[3] == 255));
        eprintln!(
            "upload_reuse_native fallback_or_abandoned_pair={index} sha256={}",
            rust_duty_launcher::bytes_hash(&pair[0]),
        );
    }
}

struct Captures(PathBuf);
impl Captures {
    fn new() -> Self {
        let nonce = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "rust-duty-upload-reuse-{}-{nonce}",
            std::process::id(),
        ));
        std::fs::create_dir_all(&path).unwrap();
        Self(path)
    }
    fn path(&self, name: &str) -> PathBuf {
        self.0.join(format!("{name}.png"))
    }
}
impl Drop for Captures {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn captured_list(captures: &Captures, prefix: &str, seed: usize) -> DrawList {
    let mut list = DrawList::new(WIDTH, HEIGHT);
    list.draw_mesh(&mesh(seed, 0), model(seed), BlendMode::Opaque);
    list.capture_png(None, captures.path(&format!("{prefix}-mid")));
    list.draw_mesh(&mesh(seed + 1, 4), model(seed + 1), BlendMode::Opaque);
    list.capture_png(None, captures.path(&format!("{prefix}-final")));
    list
}

fn assert_captures_equal(captures: &Captures, suffix: &str) {
    let reused = image::open(captures.path(&format!("reuse-{suffix}")))
        .unwrap()
        .to_rgba8();
    let fresh = image::open(captures.path(&format!("fresh-{suffix}")))
        .unwrap()
        .to_rgba8();
    assert_eq!(reused.dimensions(), (WIDTH, HEIGHT));
    assert_eq!(reused, fresh, "production submit {suffix}");
    eprintln!(
        "upload_reuse_native production_checkpoint={suffix} sha256={}",
        rust_duty_launcher::bytes_hash(reused.as_raw()),
    );
}

#[test]
fn renderer_mid_frame_capture_and_rejected_then_valid_frames_match_immutable() {
    let captures = Captures::new();
    let mut reused = pollster::block_on(WgpuRenderer::new_headless(
        WIDTH,
        HEIGHT,
        BackendSelection::Dx12,
        true,
    ))
    .expect("production renderer requires DX12/WARP; initialization must not skip");
    let mut fresh = pollster::block_on(WgpuRenderer::new_headless(
        WIDTH,
        HEIGHT,
        BackendSelection::Dx12,
        true,
    ))
    .expect("immutable control requires DX12/WARP; initialization must not skip");
    fresh.upload_cache = UploadCache::for_test(false, RETAINED_BYTES);
    for seed in 0..2 {
        reused
            .submit(&captured_list(&captures, "reuse", seed))
            .unwrap();
        fresh
            .submit(&captured_list(&captures, "fresh", seed))
            .unwrap();
        assert_captures_equal(&captures, "mid");
        assert_captures_equal(&captures, "final");
        if seed == 1 {
            assert_eq!(reused.upload_cache.stats.allocations, 0);
            assert_eq!(reused.upload_cache.stats.reuses, 3);
        }
    }
    let mid = image::open(captures.path("reuse-mid")).unwrap().to_rgba8();
    let end = image::open(captures.path("reuse-final"))
        .unwrap()
        .to_rgba8();
    assert_ne!(mid, end, "capture copy must precede later geometry");

    for renderer in [&mut reused, &mut fresh] {
        // Rejected in validation, before geometry is uploaded.
        let mut invalid = DrawList::new(WIDTH, HEIGHT);
        let mut invalid_mesh = mesh(3, 0);
        invalid_mesh.indices[0] = 99;
        invalid.draw_mesh(&invalid_mesh, Mat4::IDENTITY, BlendMode::Opaque);
        assert!(renderer
            .submit(&invalid)
            .unwrap_err()
            .contains("mesh index out of range"));

        // Rejected during command encoding, after all geometry queue writes.
        // The next valid frame must never alias an abandoned upload destination.
        let target = RenderTarget::new(WIDTH, HEIGHT, false).unwrap();
        let mut rejected = DrawList::new(WIDTH, HEIGHT);
        let mut camera = Camera::screen(WIDTH, HEIGHT);
        camera.target = Some(target.clone());
        rejected.camera(camera);
        let mut self_sampling = mesh(4, 1);
        self_sampling.texture = Some(target.texture.clone());
        rejected.draw_mesh(&self_sampling, model(4), BlendMode::Opaque);
        rejected.capture_png(None, captures.path("must-not-exist"));
        assert!(renderer
            .submit(&rejected)
            .unwrap_err()
            .contains("cannot sample the current render target"));
        assert_eq!(renderer.upload_cache.retained_bytes(), 0);
        assert!(!captures.path("must-not-exist").exists());
    }
    reused
        .submit(&captured_list(&captures, "reuse", 7))
        .unwrap();
    fresh.submit(&captured_list(&captures, "fresh", 7)).unwrap();
    assert_captures_equal(&captures, "mid");
    assert_captures_equal(&captures, "final");
    assert_eq!(reused.upload_cache.stats.allocations, 3);

    for (name, renderer) in [("reuse", &mut reused), ("fresh", &mut fresh)] {
        let mut empty = DrawList::new(WIDTH, HEIGHT);
        empty.capture_png(None, captures.path(&format!("{name}-empty")));
        renderer.submit(&empty).unwrap();
        assert_eq!(renderer.upload_cache.stats.allocations, 0);
        assert_eq!(renderer.upload_cache.retained_bytes(), 0);
    }
    assert_captures_equal(&captures, "empty");
    let empty = image::open(captures.path("reuse-empty"))
        .unwrap()
        .to_rgba8();
    assert!(empty
        .as_raw()
        .as_chunks::<4>()
        .0
        .iter()
        .all(|pixel| *pixel == [0, 0, 0, 255]));
}
