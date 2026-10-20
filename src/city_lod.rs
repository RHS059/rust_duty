//! Once-per-load, attribute-aware meshoptimizer LODs for static city instances.
//! Full-detail geometry remains unchanged. Reduced meshes reference original
//! samples, so no new vertex position, baked color, UV or normal is synthesized.
use crate::{draw::Vertex, sim::Aabb};
use glam::{Mat4, Vec3};

/// A reduced level owns only the vertices referenced by its optimized indices.
pub struct ReducedLod {
    pub vertices: Vec<Vertex>,
    pub indices: Vec<u32>,
    /// Meshoptimizer's combined geometric/attribute relative error estimate.
    pub relative_error: f32,
}

/// Attempt half- and quarter-triangle meshes, always relative to the original.
/// Tiny or topology-constrained assets may retain fewer distinct LODs rather
/// than forcing holes or reporting identical buffers as a quality reduction.
pub fn generate(vertices: &[Vertex], indices: &[u32]) -> Result<Vec<ReducedLod>, String> {
    if vertices.is_empty()
        || vertices.len() > u32::MAX as usize
        || indices.is_empty()
        || !indices.len().is_multiple_of(3)
        || indices
            .iter()
            .any(|&index| index as usize >= vertices.len())
        || vertices
            .iter()
            .any(|v| !v.position.is_finite() || !v.normal.is_finite() || !v.uv.is_finite())
    {
        return Err("invalid city LOD source geometry".into());
    }
    if indices.len() < 24 {
        return Ok(Vec::new());
    }
    let positions: Vec<_> = vertices.iter().map(|v| v.position.to_array()).collect();
    // Colored faceted city meshes have duplicated attribute seams. Preserve
    // their appearance with the attribute metric while allowing safe collapses
    // across those seams. Boundaries stay locked to avoid cracks between parts.
    let attributes: Vec<f32> = vertices
        .iter()
        .flat_map(|v| {
            [
                v.normal.x,
                v.normal.y,
                v.normal.z,
                f32::from(v.color[0]) / 255.,
                f32::from(v.color[1]) / 255.,
                f32::from(v.color[2]) / 255.,
                f32::from(v.color[3]) / 255.,
                v.uv.x,
                v.uv.y,
            ]
        })
        .collect();
    let locks = vec![false; vertices.len()];
    let weights = [0.25, 0.25, 0.25, 1., 1., 1., 1., 1., 1.];
    let mut lods = Vec::with_capacity(2);
    let mut previous_count = indices.len();
    for (ratio, error_limit) in [(0.5, 0.005), (0.25, 0.015)] {
        let target = (((indices.len() as f64 * ratio) as usize / 3) * 3).max(3);
        let mut relative_error = 0.;
        let simplified = meshopt::simplify_with_attributes_and_locks_decoder(
            indices,
            &positions,
            &attributes,
            &weights,
            weights.len() * std::mem::size_of::<f32>(),
            &locks,
            target,
            error_limit,
            meshopt::SimplifyOptions::Permissive | meshopt::SimplifyOptions::LockBorder,
            Some(&mut relative_error),
        );
        if simplified.is_empty() || simplified.len() >= previous_count {
            continue;
        }
        if !relative_error.is_finite()
            || !simplified.len().is_multiple_of(3)
            || simplified
                .iter()
                .any(|&index| index as usize >= vertices.len())
        {
            return Err("meshoptimizer returned invalid city LOD geometry".into());
        }
        let optimized = meshopt::optimize_vertex_cache(&simplified, vertices.len());
        let (compact_vertices, compact_indices) = compact(vertices, &optimized);
        previous_count = compact_indices.len();
        lods.push(ReducedLod {
            vertices: compact_vertices,
            indices: compact_indices,
            relative_error,
        });
    }
    Ok(lods)
}

fn compact(vertices: &[Vertex], indices: &[u32]) -> (Vec<Vertex>, Vec<u32>) {
    let mut remap = vec![u32::MAX; vertices.len()];
    let mut compact = Vec::new();
    let indices = indices
        .iter()
        .map(|&index| {
            let mapped = &mut remap[index as usize];
            if *mapped == u32::MAX {
                *mapped = compact.len() as u32;
                compact.push(vertices[index as usize]);
            }
            *mapped
        })
        .collect();
    (compact, indices)
}

