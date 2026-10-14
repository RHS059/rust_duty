//! Adjacent line commands share uploads/passes without changing order or state.
use crate::draw::{Command, Line, Vertex};
use glam::{Mat4, Vec2};

const MAX_LINES_PER_BATCH: usize = 32768;

/// Include only the immediately following Lines commands with bit-identical
/// model components. Every other command is a barrier, including a redundant
/// camera selection or capture. Return the number of following commands taken.
pub(crate) fn adjacent_batches<'a>(
    first: &'a [Line],
    model: Mat4,
    following: &'a [Command],
) -> (usize, impl Iterator<Item = (Vec<Vertex>, Vec<u16>)> + 'a) {
    let model_bits = model.to_cols_array().map(f32::to_bits);
    let consumed = following
        .iter()
        .take_while(|command| {
            matches!(command, Command::Lines { model, .. }
                if model.to_cols_array().map(f32::to_bits) == model_bits)
        })
        .count();
    let lines = first.iter().chain(following[..consumed].iter().flat_map(
        |command| match command {
            Command::Lines { lines, .. } => lines.iter(),
            _ => unreachable!("an adjacent line run cannot contain a state barrier"),
        },
    ));
    (consumed, batches(lines))
}

fn batches<'a>(
    lines: impl Iterator<Item = &'a Line> + 'a,
) -> impl Iterator<Item = (Vec<Vertex>, Vec<u16>)> + 'a {
    let mut lines = lines.peekable();
    std::iter::from_fn(move || {
        lines.peek()?;
        let vertices: Vec<_> = lines
            .by_ref()
            .take(MAX_LINES_PER_BATCH)
            .flat_map(|line| {
                [
                    Vertex::new2(line.start, Vec2::ZERO, line.color),
                    Vertex::new2(line.end, Vec2::ZERO, line.color),
                ]
            })
            .collect();
        let indices = (0..vertices.len()).map(|index| index as u16).collect();
        Some((vertices, indices))
    })
}
#[cfg(test)]
mod tests {
    use super::*;
    use crate::draw::{BlendMode, Camera, Color, Mesh, Rect, RenderTarget, Sampler, Texture};
    use glam::{Vec3, Vec4};

    fn line(value: f32) -> Line {
        Line {
            start: Vec3::new(value, 2., -3.),
            end: Vec3::new(4., -value, 6.),
            color: Color::new(value * 0.1, 0.5, 0.75, 0.25),
        }
    }
    fn command(lines: Vec<Line>, model: Mat4) -> Command {
        Command::Lines { lines, model }
    }
    fn verify_geometry(vertices: &[Vertex], indices: &[u16], lines: &[Line]) {
        assert_eq!(vertices.len(), lines.len() * 2);
        assert_eq!(
            indices,
            &(0..vertices.len()).map(|i| i as u16).collect::<Vec<_>>()
        );
        for (pair, line) in vertices.as_chunks::<2>().0.iter().zip(lines) {
            assert_eq!(pair[0].position, line.start);
            assert_eq!(pair[1].position, line.end);
            for vertex in pair {
                assert_eq!(vertex.uv, Vec2::ZERO);
                assert_eq!(vertex.normal, Vec4::ZERO);
                assert_eq!(vertex.color, <[u8; 4]>::from(line.color));
            }
        }
    }

    #[test]
    fn adjacent_line_commands_preserve_geometry_color_and_order() {
        let model = Mat4::from_translation(Vec3::new(4., 5., 6.));
        let first = [line(1.), line(2.)];
        let following = [
            command(vec![], model),
            command(vec![line(3.)], model),
            command(vec![line(4.), line(5.)], model),
        ];
        let (consumed, batches) = adjacent_batches(&first, model, &following);
        assert_eq!(consumed, following.len());
        let batches: Vec<_> = batches.collect();
        assert_eq!(batches.len(), 1);
        verify_geometry(
            &batches[0].0,
            &batches[0].1,
            &[line(1.), line(2.), line(3.), line(4.), line(5.)],
        );
    }

    #[test]
    fn every_non_line_command_is_a_barrier_even_when_it_draws_nothing() {
        let mut target_camera = Camera::screen(64, 64);
        target_camera.target = Some(RenderTarget::new(64, 64, true).unwrap());
        target_camera.depth_test = true;
        let texture = Texture::rgba8(1, 1, &[255; 4], Sampler::default()).unwrap();
        for barrier in [
            Command::Camera(Camera::screen(64, 64)),
            Command::Camera(target_camera),
            Command::Clear(Color::TRANSPARENT),
            Command::Mesh {
                mesh: Mesh::default(),
                model: Mat4::IDENTITY,
                blend: BlendMode::Alpha,
            },
            Command::Rect {
                rect: Rect::new(0., 0., 0., 0.),
                color: Color::TRANSPARENT,
            },
            Command::Sprite {
                texture,
                destination: Rect::new(0., 0., 1., 1.),
                tint: Color::WHITE,
            },
            Command::Text {
                text: String::new(),
                baseline: Vec2::ZERO,
                size: 16.,
                color: Color::WHITE,
            },
            Command::Capture {
                target: None,
                path: "ordered-checkpoint.png".into(),
            },
        ] {
            let first = [line(1.)];
            let following = [
                command(vec![line(2.)], Mat4::IDENTITY),
                barrier,
                command(vec![line(3.)], Mat4::IDENTITY),
            ];
            let (consumed, batches) = adjacent_batches(&first, Mat4::IDENTITY, &following);
            assert_eq!(consumed, 1, "must stop before {:?}", following[1]);
            let batches: Vec<_> = batches.collect();
            assert_eq!(batches.len(), 1);
            verify_geometry(&batches[0].0, &batches[0].1, &[line(1.), line(2.)]);
        }
    }

