//! Commands are encoded in list order, including copies at mid-frame capture checkpoints.
use super::{
    capture::{CaptureEncoding, Readback},
    mesh::{clip_matrix, FragmentKind},
    target::{self, GpuTexture},
    WgpuRenderer,
};
use crate::draw::{
    BlendMode, Camera, Color, Command, DrawList, FrameOutput, Mesh, RenderTarget, TextureSource,
};
use glam::Mat4;
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
        let mut encoder = self
            .gpu
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                label: Some("ordered presentation frame"),
            });
        clear(&mut encoder, &self.main, Color::TRANSPARENT);
        let mut camera = Camera::screen(list.width, list.height);
        let mut readbacks = Vec::new();
        let mut commands = list.commands.as_slice();
        while let Some((command, following)) = commands.split_first() {
            commands = following;
            match command {
                Command::Camera(next) => {
                    if let Some(target) = &next.target {
                        self.texture(&target.texture)?;
                    }
                    camera = next.clone();
                }
                Command::Clear(color) => {
                    let output = self.output(camera.target.as_ref())?;
                    clear(&mut encoder, &output, *color);
                }
                Command::Mesh { mesh, model, blend } => {
                    self.draw_mesh(&mut encoder, &camera, mesh, *model, *blend, false)?
                }
                Command::Lines { lines, model } => {
                    let (consumed, batches) =
                        super::lines::adjacent_batches(lines, *model, commands);
                    commands = &commands[consumed..];
                    for (vertices, indices) in batches {
                        self.draw_mesh(
                            &mut encoder,
                            &camera,
                            &Mesh {
                                vertices,
                                indices,
                                texture: None,
                            },
                            *model,
                            BlendMode::Alpha,
                            true,
                        )?;
                    }
                }
                Command::Rect { rect, color } => {
                    let screen = self.screen_camera(camera.target.as_ref())?;
                    self.draw_mesh(
                        &mut encoder,
                        &screen,
                        &super::sprite2d::quad(*rect, *color, None),
                        Mat4::IDENTITY,
                        BlendMode::Alpha,
                        false,
                    )?;
                }
                Command::Sprite {
                    texture,
                    destination,
                    tint,
                } => {
                    let screen = self.screen_camera(camera.target.as_ref())?;
                    self.draw_mesh(
                        &mut encoder,
                        &screen,
                        &super::sprite2d::quad(*destination, *tint, Some(texture.clone())),
                        Mat4::IDENTITY,
                        BlendMode::Alpha,
                        false,
                    )?;
                }
                Command::Text {
                    text,
                    baseline,
                    size,
                    color,
                } => {
                    let meshes = self.text.meshes(text, *baseline, *size, *color)?;
                    let screen = self.screen_camera(camera.target.as_ref())?;
                    for mesh in meshes {
                        self.draw_mesh(
                            &mut encoder,
                            &screen,
                            &mesh,
                            Mat4::IDENTITY,
                            BlendMode::Alpha,
                            false,
                        )?;
                    }
                }
                Command::Capture { target, path } => {
                    let output = self.output(target.as_ref())?;
                    readbacks.push(Readback::encode(
                        &self.gpu.device,
                        &mut encoder,
                        &output.texture,
                        path.clone(),
                        CaptureEncoding::for_target(target.as_ref()),
                    )?);
                }
            }
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
            let screen = Camera::screen(list.width, list.height);
            let mesh = super::sprite2d::quad(
                crate::draw::Rect::new(0., 0., list.width as f32, list.height as f32),
                Color::WHITE,
                None,
            );
            let geometry = self.pipelines.geometry(
                &self.gpu.device,
                &mesh.vertices,
                &mesh.indices,
                clip_matrix(screen.view_projection, Mat4::IDENTITY),
            );
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
            issue(&mut pass, &pipeline, &geometry, &self.main.binding);
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
    fn screen_camera(&mut self, target: Option<&RenderTarget>) -> Result<Camera, String> {
        let output = self.output(target)?;
        let mut camera = Camera::screen(output.descriptor.width, output.descriptor.height);
        camera.target = target.cloned();
        Ok(camera)
    }
    fn draw_mesh(
        &mut self,
        encoder: &mut wgpu::CommandEncoder,
        camera: &Camera,
        mesh: &Mesh,
        model: Mat4,
        blend: BlendMode,
        lines: bool,
    ) -> Result<(), String> {
        if mesh.indices.is_empty() {
            return Ok(());
        }
        let output = self.output(camera.target.as_ref())?;
        let texture = match &mesh.texture {
            Some(texture) => self.texture(texture)?,
            None => self.white.clone(),
        };
        if Arc::ptr_eq(&output, &texture) {
            return Err("cannot sample the current render target while drawing into it".into());
        }
        if camera.depth_test && output.depth.is_none() {
            return Err("depth-enabled camera requires a target with depth storage".into());
        }
        let transform = clip_matrix(camera.view_projection, model);
        if !transform.is_finite() {
            return Err("camera-model transform overflow".into());
        }
        let geometry =
            self.pipelines
                .geometry(&self.gpu.device, &mesh.vertices, &mesh.indices, transform);
        let pipeline = self.pipelines.pipeline(
            &self.gpu.device,
            target::COLOR_FORMAT,
            camera.depth_test,
            lines,
            blend,
            FragmentKind::for_source(&texture.descriptor.source, blend),
        );
        let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("ordered draw"),
            color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                view: &output.view,
                depth_slice: None,
                resolve_target: None,
                ops: wgpu::Operations {
                    load: wgpu::LoadOp::Load,
                    store: wgpu::StoreOp::Store,
                },
            })],
            depth_stencil_attachment: if camera.depth_test {
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
        issue(&mut pass, &pipeline, &geometry, &texture.binding);
        Ok(())
    }
}
fn issue(
    pass: &mut wgpu::RenderPass<'_>,
    pipeline: &wgpu::RenderPipeline,
    geometry: &super::mesh::Geometry,
    texture: &wgpu::BindGroup,
) {
    pass.set_pipeline(pipeline);
    pass.set_bind_group(0, &geometry.transform, &[]);
    pass.set_bind_group(1, texture, &[]);
    pass.set_vertex_buffer(0, geometry.vertices.slice(..));
    pass.set_index_buffer(geometry.indices.slice(..), wgpu::IndexFormat::Uint16);
    pass.draw_indexed(0..geometry.count, 0, 0..1);
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
