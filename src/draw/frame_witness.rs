//! Opt-in validation pixels, emitted before readback rather than added to PNGs.
//! This is a frame/run binding witness, not a scene-content or visual approval.
use super::{Color, Rect};

pub const SCHEMA: &str = "rust-duty-capture-frame-witness/v1";
pub const WIDTH: u32 = 64;
pub const HEIGHT: u32 = 22;

pub fn parse_identity(value: &str) -> Result<[u8; 32], String> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
    {
        return Err("capture witness identity must be 64 lowercase hexadecimal characters".into());
    }
    let mut identity = [0; 32];
    for (index, output) in identity.iter_mut().enumerate() {
        *output = u8::from_str_radix(&value[index * 2..index * 2 + 2], 16)
            .map_err(|error| error.to_string())?;
    }
    Ok(identity)
}

pub fn requested_identity(
    args: impl IntoIterator<Item = impl AsRef<str>>,
) -> Result<Option<String>, String> {
    let mut result = None;
    for argument in args {
        let arg = argument.as_ref();
        if arg == "--capture-frame-witness" {
            return Err("capture witness requires --capture-frame-witness=<identity>".into());
        }
        if let Some(value) = arg.strip_prefix("--capture-frame-witness=") {
            if result.is_some() {
                return Err("capture witness identity may be specified only once".into());
            }
            parse_identity(value)?;
            result = Some(value.to_owned());
        }
    }
    Ok(result)
}

/// Opaque 2x2 cells: little-endian frame index, its complement, then identity.
/// Header red/blue halves distinguish orientation from valid bit payloads.
pub fn rectangles(frame_index: u32, identity: &[u8; 32]) -> Vec<(Rect, Color)> {
    let mut output = vec![
        (Rect::new(0., 0., 32., 2.), Color::new(1., 0., 0., 1.)),
        (Rect::new(32., 0., 32., 2.), Color::new(0., 0., 1., 1.)),
    ];
    let bytes: Vec<u8> = frame_index
        .to_le_bytes()
        .into_iter()
        .chain((!frame_index).to_le_bytes())
        .chain(identity.iter().copied())
        .collect();
    for (bit, value) in bytes
        .iter()
        .flat_map(|byte| (0..8).map(move |bit| (byte >> bit) & 1))
        .enumerate()
    {
        let level = f32::from(value);
        output.push((
            Rect::new((bit % 32 * 2) as f32, (2 + bit / 32 * 2) as f32, 2., 2.),
            Color::new(level, level, level, 1.),
        ));
    }
    output
}

/// One upload/draw for the whole witness, avoiding hundreds of tiny GPU batches.
pub fn mesh(frame_index: u32, identity: &[u8; 32]) -> super::Mesh {
    let mut mesh = super::Mesh::default();
    for (rect, color) in rectangles(frame_index, identity) {
        let base = mesh.vertices.len() as u16;
        for (x, y) in [
            (rect.x, rect.y),
            (rect.x + rect.w, rect.y),
            (rect.x + rect.w, rect.y + rect.h),
            (rect.x, rect.y + rect.h),
        ] {
            mesh.vertices
                .push(super::Vertex::new(x, y, 0., 0., 0., color));
        }
        mesh.indices
            .extend([base, base + 1, base + 2, base, base + 2, base + 3]);
    }
    mesh
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn opt_in_identity_is_strict_and_unique() {
        let id = "0123456789abcdef".repeat(4);
        assert_eq!(requested_identity(["game", "--capture"]).unwrap(), None);
        assert_eq!(
            requested_identity([format!("--capture-frame-witness={id}")]).unwrap(),
            Some(id.clone())
        );
        for invalid in [
            "".to_owned(),
            "f".repeat(63),
            "A".repeat(64),
            "g".repeat(64),
        ] {
            assert!(parse_identity(&invalid).is_err());
        }
        assert!(requested_identity(["--capture-frame-witness"]).is_err());
        assert!(requested_identity([
            format!("--capture-frame-witness={id}"),
            format!("--capture-frame-witness={id}")
        ])
        .is_err());
    }
    #[test]
    fn marker_has_fixed_extent_endianness_and_complement() {
        let mut id = [0; 32];
        id[0] = 0x81;
        id[31] = 0x42;
        let cells = rectangles(1, &id);
        assert_eq!(cells.len(), 322);
        assert_eq!(cells[0].1, Color::new(1., 0., 0., 1.));
        assert_eq!(cells[1].1, Color::new(0., 0., 1., 1.));
        assert_eq!(cells[2].1.r, 1.);
        assert_eq!(cells[3].1.r, 0.);
        assert_eq!(cells[34].1.r, 0.);
        assert_eq!(cells[35].1.r, 1.);
        assert_eq!(cells[66].1.r, 1.);
        assert_eq!(cells[73].1.r, 1.);
        for (rect, color) in cells {
            assert!(
                rect.x >= 0.
                    && rect.y >= 0.
                    && rect.x + rect.w <= WIDTH as f32
                    && rect.y + rect.h <= HEIGHT as f32
            );
            assert_eq!(color.a, 1.);
        }
    }
    #[test]
    fn whole_witness_is_one_bounded_untextured_mesh() {
        let mesh = mesh(42, &[0x55; 32]);
        mesh.validate().unwrap();
        assert_eq!(mesh.vertices.len(), 322 * 4);
        assert_eq!(mesh.indices.len(), 322 * 6);
        assert!(mesh.texture.is_none());
        assert!(mesh.vertices.iter().all(|vertex| vertex.color[3] == 255));
    }
    #[test]
    fn identity_changes_pixels_even_at_same_frame_index() {
        let a = rectangles(7, &[0; 32]);
        let b = rectangles(7, &[1; 32]);
        assert_ne!(a, b);
        assert_ne!(a, rectangles(8, &[0; 32]));
    }
}