    #[test]
    fn model_components_must_be_bit_identical_including_signed_zero() {
        let first = [line(1.)];
        let mut signed_zero = Mat4::IDENTITY.to_cols_array();
        signed_zero[1] = -0.;
        let mut one_ulp = Mat4::IDENTITY.to_cols_array();
        one_ulp[0] = f32::from_bits(1_f32.to_bits() + 1);
        for model in [
            Mat4::from_cols_array(&signed_zero),
            Mat4::from_cols_array(&one_ulp),
            Mat4::from_translation(Vec3::X),
        ] {
            let following = [
                command(vec![line(2.)], model),
                command(vec![line(3.)], Mat4::IDENTITY),
            ];
            let (consumed, batches) = adjacent_batches(&first, Mat4::IDENTITY, &following);
            assert_eq!(consumed, 0);
            let batches: Vec<_> = batches.collect();
            assert_eq!(batches.len(), 1);
            verify_geometry(&batches[0].0, &batches[0].1, &first);
        }
    }

    #[test]
    fn empty_maximum_and_max_plus_one_runs_split_without_wrapping_indices() {
        for count in [0, 1, MAX_LINES_PER_BATCH, MAX_LINES_PER_BATCH + 1] {
            let lines = vec![line(1.); count];
            let split = count / 2;
            let following = [
                command(vec![], Mat4::IDENTITY),
                command(lines[split..].to_vec(), Mat4::IDENTITY),
            ];
            let (consumed, batches) = adjacent_batches(&lines[..split], Mat4::IDENTITY, &following);
            assert_eq!(consumed, following.len());
            let batches: Vec<_> = batches.collect();
            assert_eq!(batches.len(), count.div_ceil(MAX_LINES_PER_BATCH));
            for ((vertices, indices), expected) in
                batches.iter().zip(lines.chunks(MAX_LINES_PER_BATCH))
            {
                verify_geometry(vertices, indices, expected);
            }
        }
    }

    #[test]
    fn range_grid_recording_keeps_all_130_lines_in_one_batch() {
        use crate::draw::facade;
        facade::begin_frame(960, 540, 1.).unwrap();
        let color = Color::new(0.42, 0.48, 0.49, 1.);
        // The two uninterrupted grid loops in world_draw::world. Use the
        // production recorder; no geometry is removed or color normalized.
        for x in -31..32 {
            facade::draw_line_3d(
                Vec3::new(x as f32, 0.006, -53.5),
                Vec3::new(x as f32, 0.006, 13.5),
                color,
            );
        }
        for z in -53..14 {
            facade::draw_line_3d(
                Vec3::new(-31.5, 0.006, z as f32),
                Vec3::new(31.5, 0.006, z as f32),
                color,
            );
        }
        let list = facade::take_draw_list().unwrap();
        assert_eq!(list.commands.len(), 131); // Initial camera + 130 line commands.
        let Command::Lines { lines, model } = &list.commands[1] else {
            panic!("first grid line")
        };
        let (consumed, batches) = adjacent_batches(lines, *model, &list.commands[2..]);
        assert_eq!(consumed, 129);
        let batches: Vec<_> = batches.collect();
        assert_eq!(batches.len(), 1);
        let original: Vec<_> = list.commands[1..]
            .iter()
            .flat_map(|command| match command {
                Command::Lines { lines, .. } => lines.clone(),
                _ => panic!("grid run changed command kinds"),
            })
            .collect();
        assert_eq!(original.len(), 130);
        verify_geometry(&batches[0].0, &batches[0].1, &original);
    }

    #[test]
    fn line_batches_never_wrap_u16_indices() {
        let lines = vec![
            Line {
                start: Vec3::ZERO,
                end: Vec3::ONE,
                color: Color::WHITE
            };
            32769
        ];
        let batches: Vec<_> = batches(lines.iter()).collect();
        assert_eq!(batches.len(), 2);
        assert_eq!(batches[0].1.last(), Some(&u16::MAX));
        assert_eq!(batches[1].1, vec![0, 1]);
    }
}
