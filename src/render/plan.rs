//! CPU-only preparation. Upload packing never reorders rendering or capture copies.
use super::{
    arena::{clip_matrix, DrawSlice, FrameArena},
    text::TextRenderer,
};
use crate::draw::{BlendMode, Camera, Color, Command, DrawList, Mesh, Rect, RenderTarget, Texture};
use glam::Mat4;
use std::path::PathBuf;

pub(crate) struct GeometrySlice {
    pub arena_index: usize,
    pub range: DrawSlice,
}
pub(crate) struct PreparedDraw {
    pub target: Option<RenderTarget>,
    pub depth_test: bool,
    pub texture: Option<Texture>,
    pub blend: BlendMode,
    pub lines: bool,
    pub geometry: GeometrySlice,
}
pub(crate) struct PreparedResident {
    pub target: Option<RenderTarget>,
    pub depth_test: bool,
    pub blend: BlendMode,
    pub index: usize,
}
pub(crate) enum PreparedCommand {
    Camera(Camera),
    Clear {
        target: Option<RenderTarget>,
        color: Color,
    },
    Draw(PreparedDraw),
    Resident(PreparedResident),
    Capture {
        target: Option<RenderTarget>,
        path: PathBuf,
    },
}
/// Consecutive draws may share a pass only while its attachments stay the same.
/// Camera commands, clears, and captures remain barriers even for the same target.
/// Pipeline, texture, and arena changes are rebound for each draw inside the pass.
pub(crate) fn draw_attachment(command: &PreparedCommand) -> Option<(Option<&RenderTarget>, bool)> {
    match command {
        PreparedCommand::Draw(draw) => Some((draw.target.as_ref(), draw.depth_test)),
        PreparedCommand::Resident(draw) => Some((draw.target.as_ref(), draw.depth_test)),
        _ => None,
    }
}
pub(crate) fn draw_run_len(commands: &[PreparedCommand]) -> usize {
    let Some((target, depth)) = commands.first().and_then(draw_attachment) else {
        return 0;
    };
    let id = target.map(|t| t.texture.id);
    commands
        .iter()
        .take_while(|command| {
            draw_attachment(command)
                .is_some_and(|(t, d)| t.map(|t| t.texture.id) == id && d == depth)
        })
        .count()
}
pub(crate) struct FramePlan {
    pub arenas: Vec<FrameArena>,
    pub residents: Vec<(crate::draw::resident::ResidentDraw, Mat4)>,
    matrix_alignment: u32,
    max_buffer_size: u64,
    pub commands: Vec<PreparedCommand>,
    pub present: Option<GeometrySlice>,
}
impl FramePlan {
    pub fn new(
        list: &DrawList,
        text: &mut TextRenderer,
        matrix_alignment: u32,
        max_buffer_size: u64,
        present: bool,
    ) -> Result<Self, String> {
        let mut plan = Self {
            arenas: vec![FrameArena::new(matrix_alignment, max_buffer_size)?],
            residents: Vec::new(),
            matrix_alignment,
            max_buffer_size,
            commands: Vec::new(),
            present: None,
        };
        let mut camera = Camera::screen(list.width, list.height);
        let mut commands = list.commands.as_slice();
        while let Some((command, following)) = commands.split_first() {
            commands = following;
            match command {
                Command::Camera(next) => {
                    camera = next.clone();
                    plan.commands.push(PreparedCommand::Camera(next.clone()));
                }
                Command::Clear(color) => plan.commands.push(PreparedCommand::Clear {
                    target: camera.target.clone(),
                    color: *color,
                }),
                Command::Mesh { mesh, model, blend } => {
                    plan.draw(&camera, mesh, *model, *blend, false)?
                }
                Command::Resident { draw, model, blend } => {
                    if !draw.mesh().indices().is_empty() {
                        let index = plan.residents.len();
                        plan.residents
                            .push((draw.clone(), clip_matrix(camera.view_projection, *model)));
                        plan.commands
                            .push(PreparedCommand::Resident(PreparedResident {
                                target: camera.target.clone(),
                                depth_test: camera.depth_test,
                                blend: *blend,
                                index,
                            }));
                    }
                }
                Command::Lines { lines, model } => {
                    let (consumed, batches) =
                        super::lines::adjacent_batches(lines, *model, commands);
                    commands = &commands[consumed..];
                    for (vertices, indices) in batches {
                        plan.draw(
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
                Command::Rect { rect, color } => plan.draw(
                    &screen_camera(list, &camera),
                    &super::sprite2d::quad(*rect, *color, None),
                    Mat4::IDENTITY,
                    BlendMode::Alpha,
                    false,
                )?,
                Command::Sprite {
                    texture,
                    destination,
                    tint,
                } => plan.draw(
                    &screen_camera(list, &camera),
                    &super::sprite2d::quad(*destination, *tint, Some(texture.clone())),
                    Mat4::IDENTITY,
                    BlendMode::Alpha,
                    false,
                )?,
                Command::Text {
                    text: value,
                    baseline,
                    size,
                    color,
                } => {
                    let screen = screen_camera(list, &camera);
                    text.for_each_quad(value, *baseline, *size, *color, |vertices, texture| {
                        plan.draw_text_quad(&screen, vertices, texture)
                    })?;
                }
                Command::Capture { target, path } => plan.commands.push(PreparedCommand::Capture {
                    target: target.clone(),
                    path: path.clone(),
                }),
            }
        }
        if present {
            let screen = Camera::screen(list.width, list.height);
            let quad = super::sprite2d::quad(
                Rect::new(0., 0., list.width as f32, list.height as f32),
                Color::WHITE,
                None,
            );
            plan.present = Some(plan.append(
                &quad.vertices,
                &quad.indices,
                clip_matrix(screen.view_projection, Mat4::IDENTITY),
            )?);
        }
        Ok(plan)
    }
    fn append(
        &mut self,
        vertices: &[crate::draw::Vertex],
        indices: &[u16],
        transform: Mat4,
    ) -> Result<GeometrySlice, String> {
        let last = self.arenas.len() - 1;
        if let Some(range) = self.arenas[last].try_append(vertices, indices, transform)? {
            return Ok(GeometrySlice {
                arena_index: last,
                range,
            });
        }
        // Capacity is not a frame error: preserve every individually valid draw
        // by starting another bounded immutable chunk. A single oversized draw
        // remains an explicit error, as in the original per-draw upload path.
        let mut next = FrameArena::new(self.matrix_alignment, self.max_buffer_size)?;
        let range = next
            .try_append(vertices, indices, transform)?
            .ok_or("mesh exceeds adapter buffer limit")?;
        self.arenas.push(next);
        Ok(GeometrySlice {
            arena_index: last + 1,
            range,
        })
    }
    fn draw_text_quad(
        &mut self,
        camera: &Camera,
        vertices: &[crate::draw::Vertex; 4],
        texture: &Texture,
    ) -> Result<(), String> {
        let geometry = self.append(
            vertices,
            &super::text::QUAD_INDICES,
            clip_matrix(camera.view_projection, Mat4::IDENTITY),
        )?;
        self.commands.push(PreparedCommand::Draw(PreparedDraw {
            target: camera.target.clone(),
            depth_test: camera.depth_test,
            texture: Some(texture.clone()),
            blend: BlendMode::Alpha,
            lines: false,
            geometry,
        }));
        Ok(())
    }

    fn draw(
        &mut self,
        camera: &Camera,
        mesh: &Mesh,
        model: Mat4,
        blend: BlendMode,
        lines: bool,
    ) -> Result<(), String> {
        if mesh.indices.is_empty() {
            return Ok(());
        }
        let geometry = self.append(
            &mesh.vertices,
            &mesh.indices,
            clip_matrix(camera.view_projection, model),
        )?;
        self.commands.push(PreparedCommand::Draw(PreparedDraw {
            target: camera.target.clone(),
            depth_test: camera.depth_test,
            texture: mesh.texture.clone(),
            blend,
            lines,
            geometry,
        }));
        Ok(())
    }
}
fn screen_camera(list: &DrawList, camera: &Camera) -> Camera {
    let (width, height) = camera
        .target
        .as_ref()
        .map_or((list.width, list.height), |target| {
            (target.texture.width, target.texture.height)
        });
    let mut screen = Camera::screen(width, height);
    screen.target = camera.target.clone();
    screen
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::draw::{Line, Vertex};
    use glam::{Vec2, Vec3};
    #[test]
    fn resident_draws_skip_vertex_arenas_and_preserve_mixed_capture_barriers() {
        use crate::draw::resident::{ResidentDraw, ResidentMesh, RigidVertex, Vertices};
        let source = mesh();
        let resident = ResidentMesh::new(
            Vertices::Rigid(
                source
                    .vertices
                    .iter()
                    .map(|v| RigidVertex {
                        position: v.position.to_array(),
                        uv: v.uv.to_array(),
                        normal: [0., 1., 0.],
                    })
                    .collect(),
            ),
            source.indices.clone(),
            None,
        )
        .unwrap();
        let draw = ResidentDraw::new(
            resident,
            Mat4::IDENTITY,
            crate::scene_lighting::SceneLighting::range(),
            Color::WHITE,
            1.,
            None,
        )
        .unwrap();
        let mut list = DrawList::new(64, 64);
        list.draw_resident(draw.clone(), Mat4::IDENTITY, BlendMode::Alpha);
        let plan = prepare(&list, false);
        assert!(plan.arenas.iter().all(|a| a.buffer_contents().is_none()));
        assert_eq!(plan.residents.len(), 1);
        list.draw_mesh(&source, Mat4::IDENTITY, BlendMode::Alpha);
        list.capture_png(None, "middle.png");
        list.draw_resident(draw, Mat4::IDENTITY, BlendMode::Alpha);
        let plan = prepare(&list, false);
        assert_eq!(draw_run_len(&plan.commands), 2);
        assert!(matches!(plan.commands[2], PreparedCommand::Capture { .. }));
        assert_eq!(draw_run_len(&plan.commands[3..]), 1);
        assert_eq!(plan.residents.len(), 2);
    }

    fn mesh() -> Mesh {
        Mesh {
            vertices: [Vec3::ZERO, Vec3::X, Vec3::Y]
                .map(|p| Vertex::new2(p, Vec2::ZERO, Color::WHITE))
                .to_vec(),
            indices: vec![0, 1, 2],
            texture: None,
        }
    }
    fn prepare(list: &DrawList, present: bool) -> FramePlan {
        FramePlan::new(
            list,
            &mut TextRenderer::new().unwrap(),
            256,
            16 * 1024 * 1024,
            present,
        )
        .unwrap()
    }
    #[test]
    fn captures_clears_targets_and_blends_stay_in_exact_order() {
        let mut list = DrawList::new(100, 50);
        let target = RenderTarget::new(40, 20, true).unwrap();
        let mut camera = Camera::screen(40, 20);
        camera.target = Some(target.clone());
        camera.depth_test = true;
        list.camera(camera.clone());
        list.draw_mesh(&mesh(), Mat4::IDENTITY, BlendMode::Alpha);
        list.commands.push(Command::Capture {
            target: Some(target.clone()),
            path: "before.png".into(),
        });
        list.clear(Color::TRANSPARENT);
        list.draw_mesh(
            &mesh(),
            Mat4::from_translation(Vec3::X),
            BlendMode::Additive,
        );
        list.camera(Camera::screen(100, 50));
        list.draw_mesh(&mesh(), Mat4::IDENTITY, BlendMode::Opaque);
        list.commands.push(Command::Capture {
            target: None,
            path: "after.png".into(),
        });
        let plan = prepare(&list, true);
        let order: Vec<_> = plan
            .commands
            .iter()
            .map(|c| match c {
                PreparedCommand::Camera(_) => "camera",
                PreparedCommand::Clear { .. } => "clear",
                PreparedCommand::Draw(_) => "draw",
                PreparedCommand::Resident(_) => "resident",
                PreparedCommand::Capture { .. } => "capture",
            })
            .collect();
        assert_eq!(
            order,
            ["camera", "draw", "capture", "clear", "draw", "camera", "draw", "capture"]
        );
        let draws: Vec<_> = plan
            .commands
            .iter()
            .filter_map(|c| {
                if let PreparedCommand::Draw(d) = c {
                    Some(d)
                } else {
                    None
                }
            })
            .collect();
        assert_eq!(
            draws
                .iter()
                .map(|d| d.geometry.range.matrix_offset)
                .collect::<Vec<_>>(),
            [0, 256, 512]
        );
        assert_eq!(
            draws[0].target.as_ref().unwrap().texture.id,
            target.texture.id
        );
        assert!(draws[0].depth_test);
        assert_eq!(draws[0].blend, BlendMode::Alpha);
        assert_eq!(draws[1].blend, BlendMode::Additive);
        assert_eq!(draws[2].blend, BlendMode::Opaque);
        assert!(draws[2].target.is_none());
        assert!(!draws[2].depth_test);
        assert!(
            matches!(&plan.commands[2],PreparedCommand::Capture{target:Some(t),path} if t.texture.id==target.texture.id && path==std::path::Path::new("before.png"))
        );
        assert!(
            matches!(&plan.commands[7],PreparedCommand::Capture{target:None,path} if path==std::path::Path::new("after.png"))
        );
        assert_eq!(plan.present.as_ref().unwrap().range.matrix_offset, 768);
        let matrices = plan.arenas[0].buffer_contents().unwrap()[2];
        let expected = clip_matrix(camera.view_projection, Mat4::from_translation(Vec3::X))
            .to_cols_array()
            .into_iter()
            .flat_map(f32::to_le_bytes)
            .collect::<Vec<_>>();
        assert_eq!(&matrices[256..320], expected);
    }
    #[test]
    fn capture_is_still_a_line_batch_barrier() {
        let mut list = DrawList::new(100, 50);
        let line = Line {
            start: Vec3::ZERO,
            end: Vec3::X,
            color: Color::WHITE,
        };
        list.draw_lines(&[line], Mat4::IDENTITY);
        list.draw_lines(&[line], Mat4::IDENTITY);
        list.commands.push(Command::Capture {
            target: None,
            path: "lines.png".into(),
        });
        list.draw_lines(&[line], Mat4::IDENTITY);
        let plan = prepare(&list, false);
        assert_eq!(plan.commands.len(), 3);
        assert!(
            matches!(&plan.commands[0],PreparedCommand::Draw(d) if d.lines && d.geometry.range.count==4)
        );
        assert!(matches!(&plan.commands[1], PreparedCommand::Capture { .. }));
        assert!(
            matches!(&plan.commands[2],PreparedCommand::Draw(d) if d.lines && d.geometry.range.count==2 && d.geometry.range.matrix_offset==256)
        );
    }
    #[test]
    fn text_remains_per_glyph_but_uses_only_three_frame_buffers() {
        let mut list = DrawList::new(960, 540);
        list.draw_text("A B A", Vec2::new(1., 20.), 16., Color::WHITE);
        let plan = prepare(&list, false);
        assert_eq!(plan.commands.len(), 3);
        assert_eq!(plan.arenas[0].buffer_contents().unwrap().len(), 3);
        let draws: Vec<_> = plan
            .commands
            .iter()
            .filter_map(|c| {
                if let PreparedCommand::Draw(d) = c {
                    Some(d)
                } else {
                    None
                }
            })
            .collect();
        assert_eq!(
            draws
                .iter()
                .map(|d| d.geometry.range.matrix_offset)
                .collect::<Vec<_>>(),
            [0, 256, 512]
        );
        assert_eq!(
            draws[0].texture.as_ref().unwrap().id,
            draws[2].texture.as_ref().unwrap().id
        );
        assert_ne!(
            draws[0].texture.as_ref().unwrap().id,
            draws[1].texture.as_ref().unwrap().id
        );
    }

    #[test]
    fn streamed_text_packs_fixed_positions_and_keeps_capture_barrier() {
        let mut list = DrawList::new(960, 540);
        list.draw_text("Ag ", Vec2::new(10., 20.), 16., Color::WHITE);
        list.capture_png(None, "text-prefix.png");
        list.draw_text("A", Vec2::new(10., 20.), 16., Color::WHITE);
        let plan = prepare(&list, false);
        assert_eq!(plan.commands.len(), 4);
        assert!(matches!(plan.commands[2], PreparedCommand::Capture { .. }));
        assert_eq!(draw_run_len(&plan.commands), 2);
        assert_eq!(draw_run_len(&plan.commands[3..]), 1);
        let [vertices, indices, _] = plan.arenas[0].buffer_contents().unwrap();
        let expected_positions = [
            (11., 12.),
            (17., 12.),
            (17., 20.),
            (11., 20.),
            (18., 14.),
            (23., 14.),
            (23., 23.),
            (18., 23.),
            (11., 12.),
            (17., 12.),
            (17., 20.),
            (11., 20.),
        ];
        assert_eq!(vertices.len(), expected_positions.len() * 40);
        for (packed, (x, y)) in vertices.as_chunks::<40>().0.iter().zip(expected_positions) {
            let float = |offset| f32::from_le_bytes(packed[offset..offset + 4].try_into().unwrap());
            assert_eq!([float(0), float(4), float(8)], [x, y, 0.]);
            assert_eq!(&packed[20..24], &[255; 4]);
        }
        let expected_indices: Vec<_> = [0_u16, 1, 2, 0, 2, 3]
            .into_iter()
            .cycle()
            .take(18)
            .flat_map(u16::to_le_bytes)
            .collect();
        assert_eq!(indices, expected_indices);
    }

    #[test]
    fn streamed_text_obeys_upload_chunk_limits_and_failure_is_not_a_plan() {
        let mut list = DrawList::new(960, 540);
        list.draw_text("AB", Vec2::ZERO, 16., Color::WHITE);
        let plan =
            FramePlan::new(&list, &mut TextRenderer::new().unwrap(), 64, 256, false).unwrap();
        assert_eq!(plan.arenas.len(), 2);
        assert_eq!(plan.commands.len(), 2);
        for (index, command) in plan.commands.iter().enumerate() {
            let PreparedCommand::Draw(draw) = command else {
                panic!("expected text draw")
            };
            assert_eq!(draw.geometry.arena_index, index);
            assert_eq!(draw.geometry.range.vertices, 0..160);
            assert_eq!(draw.geometry.range.count, 6);
        }
        assert!(FramePlan::new(&list, &mut TextRenderer::new().unwrap(), 64, 128, false).is_err());
        list.draw_text("invalid later text", Vec2::ZERO, f32::NAN, Color::WHITE);
        assert!(FramePlan::new(&list, &mut TextRenderer::new().unwrap(), 64, 256, false).is_err());
    }

    #[test]
    fn screen_draws_use_target_extent_without_world_depth_or_matrix() {
        let mut list = DrawList::new(100, 50);
        let target = RenderTarget::new(40, 20, true).unwrap();
        let camera = Camera {
            view_projection: Mat4::from_scale(Vec3::splat(7.)),
            target: Some(target.clone()),
            depth_test: true,
        };
        let texture = Texture::rgba8(1, 1, &[255; 4], crate::draw::Sampler::default()).unwrap();
        list.camera(camera);
        list.draw_rect(Rect::new(1., 2., 3., 4.), Color::WHITE);
        list.draw_texture(&texture, Rect::new(1., 2., 3., 4.), Color::WHITE);
        list.draw_text("A", Vec2::new(1., 10.), 16., Color::WHITE);
        let plan = prepare(&list, false);
        let draws: Vec<_> = plan
            .commands
            .iter()
            .filter_map(|command| {
                if let PreparedCommand::Draw(draw) = command {
                    Some(draw)
                } else {
                    None
                }
            })
            .collect();
        assert_eq!(draws.len(), 3);
        let expected = clip_matrix(Camera::screen(40, 20).view_projection, Mat4::IDENTITY)
            .to_cols_array()
            .into_iter()
            .flat_map(f32::to_le_bytes)
            .collect::<Vec<_>>();
        let matrices = plan.arenas[0].buffer_contents().unwrap()[2];
        for (i, draw) in draws.iter().enumerate() {
            assert_eq!(draw.target.as_ref().unwrap().texture.id, target.texture.id);
            assert!(!draw.depth_test);
            assert!(!draw.lines);
            assert_eq!(draw.geometry.range.count, 6);
            assert_eq!(draw.geometry.range.matrix_offset, i as u32 * 256);
            assert_eq!(&matrices[i * 256..i * 256 + 64], expected);
        }
        assert!(draws[0].texture.is_none());
        assert_eq!(draws[1].texture.as_ref().unwrap().id, texture.id);
        assert!(draws[2].texture.is_some());
    }
    #[test]
    fn adjacent_line_limit_keeps_local_indices_in_distinct_arena_slices() {
        let mut list = DrawList::new(100, 50);
        let line = Line {
            start: Vec3::ZERO,
            end: Vec3::X,
            color: Color::WHITE,
        };
        list.draw_lines(&vec![line; 32769], Mat4::IDENTITY);
        let plan = prepare(&list, false);
        let [PreparedCommand::Draw(first), PreparedCommand::Draw(second)] =
            plan.commands.as_slice()
        else {
            panic!("line limit must make two draws")
        };
        assert_eq!(first.geometry.range.vertices, 0..65536 * 40);
        assert_eq!(first.geometry.range.indices, 0..65536 * 2);
        assert_eq!(second.geometry.range.vertices, 65536 * 40..65538 * 40);
        assert_eq!(second.geometry.range.indices, 65536 * 2..65538 * 2);
        assert_eq!(second.geometry.range.count, 2);
        assert_eq!(second.geometry.range.matrix_offset, 256);
        assert_eq!(
            &plan.arenas[0].buffer_contents().unwrap()[1][65536 * 2..],
            &[0, 0, 1, 0]
        );
    }
    #[test]
    fn vertex_capacity_rolls_over_without_rebasing_local_indices() {
        let mut list = DrawList::new(100, 50);
        for _ in 0..3 {
            list.draw_mesh(&mesh(), Mat4::IDENTITY, BlendMode::Alpha);
        }
        let plan =
            FramePlan::new(&list, &mut TextRenderer::new().unwrap(), 64, 256, false).unwrap();
        assert_eq!(plan.arenas.len(), 2);
        let draws: Vec<_> = plan
            .commands
            .iter()
            .filter_map(|c| {
                if let PreparedCommand::Draw(d) = c {
                    Some(d)
                } else {
                    None
                }
            })
            .collect();
        assert_eq!(
            draws
                .iter()
                .map(|d| d.geometry.arena_index)
                .collect::<Vec<_>>(),
            [0, 0, 1]
        );
        assert_eq!(draws[1].geometry.range.vertices, 120..240);
        assert_eq!(draws[1].geometry.range.indices, 6..12);
        assert_eq!(draws[1].geometry.range.matrix_offset, 64);
        assert_eq!(draws[2].geometry.range.vertices, 0..120);
        assert_eq!(draws[2].geometry.range.indices, 0..6);
        assert_eq!(draws[2].geometry.range.matrix_offset, 0);
        assert_eq!(
            plan.arenas[1].buffer_contents().unwrap()[1],
            &[0, 0, 1, 0, 2, 0]
        );
    }
    #[test]
    fn index_capacity_rolls_over_even_when_vertex_and_matrix_bytes_fit() {
        let mut list = DrawList::new(100, 50);
        let mesh = Mesh {
            vertices: vec![mesh().vertices[0]],
            indices: vec![0; 99],
            texture: None,
        };
        for _ in 0..2 {
            list.draw_mesh(&mesh, Mat4::IDENTITY, BlendMode::Alpha);
        }
        let plan =
            FramePlan::new(&list, &mut TextRenderer::new().unwrap(), 64, 256, false).unwrap();
        assert_eq!(plan.arenas.len(), 2);
        for (i, command) in plan.commands.iter().enumerate() {
            let PreparedCommand::Draw(draw) = command else {
                panic!("expected draw")
            };
            assert_eq!(draw.geometry.arena_index, i);
            assert_eq!(draw.geometry.range.indices, 0..198);
            assert_eq!(draw.geometry.range.vertices, 0..40);
            assert_eq!(draw.geometry.range.matrix_offset, 0);
        }
    }
    #[test]
    fn matrix_capacity_rollover_preserves_capture_order_and_previous_bytes() {
        let mut list = DrawList::new(100, 50);
        list.draw_mesh(&mesh(), Mat4::IDENTITY, BlendMode::Alpha);
        list.commands.push(Command::Capture {
            target: None,
            path: "first.png".into(),
        });
        list.clear(Color::WHITE);
        list.draw_mesh(
            &mesh(),
            Mat4::from_translation(Vec3::X),
            BlendMode::Additive,
        );
        let plan =
            FramePlan::new(&list, &mut TextRenderer::new().unwrap(), 256, 256, false).unwrap();
        assert_eq!(plan.arenas.len(), 2);
        assert!(matches!(&plan.commands[0],PreparedCommand::Draw(d) if d.geometry.arena_index==0));
        assert!(
            matches!(&plan.commands[1],PreparedCommand::Capture{path,..} if path==std::path::Path::new("first.png"))
        );
        assert!(matches!(&plan.commands[2], PreparedCommand::Clear { .. }));
        assert!(
            matches!(&plan.commands[3],PreparedCommand::Draw(d) if d.geometry.arena_index==1 && d.geometry.range.matrix_offset==0 && d.blend==BlendMode::Additive)
        );
        assert_eq!(
            plan.arenas[0].buffer_contents().unwrap()[0],
            plan.arenas[1].buffer_contents().unwrap()[0]
        );
        assert_ne!(
            plan.arenas[0].buffer_contents().unwrap()[2],
            plan.arenas[1].buffer_contents().unwrap()[2]
        );
        assert_eq!(
            plan.arenas
                .iter()
                .map(|a| a.buffer_contents().unwrap().len())
                .sum::<usize>(),
            6
        );
    }
    #[test]
    fn presentation_can_roll_over_into_its_own_immutable_chunk() {
        let mut list = DrawList::new(100, 50);
        list.draw_mesh(&mesh(), Mat4::IDENTITY, BlendMode::Alpha);
        let plan = FramePlan::new(&list, &mut TextRenderer::new().unwrap(), 64, 256, true).unwrap();
        assert_eq!(plan.arenas.len(), 2);
        let present = plan.present.unwrap();
        assert_eq!(present.arena_index, 1);
        assert_eq!(present.range.vertices, 0..160);
        assert_eq!(present.range.indices, 0..12);
        assert_eq!(present.range.matrix_offset, 0);
    }
    #[test]
    fn individually_oversized_or_malformed_draw_still_fails() {
        let mut list = DrawList::new(100, 50);
        let mut too_big = mesh();
        too_big.vertices.resize(7, too_big.vertices[0]);
        list.draw_mesh(&too_big, Mat4::IDENTITY, BlendMode::Alpha);
        assert!(
            FramePlan::new(&list, &mut TextRenderer::new().unwrap(), 64, 256, false)
                .err()
                .unwrap()
                .contains("adapter buffer limit")
        );
        list.commands.clear();
        let mut invalid = mesh();
        invalid.indices[0] = 3;
        list.draw_mesh(&invalid, Mat4::IDENTITY, BlendMode::Alpha);
        assert!(
            FramePlan::new(&list, &mut TextRenderer::new().unwrap(), 64, 256, false)
                .err()
                .unwrap()
                .contains("invalid frame geometry")
        );
    }
    #[test]
    fn clear_capture_only_headless_frame_allocates_no_geometry() {
        let mut list = DrawList::new(100, 50);
        list.clear(Color::WHITE);
        list.commands.push(Command::Capture {
            target: None,
            path: "clear.png".into(),
        });
        let plan = prepare(&list, false);
        assert!(plan.arenas[0].buffer_contents().is_none());
        assert!(plan.present.is_none());
        assert_eq!(plan.commands.len(), 2);
    }
}