/// Fraction of viewport height covered by the projected AABB. Crossing the
/// near plane or enclosing the eye requests full detail, avoiding unstable or
/// negative perspective divisions. Orthographic cameras work without a
/// distance heuristic. The matrix uses the draw facade's -1..1 clip depth.
pub fn screen_fraction(bounds: Aabb, eye: Vec3, view_projection: Mat4) -> f32 {
    if !view_projection.is_finite()
        || !bounds.min.is_finite()
        || !bounds.max.is_finite()
        || !bounds.min.cmple(bounds.max).all()
        || !eye.is_finite()
        || (eye.cmpge(bounds.min).all() && eye.cmple(bounds.max).all())
    {
        return f32::INFINITY;
    }
    let mut minimum = f32::INFINITY;
    let mut maximum = f32::NEG_INFINITY;
    // Include horizontal span normalized to viewport height conservatively:
    // view_projection does not retain the viewport's aspect ratio, so vertical
    // span is used and a radius bound below protects thin/horizontal assets.
    let center = (bounds.min + bounds.max) * 0.5;
    let radius = (bounds.max - bounds.min).length() * 0.5;
    for x in [bounds.min.x, bounds.max.x] {
        for y in [bounds.min.y, bounds.max.y] {
            for z in [bounds.min.z, bounds.max.z] {
                let clip = view_projection * Vec3::new(x, y, z).extend(1.);
                if !clip.is_finite() || clip.w <= 0.0001 || clip.z <= -clip.w {
                    return f32::INFINITY;
                }
                minimum = minimum.min(clip.y / clip.w);
                maximum = maximum.max(clip.y / clip.w);
            }
        }
    }
    let clip_center = view_projection * center.extend(1.);
    let row_y = Vec3::new(
        view_projection.x_axis.y,
        view_projection.y_axis.y,
        view_projection.z_axis.y,
    );
    let row_w = Vec3::new(
        view_projection.x_axis.w,
        view_projection.y_axis.w,
        view_projection.z_axis.w,
    );
    let near_w = clip_center.w - row_w.length() * radius;
    if near_w <= 0.0001 {
        return f32::INFINITY;
    }
    // The sphere bounds all orientations, including poles and ground-level
    // wide objects. This deliberately chooses extra detail near the camera.
    let sphere_fraction = radius * row_y.length() / near_w;
    ((maximum - minimum) * 0.5).max(sphere_fraction)
}

/// 0 is full detail, 1 and 2 are reduced meshes. Selection depends on screen
/// size, never raw distance; use at most the levels actually generated.
pub fn select(bounds: Aabb, eye: Vec3, view_projection: Mat4, reduced_count: usize) -> usize {
    let fraction = screen_fraction(bounds, eye, view_projection);
    let level = if fraction < 0.06 {
        2
    } else if fraction < 0.18 {
        1
    } else {
        0
    };
    level.min(reduced_count.min(2))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::draw::Color;
    use glam::Vec2;

    fn grid(side: u32) -> (Vec<Vertex>, Vec<u32>) {
        let vertices = (0..=side)
            .flat_map(|y| {
                (0..=side).map(move |x| {
                    Vertex::new2(Vec3::new(x as f32, y as f32, 0.), Vec2::ZERO, Color::WHITE)
                })
            })
            .collect();
        let mut indices = Vec::new();
        for y in 0..side {
            for x in 0..side {
                let a = y * (side + 1) + x;
                indices.extend([a, a + 1, a + side + 1, a + 1, a + side + 2, a + side + 1]);
            }
        }
        (vertices, indices)
    }

    #[test]
    fn generates_two_distinct_compact_lods_without_inventing_vertex_samples() {
        let (vertices, indices) = grid(20);
        let lods = generate(&vertices, &indices).unwrap();
        assert_eq!(lods.len(), 2);
        let mut previous = indices.len();
        for lod in lods {
            assert!(lod.indices.len() < previous);
            assert!(lod.vertices.len() < vertices.len());
            assert!(lod.vertices.iter().all(|v| vertices.contains(v)));
            assert!(lod
                .indices
                .iter()
                .all(|&i| (i as usize) < lod.vertices.len()));
            assert!(lod.relative_error.is_finite());
            previous = lod.indices.len();
        }
    }

    #[test]
    fn invalid_ffi_inputs_are_rejected() {
        let (vertices, mut indices) = grid(4);
        indices[0] = vertices.len() as u32;
        assert!(generate(&vertices, &indices).is_err());
        assert!(generate(&vertices, &[0, 1]).is_err());
        assert!(generate(&[], &[]).is_err());
        let mut vertices = vertices;
        vertices[0].normal.x = f32::NAN;
        assert!(generate(&vertices, &[0, 1, 2]).is_err());
    }

    #[test]
    fn screen_size_selection_keeps_close_and_near_plane_objects_detailed() {
        let projection = Mat4::perspective_rh_gl(60_f32.to_radians(), 16. / 9., 0.1, 400.);
        let bounds = |z| Aabb::from_center(Vec3::new(0., 0., z), Vec3::splat(2.));
        assert_eq!(select(bounds(-4.), Vec3::ZERO, projection, 2), 0);
        assert_eq!(select(bounds(-20.), Vec3::ZERO, projection, 2), 1);
        assert_eq!(select(bounds(-100.), Vec3::ZERO, projection, 2), 2);
        assert_eq!(select(bounds(-100.), Vec3::ZERO, projection, 1), 1);
        assert_eq!(select(bounds(0.), Vec3::ZERO, projection, 2), 0);
        assert_eq!(select(bounds(3.), Vec3::ZERO, projection, 2), 0);
        let zoomed = Mat4::perspective_rh_gl(12_f32.to_radians(), 16. / 9., 0.1, 400.);
        assert!(
            select(bounds(-20.), Vec3::ZERO, zoomed, 2)
                < select(bounds(-20.), Vec3::ZERO, projection, 2)
        );
    }
}
