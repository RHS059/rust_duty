//! Line-list batches keep debug lines in command order and use the current camera's depth.
use crate::draw::{Line, Vertex};
use glam::Vec2;
pub(crate) fn batches(lines: &[Line]) -> impl Iterator<Item = (Vec<Vertex>, Vec<u16>)> + '_ {
    lines.chunks(32768).map(|lines| {
        let vertices: Vec<_> = lines
            .iter()
            .flat_map(|line| {
                [
                    Vertex::new2(line.start, Vec2::ZERO, line.color),
                    Vertex::new2(line.end, Vec2::ZERO, line.color),
                ]
            })
            .collect();
        let indices = (0..vertices.len()).map(|index| index as u16).collect();
        (vertices, indices)
    })
}
#[cfg(test)]
mod tests {
    use super::*;
    use crate::draw::Color;
    use glam::Vec3;
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
        let batches: Vec<_> = batches(&lines).collect();
        assert_eq!(batches.len(), 2);
        assert_eq!(batches[0].1.last(), Some(&u16::MAX));
        assert_eq!(batches[1].1, vec![0, 1]);
    }
}
