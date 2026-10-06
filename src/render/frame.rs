//! Commands are encoded in list order, including copies at mid-frame capture checkpoints.
use super::{
    arena::DrawSlice,
    capture::{CaptureEncoding, Readback},
    mesh::{FragmentKind, FrameGeometry},
    plan::{draw_run_len, FramePlan, PreparedCommand, PreparedDraw},
    target::{self, GpuTexture},
    WgpuRenderer,
};
use crate::draw::{BlendMode, Color, Command, DrawList, FrameOutput, RenderTarget, TextureSource};
use std::sync::Arc;

impl WgpuRenderer {
    pub(super) fn submit_frame(&mut self, list: &DrawList) -> Result<FrameOutput, String> {
        // Take ownership up front: failures drop this surface texture, and no
        // command path can acquire another texture after app/input advance.
        let presentation = super::backend::take_presentation(
            &mut self.prepared,
            self.gpu.surface.is_some(),
            list.width,
            list.height,
        )?;
        self.gpu.check_errors()?;
        validate(list, &self.gpu.device.limits())?;
        // Retire only glyphs absent from the complete frame, before encoding
        // any commands. Dropping cached GPU handles does not rewrite textures
        // retained by older in-flight submissions or recorded CPU meshes.
        let retired = self
            .text
            .prepare_frame(list.commands.iter().filter_map(|command| match command {
                Command::Text { text, size, .. } => Some((text.as_str(), *size)),
                _ => None,
            }))?;
        for id in retired {
            self.release_texture(id);
        }
        let error_scope = self
            .gpu
            .device
            .push_error_scope(wgpu::ErrorFilter::Validation);
        let encoded = self.encode_frame(list, presentation);
        let validation = pollster::block_on(error_scope.pop());
        if let Some(error) = validation {
            return Err(format!("frame validation: {error}"));
        }
        self.gpu.check_errors()?;
        let (readbacks, presentation) = encoded?;
        let mut output = FrameOutput::default();
        for readback in readbacks {
            output.captures.push(readback.finish(&self.gpu.device)?);
        }
        if let Some(presentation) = presentation {
            self.gpu.queue.present(presentation);
        }
        self.gpu.check_errors()?;
        Ok(output)
    }
    fn encode_frame(
        &mut self,
        list: &DrawList,
        presentation: Option<wgpu::SurfaceTexture>,
    ) -> Result<(Vec<Readback>, Option<wgpu::SurfaceTexture>), String> {
        if self.main.descriptor.width != list.width || self.main.descriptor.height != list.height {
            self.main = Arc::new(GpuTexture::new(
                &self.gpu.device,
                &self.gpu.queue,
                &self.pipelines.texture_layout,
                &RenderTarget::new(list.width, list.height, true)?.texture,
            )?);
        }
        let limits = self.gpu.device.limits();
        let plan = FramePlan::new(
            list,
            &mut self.text,
            limits.min_uniform_buffer_offset_alignment,
            limits.max_buffer_size,
            presentation.is_some(),
        )?;
        let geometry: Vec<_> = plan
            .arenas
            .iter()
            .map(|arena| self.pipelines.upload_geometry(&self.gpu.device, arena))
            .collect();
        let mut encoder = self
            .gpu
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                label: Some("ordered presentation frame"),
            });
        clear(&mut encoder, &self.main, Color::TRANSPARENT);
        let mut readbacks = Vec::new();
        let mut commands = plan.commands.as_slice();
        while let Some((command, following)) = commands.split_first() {
            let mut consumed = 1;
            match command {
                PreparedCommand::Camera(camera) => {
                    if let Some(target) = &camera.target {
                        self.texture(&target.texture)?;
                    }
                }
                PreparedCommand::Clear { target, color } => {
                    let output = self.output(target.as_ref())?;
                    clear(&mut encoder, &output, *color);
                }
                PreparedCommand::Draw(draw) => {
                    consumed = draw_run_len(commands);
                    self.draw_prepared_run(
                        &mut encoder,
                        &geometry,
                        draw,
                        &following[..consumed - 1],
                    )?;
                }
                PreparedCommand::Capture { target, path } => {
                    let output = self.output(target.as_ref())?;
                    // Capture remains an in-order GPU copy, before later draws
                    // or clears. All maps still finish after the same submission.
                    readbacks.push(Readback::encode(
                        &self.gpu.device,
                        &mut encoder,
                        &output.texture,
                        path.clone(),
                        CaptureEncoding::for_target(target.as_ref()),
                    )?);
                }
            }
            commands = &commands[consumed..];
        }
        if let Some(frame) = &presentation {
            let surface = self
                .gpu
                .surface
                .as_ref()
                .expect("a presentation frame has a surface");
            let view = frame
                .texture
                .create_view(&wgpu::TextureViewDescriptor::default());
            let pipeline = self.pipelines.pipeline(
                &self.gpu.device,
                surface.config.format,
                false,
                false,
                BlendMode::Opaque,
                FragmentKind::Present,
            );
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("present main target"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &view,
                    depth_slice: None,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                ..Default::default()
            });
            let present = plan
                .present
                .as_ref()
                .expect("presentation has a draw slice");
            issue(
                &mut pass,
                &pipeline,
                geometry[present.arena_index]
                    .as_ref()
                    .expect("presentation has frame buffers"),
                &present.range,
                &self.main.binding,
            );
        }
        self.gpu.queue.submit([encoder.finish()]);
        Ok((readbacks, presentation))
    }
    fn output(&mut self, target: Option<&RenderTarget>) -> Result<Arc<GpuTexture>, String> {
        match target {
            Some(target) => self.texture(&target.texture),
            None => Ok(self.main.clone()),
        }
    }
    fn draw_prepared_run(
        &mut self,
        encoder: &mut wgpu::CommandEncoder,
        geometry: &[Option<FrameGeometry>],
        first: &PreparedDraw,
        following: &[PreparedCommand],
    ) -> Result<(), String> {
        let output = self.output(first.target.as_ref())?;
        let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("ordered draw run"),
            color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                view: &output.view,
                depth_slice: None,
                resolve_target: None,
                ops: wgpu::Operations {
                    load: wgpu::LoadOp::Load,
                    store: wgpu::StoreOp::Store,
                },
            })],
            depth_stencil_attachment: if first.depth_test {
                output
                    .depth
                    .as_ref()
                    .map(|view| wgpu::RenderPassDepthStencilAttachment {
                        view,
                        depth_ops: Some(wgpu::Operations {
                            load: wgpu::LoadOp::Load,
                            store: wgpu::StoreOp::Store,
                        }),
                        stencil_ops: None,
                    })
            } else {
                None
            },
            ..Default::default()
        });
        self.draw_prepared_mesh(&mut pass, geometry, first)?;
        for command in following {
            let PreparedCommand::Draw(draw) = command else {
                unreachable!("draw run ends before non-draw commands")
            };
            self.draw_prepared_mesh(&mut pass, geometry, draw)?;
        }
        Ok(())
    }
    fn draw_prepared_mesh(
        &mut self,
        pass: &mut wgpu::RenderPass<'_>,
        geometry: &[Option<FrameGeometry>],
        draw: &PreparedDraw,
    ) -> Result<(), String> {
        // Resolve and validate each draw at its original command position. The
        // cached owned handles remain valid while wgpu records their use; no
        // borrowed temporary resources or draws are saved for a later flush.
        let output = self.output(draw.target.as_ref())?;
        let texture = match &draw.texture {
            Some(texture) => self.texture(texture)?,
            None => self.white.clone(),
        };
        if Arc::ptr_eq(&output, &texture) {
            return Err("cannot sample the current render target while drawing into it".into());
        }
        if draw.depth_test && output.depth.is_none() {
            return Err("depth-enabled camera requires a target with depth storage".into());
        }
        let pipeline = self.pipelines.pipeline(
            &self.gpu.device,
            target::COLOR_FORMAT,
            draw.depth_test,
            draw.lines,
            draw.blend,
            FragmentKind::for_source(&texture.descriptor.source, draw.blend),
        );
        issue(
            pass,
            &pipeline,
            geometry[draw.geometry.arena_index]
                .as_ref()
                .expect("prepared draw has frame buffers"),
            &draw.geometry.range,
            &texture.binding,
        );
        Ok(())
    }
}
fn issue(
    pass: &mut wgpu::RenderPass<'_>,
    pipeline: &wgpu::RenderPipeline,
    geometry: &FrameGeometry,
    slice: &DrawSlice,
    texture: &wgpu::BindGroup,
) {
    pass.set_pipeline(pipeline);
    pass.set_bind_group(0, &geometry.transform, &[slice.matrix_offset]);
    pass.set_bind_group(1, texture, &[]);
    pass.set_vertex_buffer(0, geometry.vertices.slice(slice.vertices.clone()));
    pass.set_index_buffer(
        geometry.indices.slice(slice.indices.clone()),
        wgpu::IndexFormat::Uint16,
    );
    pass.draw_indexed(0..slice.count, 0, 0..1);
}
pub(super) fn clear(encoder: &mut wgpu::CommandEncoder, target: &GpuTexture, color: Color) {
    let _pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
        label: Some("clear camera target"),
        color_attachments: &[Some(wgpu::RenderPassColorAttachment {
            view: &target.view,
            depth_slice: None,
            resolve_target: None,
            ops: wgpu::Operations {
                load: wgpu::LoadOp::Clear(target::clear_color(color)),
                store: wgpu::StoreOp::Store,
            },
        })],
        depth_stencil_attachment: target.depth.as_ref().map(|view| {
            wgpu::RenderPassDepthStencilAttachment {
                view,
                depth_ops: Some(wgpu::Operations {
                    load: wgpu::LoadOp::Clear(1.),
                    store: wgpu::StoreOp::Store,
                }),
                stencil_ops: None,
            }
        }),
        ..Default::default()
    });
}
fn validate(list: &DrawList, limits: &wgpu::Limits) -> Result<(), String> {
    if list.width == 0 || list.height == 0 {
        return Err("draw-list extent must be nonzero (defer minimized windows)".into());
    }
    if list.width > limits.max_texture_dimension_2d || list.height > limits.max_texture_dimension_2d
    {
        return Err("draw-list extent exceeds adapter limit".into());
    }
    let color = |c: Color| {
        if [c.r, c.g, c.b, c.a].into_iter().all(f32::is_finite) {
            Ok(())
        } else {
            Err("non-finite draw color".to_owned())
        }
    };
    let target = |t: &RenderTarget| -> Result<(), String> {
        target::validate(&t.texture, limits)?;
        if !matches!(t.texture.source, TextureSource::Target { .. }) {
            return Err("render-target handle does not refer to target storage".into());
        }
        Ok(())
    };
    for command in &list.commands {
        match command {
            Command::Camera(camera) => {
                if !camera.view_projection.is_finite() {
                    return Err("non-finite camera transform".into());
                }
                if let Some(t) = &camera.target {
                    target(t)?;
                    if camera.depth_test
                        && matches!(t.texture.source, TextureSource::Target { depth: false })
                    {
                        return Err("depth-enabled camera requires a depth target".into());
                    }
                }
            }
            Command::Clear(c) => color(*c)?,
            Command::Mesh { mesh, model, .. } => {
                mesh.validate()?;
                if !model.is_finite() {
                    return Err("non-finite model transform".into());
                }
                if mesh.vertices.len() as u64 * super::mesh::GpuVertex::STRIDE
                    > limits.max_buffer_size
                    || mesh.indices.len() as u64 * 2 > limits.max_buffer_size
                    || mesh.indices.len() > u32::MAX as usize
                {
                    return Err("mesh exceeds adapter buffer limit".into());
                }
                if let Some(texture) = &mesh.texture {
                    target::validate(texture, limits)?;
                }
            }
            Command::Lines { lines, model } => {
                if !model.is_finite() {
                    return Err("non-finite line transform".into());
                }
                for line in lines {
                    if !line.start.is_finite() || !line.end.is_finite() {
                        return Err("non-finite line endpoint".into());
                    }
                    color(line.color)?;
                }
            }
            Command::Rect { rect, color: c }
            | Command::Sprite {
                destination: rect,
                tint: c,
                ..
            } => {
                if ![
                    rect.x,
                    rect.y,
                    rect.w,
                    rect.h,
                    rect.x + rect.w,
                    rect.y + rect.h,
                ]
                .into_iter()
                .all(f32::is_finite)
                {
                    return Err("non-finite screen rectangle".into());
                }
                color(*c)?;
                if let Command::Sprite { texture, .. } = command {
                    target::validate(texture, limits)?;
                }
            }
            Command::Text {
                baseline,
                size,
                color: c,
                ..
            } => {
                super::text::validate_size(*size)?;
                if !baseline.is_finite() {
                    return Err("text requires finite coordinates".into());
                }
                color(*c)?;
            }
            Command::Capture { target: t, path } => {
                if let Some(t) = t {
                    target(t)?;
                }
                if path.as_os_str().is_empty() {
                    return Err("capture path must not be empty".into());
                }
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::draw::{Camera, Mesh, Rect, Sampler, Texture};
    use glam::{Mat4, Vec3};
    use std::ops::Range;

    fn draw(target: Option<&RenderTarget>, depth_test: bool, index: u32) -> PreparedCommand {
        PreparedCommand::Draw(PreparedDraw {
            target: target.cloned(),
            depth_test,
            texture: None,
            blend: BlendMode::Alpha,
            lines: false,
            geometry: super::super::plan::GeometrySlice {
                arena_index: 0,
                range: DrawSlice {
                    vertices: u64::from(index) * 120..u64::from(index + 1) * 120,
                    indices: u64::from(index) * 6..u64::from(index + 1) * 6,
                    matrix_offset: index * 256,
                    count: 3,
                },
            },
        })
    }

    fn draw_runs(commands: &[PreparedCommand]) -> Vec<Range<usize>> {
        let mut runs = Vec::new();
        let mut position = 0;
        while position < commands.len() {
            let count = draw_run_len(&commands[position..]);
            if count != 0 {
                runs.push(position..position + count);
            }
            position += count.max(1);
        }
        runs
    }

    #[test]
    fn grouping_preserves_camera_clear_capture_and_attachment_boundaries() {
        let a = RenderTarget::new(40, 20, true).unwrap();
        let b = RenderTarget::new(40, 20, true).unwrap();
        let commands = vec![
            draw(None, false, 0),
            draw(None, false, 1),
            PreparedCommand::Camera(Camera::screen(100, 50)),
            draw(None, false, 2),
            PreparedCommand::Clear {
                target: None,
                color: Color::WHITE,
            },
            draw(None, false, 3),
            PreparedCommand::Capture {
                target: Some(b.clone()),
                path: "other-target.png".into(),
            },
            draw(None, false, 4),
            draw(None, true, 5),
            draw(None, true, 6),
            draw(Some(&a), true, 7),
            draw(Some(&b), true, 8),
            draw(Some(&a), true, 9),
            draw(Some(&a), false, 10),
            draw(Some(&a), false, 11),
        ];
        let runs = draw_runs(&commands);
        assert_eq!(
            runs,
            [
                0..2,
                3..4,
                5..6,
                7..8,
                8..10,
                10..11,
                11..12,
                12..13,
                13..15
            ]
        );
        // Flatten the actual grouping rule and compare with the original
        // logical draw sequence, including exact immutable draw identities.
        let before: Vec<_> = commands
            .iter()
            .filter_map(|command| match command {
                PreparedCommand::Draw(draw) => Some(draw as *const PreparedDraw),
                _ => None,
            })
            .collect();
        let after: Vec<_> = runs
            .into_iter()
            .flat_map(|range| &commands[range])
            .map(|command| {
                let PreparedCommand::Draw(draw) = command else {
                    panic!("draw run crossed a barrier")
                };
                draw as *const PreparedDraw
            })
            .collect();
        assert_eq!(after, before);
    }

    #[test]
    fn empty_draw_groups_do_not_open_passes() {
        assert_eq!(draw_run_len(&[]), 0);
        let commands = [
            PreparedCommand::Camera(Camera::screen(100, 50)),
            PreparedCommand::Camera(Camera::screen(100, 50)),
            PreparedCommand::Clear {
                target: None,
                color: Color::WHITE,
            },
            PreparedCommand::Capture {
                target: None,
                path: "empty.png".into(),
            },
        ];
        assert!(draw_runs(&commands).is_empty());
        let mut list = DrawList::new(100, 50);
        list.draw_mesh(&Mesh::default(), Mat4::IDENTITY, BlendMode::Opaque);
        list.draw_text("  ", glam::Vec2::ZERO, 16., Color::WHITE);
        let plan = FramePlan::new(
            &list,
            &mut super::super::text::TextRenderer::new().unwrap(),
            256,
            1024,
            false,
        )
        .unwrap();
        assert!(draw_runs(&plan.commands).is_empty());
        assert!(plan.present.is_none());
    }

    #[test]
    fn alternating_pipeline_texture_and_arena_state_stays_in_one_ordered_pass() {
        let sampled = RenderTarget::new(40, 20, false).unwrap();
        let image = Texture::rgba8(1, 1, &[255; 4], Sampler::default()).unwrap();
        let mut commands: Vec<_> = (0..6).map(|i| draw(None, false, i)).collect();
        for (i, command) in commands.iter_mut().enumerate() {
            let PreparedCommand::Draw(draw) = command else {
                unreachable!()
            };
            draw.blend = [BlendMode::Opaque, BlendMode::Alpha, BlendMode::Additive][i % 3];
            draw.lines = i % 2 == 0;
            draw.texture = match i % 3 {
                0 => None,
                1 => Some(image.clone()),
                _ => Some(sampled.texture.clone()),
            };
            draw.geometry.arena_index = i / 2;
        }
        assert_eq!(draw_run_len(&commands), 6);
        let runs = draw_runs(&commands);
        assert_eq!(runs.len(), 1);
        assert_eq!(runs[0], 0..6);
        for (i, command) in commands.iter().enumerate() {
            let PreparedCommand::Draw(draw) = command else {
                unreachable!()
            };
            assert_eq!(
                draw.blend,
                [BlendMode::Opaque, BlendMode::Alpha, BlendMode::Additive][i % 3]
            );
            assert_eq!(draw.lines, i % 2 == 0);
            assert_eq!(draw.geometry.arena_index, i / 2);
            assert_eq!(draw.geometry.range.matrix_offset, i as u32 * 256);
            assert_eq!(
                draw.geometry.range.vertices,
                i as u64 * 120..(i as u64 + 1) * 120
            );
            assert_eq!(
                draw.geometry.range.indices,
                i as u64 * 6..(i as u64 + 1) * 6
            );
            assert_eq!(
                draw.texture.as_ref().map(|texture| texture.id),
                match i % 3 {
                    0 => None,
                    1 => Some(image.id),
                    _ => Some(sampled.texture.id),
                }
            );
        }
    }

    #[test]
    fn grouping_keeps_real_arena_rollover_matrices_and_presentation_separate() {
        let mut list = DrawList::new(100, 50);
        let mesh = super::super::sprite2d::quad(Rect::new(1., 2., 3., 4.), Color::WHITE, None);
        for i in 0..3 {
            list.draw_mesh(
                &mesh,
                Mat4::from_translation(Vec3::X * i as f32),
                BlendMode::Alpha,
            );
        }
        let plan = FramePlan::new(
            &list,
            &mut super::super::text::TextRenderer::new().unwrap(),
            256,
            256,
            true,
        )
        .unwrap();
        assert_eq!(plan.arenas.len(), 4);
        let runs = draw_runs(&plan.commands);
        assert_eq!(runs.len(), 1);
        assert_eq!(runs[0], 0..3);
        for (i, command) in plan.commands.iter().enumerate() {
            let PreparedCommand::Draw(draw) = command else {
                unreachable!()
            };
            assert_eq!(draw.geometry.arena_index, i);
            assert_eq!(draw.geometry.range.matrix_offset, 0);
            assert_eq!(draw.geometry.range.vertices, 0..160);
            assert_eq!(draw.geometry.range.indices, 0..12);
            assert_eq!(draw.geometry.range.count, 6);
            let expected = super::super::arena::clip_matrix(
                Camera::screen(100, 50).view_projection,
                Mat4::from_translation(Vec3::X * i as f32),
            )
            .to_cols_array()
            .into_iter()
            .flat_map(f32::to_le_bytes)
            .collect::<Vec<_>>();
            assert_eq!(
                &plan.arenas[i].buffer_contents().unwrap()[2][..64],
                expected
            );
        }
        let present = plan.present.unwrap();
        assert_eq!(present.arena_index, 3);
        assert_eq!(present.range.matrix_offset, 0);
    }

    #[test]
    fn rejects_invalid_commands_before_encoding() {
        let mut list = DrawList::new(960, 540);
        list.camera(Camera {
            view_projection: Mat4::IDENTITY,
            target: Some(RenderTarget::new(64, 64, false).unwrap()),
            depth_test: true,
        });
        assert!(validate(&list, &wgpu::Limits::default())
            .unwrap_err()
            .contains("depth"));
        list.commands.clear();
        list.clear(Color::new(f32::NAN, 0., 0., 1.));
        assert!(validate(&list, &wgpu::Limits::default()).is_err());
    }
}
