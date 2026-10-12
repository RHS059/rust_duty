//! Native bounded-staging proof, separate from the immutable finite probe.
//! Requires DX12/WARP: missing initialization fails these tests on Windows.
//! Every changed frame is submitted before readback mapping or a CPU GPU-wait.
#![cfg(target_os = "windows")]

use super::super::{
    arena::{clip_matrix, DrawSlice, FrameArena},
    capture::{padded_bytes_per_row, unpack_rows},
    device::{BackendSelection, Gpu},
    mesh::{FragmentKind, FrameGeometry, Pipelines},
    target::{GpuTexture, COLOR_FORMAT},
};
use super::{UploadCache, RETAINED_BYTES};
use crate::draw::{BlendMode, Camera, Color, Mesh, RenderTarget, Sampler, Texture, Vertex};
use glam::{Mat4, Vec3};
use std::{sync::mpsc, time::Duration};

const WIDTH: u32 = 64;
const HEIGHT: u32 = 64;

fn warp() -> Gpu {
    let gpu = pollster::block_on(Gpu::new(BackendSelection::Dx12, true, None, WIDTH, HEIGHT))
        .expect("native staging-upload proof requires DX12/WARP; initialization must not skip");
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
        label: Some("deferred staging-upload pixel comparison"),
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
        super::super::frame::clear(encoder, target, Color::TRANSPARENT);
        let mut checkpoint = None;
        for (batch, geometry) in batches.iter().zip(geometry) {
            for slice in &batch.slices {
                let geometry = geometry.as_ref().expect("nonempty draw has geometry");
                {
                    let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                        label: Some("staging-upload synthetic production-pipeline draw"),
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

/// Readback maps and the only blocking poll follow all changed-frame submits.
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

fn upload_bytes(batches: &[Batch]) -> u64 {
    batches
        .iter()
        .filter_map(|batch| batch.arena.buffer_contents())
        .flatten()
        .map(|bytes| (bytes.len() as u64 + 3) & !3)
        .sum()
}

fn staged_geometry(
    fixture: &NativeFixture,
    cache: &mut UploadCache,
    batches: &[Batch],
    encoder: &mut wgpu::CommandEncoder,
) -> Vec<Option<FrameGeometry>> {
    batches
        .iter()
        .enumerate()
        .map(|(index, batch)| {
            cache
                .upload_with_encoder(
                    &fixture.gpu.device,
                    &fixture.gpu.queue,
                    &fixture.pipelines,
                    index,
                    &batch.arena,
                    encoder,
                )
                .unwrap()
        })
        .collect()
}

fn queue_geometry(
    fixture: &NativeFixture,
    cache: &mut UploadCache,
    batches: &[Batch],
) -> Vec<Option<FrameGeometry>> {
    batches
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
        .collect()
}

fn record_pair(
    fixture: &NativeFixture,
    encoder: &mut wgpu::CommandEncoder,
    batches: &[Batch],
    staged: &[Option<FrameGeometry>],
    control: &[Option<FrameGeometry>],
    observations: &mut Vec<wgpu::Buffer>,
) {
    let [staged_mid, staged_final] = fixture.encode(encoder, 0, batches, staged);
    let [control_mid, control_final] = fixture.encode(encoder, 1, batches, control);
    observations.extend([staged_mid, control_mid, staged_final, control_final]);
}

fn assert_pairs(pixels: &[Vec<u8>], label: &str) {
    let (frames, remainder) = pixels.as_chunks::<4>();
    assert!(remainder.is_empty());
    assert!(!frames.is_empty());
    for (frame, pair) in frames.iter().enumerate() {
        assert_eq!(pair[0].len(), (WIDTH * HEIGHT * 4) as usize);
        assert_eq!(pair[2].len(), (WIDTH * HEIGHT * 4) as usize);
        assert_eq!(pair[0], pair[1], "{label} frame {frame} checkpoint bytes");
        assert_eq!(pair[2], pair[3], "{label} frame {frame} final bytes");
        eprintln!(
            "staging_upload_native case={label} frame={frame} mid_sha256={} final_sha256={} matched_rgba_bytes={}",
            rust_duty_launcher::bytes_hash(&pair[0]),
            rust_duty_launcher::bytes_hash(&pair[2]),
            pair[0].len() + pair[2].len(),
        );
    }
}

#[test]
fn changed_queued_frames_match_queuewrite_at_every_pixel() {
    let fixture = NativeFixture::new();
    let scope = fixture
        .gpu
        .device
        .push_error_scope(wgpu::ErrorFilter::Validation);
    let staging_budget = 16 * 1024 * 1024;
    let mut staging = UploadCache::for_staging_test(true, RETAINED_BYTES, staging_budget, 64);
    let mut control = UploadCache::for_test(true, RETAINED_BYTES);
    let mut observations = Vec::new();
    let mut previous = Vec::<Handles>::new();
    let mut staged_bytes = 0;
    // Plenty of source slots, so correctness does not depend on callback timing.
    // Repeated sizes, growth, shrink, simultaneous slots, empty, then fresh work.
    let cases: &[&[usize]] = &[
        &[1],
        &[1],
        &[9],
        &[1],
        &[1, 1, 1],
        &[1, 1, 1],
        &[],
        &[1],
        &[1, 1, 1],
    ];
    for (frame, counts) in cases.iter().enumerate() {
        staging
            .begin_frame_with_device(&fixture.gpu.device)
            .unwrap();
        control.begin_frame().unwrap();
        let batches: Vec<_> = if counts.is_empty() {
            vec![batch(&fixture.gpu, frame, 0, 0)]
        } else {
            counts
                .iter()
                .enumerate()
                .map(|(ordinal, &draws)| batch(&fixture.gpu, frame, ordinal, draws))
                .collect()
        };
        let bytes = upload_bytes(&batches);
        let mut encoder = fixture
            .gpu
            .device
            .create_command_encoder(&Default::default());
        let staged = staged_geometry(&fixture, &mut staging, &batches, &mut encoder);
        let queued = queue_geometry(&fixture, &mut control, &batches);
        let current: Vec<_> = staged.iter().flatten().map(handles).collect();
        match frame {
            1 | 3 | 5 => assert_eq!(current, previous, "destination reuse at frame {frame}"),
            2 => {
                assert_ne!(current[0].0, previous[0].0, "vertex growth must allocate");
                assert_ne!(current[0].1, previous[0].1, "index growth must allocate");
                assert_ne!(current[0].2, previous[0].2, "uniform growth must rebind");
            }
            6 => assert!(staged.iter().all(Option::is_none)),
            _ => {}
        }
        let stats = staging.staging_stats();
        assert_eq!(stats.staging_copy_bytes, bytes);
        assert_eq!(stats.staging_queue_write_calls, 0);
        assert_eq!(stats.staging_queue_write_bytes, 0);
        assert_eq!(stats.staging_fallback_arenas, 0);
        assert_eq!(stats.staging_map_failures, 0);
        assert!(stats.staging_retained_bytes <= staging_budget);
        assert!(staging.retained_bytes() <= RETAINED_BYTES);
        if bytes != 0 {
            assert!(stats.staging_buffer_allocations + stats.staging_buffer_reuses > 0);
        }
        staged_bytes += stats.staging_copy_bytes;
        record_pair(
            &fixture,
            &mut encoder,
            &batches,
            &staged,
            &queued,
            &mut observations,
        );
        let commands = encoder.finish();
        // CPU input and temporary destination handles are gone before submit.
        // The encoded copies/draws must keep both GPU resource types alive.
        drop(batches);
        drop(staged);
        drop(queued);
        fixture.gpu.queue.submit([commands]);
        staging.submitted();
        control.submitted();
        previous = current;
    }
    let pixels = read_after_submissions(&fixture.gpu, &observations);
    // The terminal readback also completes source remaps. Exercise a real
    // mapped-source checkout now, without an extra submission or blocking wait.
    staging
        .begin_frame_with_device(&fixture.gpu.device)
        .unwrap();
    let probe = [batch(&fixture.gpu, 40, 0, 1)];
    let mut encoder = fixture
        .gpu
        .device
        .create_command_encoder(&Default::default());
    let geometry = staged_geometry(&fixture, &mut staging, &probe, &mut encoder);
    assert_eq!(staging.staging_stats().staging_buffer_allocations, 0);
    assert_eq!(staging.staging_stats().staging_buffer_reuses, 1);
    assert_eq!(
        staging.staging_stats().staging_copy_bytes,
        upload_bytes(&probe)
    );
    drop(encoder);
    drop(geometry);
    staging.clear();
    let validation = pollster::block_on(scope.pop());
    assert!(validation.is_none(), "staging validation: {validation:?}");
    assert_pairs(&pixels, "changed-queued");
    assert!(pixels[6 * 4 + 2].iter().all(|&byte| byte == 0));
    for (frame, pair) in pixels.as_chunks::<4>().0.iter().enumerate() {
        if frame != 6 {
            assert!(pair[2]
                .as_chunks::<4>()
                .0
                .iter()
                .any(|pixel| pixel[3] == 255));
        }
    }
    assert_ne!(
        pixels[2], pixels[6],
        "changed inputs must change final pixels"
    );
    assert_ne!(
        pixels[8], pixels[10],
        "later draws must change the checkpoint"
    );
    eprintln!(
        "staging_upload_native queued_frames={} matched_pixel_pairs={} copy_bytes={staged_bytes} cpu_waits_between_submits=0",
        cases.len(), cases.len() * 2,
    );
}

#[test]
fn exhausted_budget_and_busy_sources_use_padded_queuewrite_fallback() {
    let fixture = NativeFixture::new();
    let scope = fixture
        .gpu
        .device
        .push_error_scope(wgpu::ErrorFilter::Validation);
    let mut observations = Vec::new();
    let mut control = UploadCache::for_test(true, RETAINED_BYTES);
    // A zero-byte budget forces all queue writes; one held source slot forces
    // busy fallback after the first submit even if WARP has already completed it.
    let scenarios = [
        (0, 1, 3),
        (4096, 1, 3),
        (4096, super::staging::MAX_CHUNKS, 9),
    ];
    assert_eq!(
        super::staging::MAX_CHUNKS,
        8,
        "production source-slot bound"
    );
    for (scenario, (budget, slots, frames)) in scenarios.into_iter().enumerate() {
        let mut staging = UploadCache::for_staging_test(true, RETAINED_BYTES, budget, slots);
        staging.hold_ready_for_test(true);
        let mut previous = None;
        for frame in 0..frames {
            staging
                .begin_frame_with_device(&fixture.gpu.device)
                .unwrap();
            control.begin_frame().unwrap();
            let draws = if frame + 1 == frames { 3 } else { 1 };
            let batches = [batch(&fixture.gpu, scenario * 3 + frame, 0, draws)];
            let contents = batches[0].arena.buffer_contents().unwrap();
            assert_eq!(contents[1].len() % 4, 2, "odd-u16 index fixture");
            let bytes = upload_bytes(&batches);
            let unpadded: u64 = contents.iter().map(|part| part.len() as u64).sum();
            assert_eq!(bytes, unpadded + 2, "exactly two zero-padding bytes");
            let mut encoder = fixture
                .gpu
                .device
                .create_command_encoder(&Default::default());
            let staged = staged_geometry(&fixture, &mut staging, &batches, &mut encoder);
            let queued = queue_geometry(&fixture, &mut control, &batches);
            let current = handles(staged[0].as_ref().unwrap());
            if frame == 1 {
                assert_eq!(
                    Some(&current),
                    previous.as_ref(),
                    "busy source preserves destination reuse"
                );
            } else if frame + 1 == frames {
                assert_ne!(
                    Some(&current),
                    previous.as_ref(),
                    "growth replaces the in-flight destination"
                );
            }
            let stats = staging.staging_stats();
            if scenario != 0 && frame < slots {
                assert_eq!(stats.staging_copy_bytes, bytes);
                assert_eq!(stats.staging_fallback_arenas, 0);
                assert_eq!(stats.staging_queue_write_calls, 0);
                assert!(stats.staging_buffer_allocations > 0);
            } else {
                assert_eq!(stats.staging_copy_bytes, 0);
                assert_eq!(stats.staging_fallback_arenas, 1);
                assert_eq!(stats.staging_queue_write_calls, 3);
                assert_eq!(stats.staging_queue_write_bytes, bytes);
                assert_eq!(stats.staging_buffer_allocations, 0);
                assert_eq!(stats.staging_buffer_reuses, 0);
            }
            assert!(stats.staging_retained_bytes <= budget);
            assert!(stats.staging_pending_buffers <= slots as u64);
            assert_eq!(stats.staging_map_failures, 0);
            record_pair(
                &fixture,
                &mut encoder,
                &batches,
                &staged,
                &queued,
                &mut observations,
            );
            let commands = encoder.finish();
            drop(batches);
            drop(staged);
            drop(queued);
            fixture.gpu.queue.submit([commands]);
            staging.submitted();
            control.submitted();
            if scenario != 0 {
                assert!(staging.staging_stats().staging_pending_buffers > 0);
            }
            previous = Some(current);
        }
        // Still no wait: clear drops destinations but pending sources remain
        // charged until completion. Dropping the entire cache also must be safe.
        let before_clear = staging.staging_stats();
        staging.clear();
        assert_eq!(staging.retained_bytes(), 0);
        assert_eq!(
            staging.staging_stats().staging_retained_bytes,
            before_clear.staging_retained_bytes
        );
        assert_eq!(
            staging.staging_stats().staging_pending_buffers,
            before_clear.staging_pending_buffers
        );
        drop(staging);
    }
    let pixels = read_after_submissions(&fixture.gpu, &observations);
    let validation = pollster::block_on(scope.pop());
    assert!(validation.is_none(), "fallback validation: {validation:?}");
    assert_pairs(&pixels, "budget-and-busy");
    for pair in pixels.as_chunks::<4>().0 {
        assert!(pair[2]
            .as_chunks::<4>()
            .0
            .iter()
            .any(|pixel| pixel[3] == 255));
    }
    eprintln!("staging_upload_native fallback_frames=6 padded_odd_u16_frames=15 cpu_waits_between_submits=0");
}

#[test]
fn aborted_encoder_and_postsubmit_clear_never_recycle_late_callbacks() {
    let fixture = NativeFixture::new();
    let scope = fixture
        .gpu
        .device
        .push_error_scope(wgpu::ErrorFilter::Validation);
    let mut staging =
        UploadCache::for_staging_test(true, RETAINED_BYTES, 4096, super::staging::MAX_CHUNKS);
    staging.hold_ready_for_test(true);
    let mut control = UploadCache::for_test(true, RETAINED_BYTES);
    let mut observations = Vec::new();
    staging
        .begin_frame_with_device(&fixture.gpu.device)
        .unwrap();
    let abandoned_batch = [batch(&fixture.gpu, 20, 0, 1)];
    let mut abandoned_encoder = fixture
        .gpu
        .device
        .create_command_encoder(&Default::default());
    let abandoned = staged_geometry(
        &fixture,
        &mut staging,
        &abandoned_batch,
        &mut abandoned_encoder,
    );
    let abandoned_handles = handles(abandoned[0].as_ref().unwrap());
    assert!(staging.staging_stats().staging_copy_bytes > 0);
    drop(abandoned_encoder);
    drop(abandoned_batch);
    drop(abandoned);
    // The begin-frame rejection must discard the abandoned upload generation.
    assert!(staging
        .begin_frame_with_device(&fixture.gpu.device)
        .is_err());
    assert_eq!(staging.retained_bytes(), 0);
    let mut old_handles = vec![abandoned_handles];
    // Finishing an encoder transfers its deferred callback to the command
    // buffer. Dropping that buffer without submit is a separate cancellation
    // boundary and must never turn this source into a ready pooled checkout.
    staging
        .begin_frame_with_device(&fixture.gpu.device)
        .unwrap();
    assert_eq!(staging.staging_stats().staging_retained_bytes, 0);
    assert_eq!(staging.staging_stats().staging_pending_buffers, 0);
    let cancelled_batch = [batch(&fixture.gpu, 25, 0, 1)];
    let mut cancelled_encoder = fixture
        .gpu
        .device
        .create_command_encoder(&Default::default());
    let cancelled = staged_geometry(
        &fixture,
        &mut staging,
        &cancelled_batch,
        &mut cancelled_encoder,
    );
    assert_eq!(staging.staging_stats().staging_buffer_allocations, 1);
    assert_eq!(staging.staging_stats().staging_buffer_reuses, 0);
    old_handles.push(handles(cancelled[0].as_ref().unwrap()));
    let cancelled_commands = cancelled_encoder.finish();
    drop(cancelled_batch);
    drop(cancelled);
    drop(cancelled_commands);
    staging.clear();
    assert_eq!(staging.retained_bytes(), 0);
    for frame in 0..3 {
        staging
            .begin_frame_with_device(&fixture.gpu.device)
            .unwrap();
        if frame == 0 {
            assert_eq!(staging.staging_stats().staging_retained_bytes, 0);
            assert_eq!(staging.staging_stats().staging_pending_buffers, 0);
            assert_eq!(staging.staging_stats().staging_map_failures, 0);
        }
        control.begin_frame().unwrap();
        let batches = [batch(&fixture.gpu, 21 + frame, frame, 1)];
        let mut encoder = fixture
            .gpu
            .device
            .create_command_encoder(&Default::default());
        let staged = staged_geometry(&fixture, &mut staging, &batches, &mut encoder);
        let queued = queue_geometry(&fixture, &mut control, &batches);
        let current = handles(staged[0].as_ref().unwrap());
        for old in &old_handles {
            assert_ne!(current.0, old.0, "cleared vertex destination cannot alias");
            assert_ne!(current.1, old.1, "cleared index destination cannot alias");
            assert_ne!(current.2, old.2, "cleared binding cannot alias");
        }
        let stats = staging.staging_stats();
        assert!(stats.staging_buffer_allocations > 0);
        assert_eq!(stats.staging_buffer_reuses, 0);
        assert_eq!(stats.staging_fallback_arenas, 0);
        assert_eq!(stats.staging_copy_bytes, upload_bytes(&batches));
        record_pair(
            &fixture,
            &mut encoder,
            &batches,
            &staged,
            &queued,
            &mut observations,
        );
        let commands = encoder.finish();
        drop(batches);
        drop(staged);
        drop(queued);
        fixture.gpu.queue.submit([commands]);
        staging.submitted();
        control.submitted();
        assert!(staging.staging_stats().staging_pending_buffers > 0);
        let before_clear = staging.staging_stats();
        staging.clear();
        assert_eq!(staging.retained_bytes(), 0);
        assert_eq!(
            staging.staging_stats().staging_retained_bytes,
            before_clear.staging_retained_bytes
        );
        assert!(staging.staging_stats().staging_pending_buffers > 0);
        old_handles.push(current);
    }
    let pixels = read_after_submissions(&fixture.gpu, &observations);
    assert_pairs(&pixels, "aborted-and-cleared");
    // The final test-only poll above has delivered all old map callbacks. Draining
    // them on the next begin must not resurrect any cleared pool generation.
    staging.hold_ready_for_test(false);
    staging
        .begin_frame_with_device(&fixture.gpu.device)
        .unwrap();
    assert_eq!(staging.staging_stats().staging_retained_bytes, 0);
    assert_eq!(staging.staging_stats().staging_pending_buffers, 0);
    let probe = [batch(&fixture.gpu, 30, 0, 1)];
    let mut encoder = fixture
        .gpu
        .device
        .create_command_encoder(&Default::default());
    let geometry = staged_geometry(&fixture, &mut staging, &probe, &mut encoder);
    let stats = staging.staging_stats();
    assert!(
        stats.staging_buffer_allocations > 0,
        "late callbacks cannot recycle cleared sources"
    );
    assert_eq!(stats.staging_buffer_reuses, 0);
    assert_eq!(stats.staging_map_failures, 0);
    let current = handles(geometry[0].as_ref().unwrap());
    assert!(old_handles.iter().all(|old| current.0 != old.0));
    drop(encoder);
    drop(geometry);
    staging.clear();
    let validation = pollster::block_on(scope.pop());
    assert!(
        validation.is_none(),
        "aborted/clear validation: {validation:?}"
    );
    fixture.gpu.check_errors().unwrap();
    eprintln!("staging_upload_native aborted_encoders=2 dropped_unsubmitted_command_buffers=1 postsubmit_clears=3 late_callback_reuses=0 cpu_waits_between_submits=0");
}
