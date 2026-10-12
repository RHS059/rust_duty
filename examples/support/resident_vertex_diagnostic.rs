//! Bounded selection of original authored triangles for explicit vertex readback.
//! Included by the existing correctness fixture; it never alters image verdicts.
use super::{bits, require, write, Case, HEIGHT, WIDTH};
use glam::{Mat4, Vec4};
use rust_duty_launcher::bytes_hash;
use serde_json::{json, Value};
use std::{collections::BTreeMap, path::Path};
use vector_range::{
    draw::Command,
    render::{resident_vertex_probe as probe, WgpuRenderer},
};

const MAX_PIXELS: usize = 16;
const PER_PIXEL: usize = 2;

fn historical_pixels(name: &str) -> &'static [[u32; 2]] {
    match name {
        "ready-0" | "ready-1" | "ready-3" | "manifest-0" | "manifest-12" | "manifest-24" => {
            &[[544, 257]]
        }
        "walk-0" | "walk-3" => &[[561, 238]],
        "walk-1" => &[[551, 253]],
        "ads-1" => &[[546, 246], [547, 246], [519, 261], [519, 263]],
        "reload-1" => &[[508, 233], [510, 233], [524, 233], [524, 234], [505, 270]],
        _ => &[],
    }
}

fn remap(camera: Mat4, model: Mat4) -> Mat4 {
    Mat4::from_cols(
        Vec4::X,
        Vec4::Y,
        Vec4::new(0., 0., 0.5, 0.),
        Vec4::new(0., 0., 0.5, 1.),
    ) * camera
        * model
}

#[derive(Clone)]
struct Hit {
    command: usize,
    corner: usize,
    depth: f64,
}

fn triangle_depth(points: [[f64; 3]; 3], pixel: [u32; 2]) -> Option<f64> {
    let [a, b, c] = points;
    let p = [f64::from(pixel[0]) + 0.5, f64::from(pixel[1]) + 0.5];
    let denominator = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1]);
    if !denominator.is_finite() || denominator.abs() < 1e-16 {
        return None;
    }
    let x = ((b[1] - c[1]) * (p[0] - c[0]) + (c[0] - b[0]) * (p[1] - c[1])) / denominator;
    let y = ((c[1] - a[1]) * (p[0] - c[0]) + (a[0] - c[0]) * (p[1] - c[1])) / denominator;
    let z = 1. - x - y;
    // A generous selection envelope, never a raster/coverage acceptance rule.
    if [x, y, z].iter().any(|v| *v < -1e-4 || *v > 1.0001) {
        return None;
    }
    let depth = x * a[2] + y * b[2] + z * c[2];
    depth.is_finite().then_some(depth)
}

fn samples(values: &[probe::VertexSample]) -> Value {
    json!(values
        .iter()
        .map(|v| json!({"source_vertex":v.source_vertex,
        "clip_bits":v.clip_bits,"color_bits":v.color_bits}))
        .collect::<Vec<_>>())
}

pub(super) fn run(
    directory: &Path,
    renderer: &mut WgpuRenderer,
    cpu: &Case,
    native: &Case,
    camera: Mat4,
    a: &image::RgbaImage,
    b: &image::RgbaImage,
) -> Result<(), String> {
    let changed: Vec<[u32; 2]> = a
        .enumerate_pixels()
        .filter_map(|(x, y, p)| (p != b.get_pixel(x, y)).then_some([x, y]))
        .collect();
    let mut pixels = historical_pixels(&cpu.name).to_vec();
    for pixel in &changed {
        if !pixels.contains(pixel) && pixels.len() < MAX_PIXELS {
            pixels.push(*pixel);
        }
    }
    require(pixels.len() <= MAX_PIXELS, "unbounded probe pixel list")?;
    let cpu_commands: Vec<_> = cpu
        .list
        .commands
        .iter()
        .filter(|v| matches!(v, Command::Mesh { .. }))
        .collect();
    let native_commands: Vec<_> = native
        .list
        .commands
        .iter()
        .filter(|v| matches!(v, Command::Resident { .. }))
        .collect();
    require(
        cpu_commands.len() == native_commands.len(),
        "probe draw order differs",
    )?;
    let mut hits = vec![Vec::<Hit>::new(); pixels.len()];
    for (command, &value) in cpu_commands.iter().enumerate() {
        let Command::Mesh { mesh, model, .. } = value else {
            unreachable!()
        };
        let transform = remap(camera, *model);
        let projected: Vec<_> = mesh
            .vertices
            .iter()
            .map(|v| {
                let p = transform * v.position.extend(1.);
                if !p.is_finite() || p.w <= 0. {
                    return None;
                }
                let q = p.as_dvec4() / f64::from(p.w);
                Some([
                    (q.x + 1.) * f64::from(WIDTH) * 0.5,
                    (1. - q.y) * f64::from(HEIGHT) * 0.5,
                    q.z,
                ])
            })
            .collect();
        for (triangle, indices) in mesh.indices.as_chunks::<3>().0.iter().enumerate() {
            let Some(points) = indices
                .iter()
                .map(|&i| projected[usize::from(i)])
                .collect::<Option<Vec<_>>>()
            else {
                continue;
            };
            let points: [[f64; 3]; 3] = points.try_into().unwrap();
            for (pixel, candidates) in pixels.iter().zip(&mut hits) {
                if let Some(depth) = triangle_depth(points, *pixel) {
                    candidates.push(Hit {
                        command,
                        corner: triangle * 3,
                        depth,
                    });
                    candidates.sort_by(|a, b| {
                        a.depth
                            .total_cmp(&b.depth)
                            .then(a.command.cmp(&b.command))
                            .then(a.corner.cmp(&b.corner))
                    });
                    candidates.truncate(PER_PIXEL);
                }
            }
        }
    }
    let mut selected = BTreeMap::<usize, Vec<usize>>::new();
    let pixel_rows: Vec<_>=pixels.iter().zip(&hits).map(|(pixel,hits)| {
        for h in hits {
            let corners=selected.entry(h.command).or_default();
            if !corners.contains(&h.corner){corners.push(h.corner);}
        }
        json!({"pixel":pixel,"triangles":hits.iter().map(|h|json!({"command":h.command,"corner":h.corner,"cpu_depth":h.depth})).collect::<Vec<_>>()})
    }).collect();
    let mut rows = Vec::new();
    for (command, corners) in selected {
        let Command::Mesh { mesh, model, .. } = cpu_commands[command] else {
            unreachable!()
        };
        let Command::Resident {
            draw,
            model: native_model,
            ..
        } = native_commands[command]
        else {
            unreachable!()
        };
        let mut cpu_indices = Vec::new();
        let mut native_indices = Vec::new();
        for &corner in &corners {
            require(
                corner + 3 <= draw.mesh().indices().len(),
                "resident triangle range differs",
            )?;
            cpu_indices.extend(
                mesh.indices[corner..corner + 3]
                    .iter()
                    .map(|&v| u32::from(v)),
            );
            native_indices.extend(
                draw.mesh().indices()[corner..corner + 3]
                    .iter()
                    .map(|&v| u32::from(v)),
            );
        }
        require(
            cpu_indices.len() <= probe::MAX_VERTICES,
            "probe selection exceeds native bound",
        )?;
        let reference =
            probe::capture_cpu_reference(renderer, mesh, remap(camera, *model), &cpu_indices)?;
        let current = probe::capture(
            renderer,
            draw,
            remap(camera, *native_model),
            &native_indices,
            probe::Arithmetic::Current,
        )?;
        let historical = probe::capture(
            renderer,
            draw,
            remap(camera, *native_model),
            &native_indices,
            probe::Arithmetic::HistoricalInverseSqrt,
        )?;
        let skin = draw.palette().is_some();
        rows.push(json!({"command":command,"triangle_corner_offsets":corners,
            "kind":if skin{"skin"}else{"rigid"},
            "vertex_count":cpu_indices.len(),
            "cpu_probe_shader_sha256":bytes_hash(probe::cpu_shader_source(cpu_indices.len())?.as_bytes()),
            "current_probe_shader_sha256":bytes_hash(probe::shader_source(probe::Arithmetic::Current,skin,cpu_indices.len())?.as_bytes()),
            "historical_probe_shader_sha256":bytes_hash(probe::shader_source(probe::Arithmetic::HistoricalInverseSqrt,skin,cpu_indices.len())?.as_bytes()),
            "cpu_model_bits":bits(*model),"resident_model_bits":bits(*native_model),
            "cpu_vertex_stage":samples(&reference),"current_vertex_stage":samples(&current),
            "historical_inverse_sqrt_vertex_stage":samples(&historical)}));
    }
    let current_shader = probe::shader_source(probe::Arithmetic::Current, true, 3)?;
    let historical_shader =
        probe::shader_source(probe::Arithmetic::HistoricalInverseSqrt, true, 3)?;
    let uncovered = hits.iter().filter(|h| h.is_empty()).count();
    let omitted = changed.iter().filter(|p| !pixels.contains(p)).count();
    write(
        &directory.join(format!("{}.json", cpu.name)),
        &json!({
            "schema":"rust-duty-resident-vertex-probe/v1","case":cpu.name,
            "source_receipt_sha256":option_env!("PASS_SUBMISSION_SOURCE_SHA256").unwrap_or("unbound"),
            "camera_bits":bits(camera),"metadata":cpu.metadata,
            "production_resident_shader_sha256":bytes_hash(include_bytes!("../../src/render/resident.wgsl")),
            "production_cpu_shader_sha256":bytes_hash(include_bytes!("../../src/render/mesh.wgsl")),
            "probe_implementation_sha256":bytes_hash(include_bytes!("../../src/render/resident_vertex_probe.rs")),
            "representative_probe_shader_count":3,"current_skin_probe_shader_sha256":bytes_hash(current_shader.as_bytes()),
            "historical_skin_probe_shader_sha256":bytes_hash(historical_shader.as_bytes()),
            "changed_pixel_count":changed.len(),"selection_limit_pixels":MAX_PIXELS,"selection_limit_triangles_per_pixel":PER_PIXEL,
            "changed_pixels_not_selected":omitted,"requested_pixels_without_triangle":uncovered,
            "selection_complete":uncovered==0 && omitted==0,
            "pixels":pixel_rows,"draws":rows,
            "scope":"actual instrumented vertex-stage clip/color bits; nearest CPU-projected triangles are a selection aid, not GPU primitive IDs; altered entry points may alter optimization; original exact-image verdict remains authoritative"
        }),
    )?;
    require(
        uncovered == 0 && omitted == 0,
        "vertex probe selection incomplete; counts and available samples retained",
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn pixel_selection_is_bounded_and_does_not_accept_outside_or_degenerate_triangles() {
        let tri = [[0., 0., 0.25], [10., 0., 0.25], [0., 10., 0.25]];
        assert_eq!(triangle_depth(tri, [1, 1]), Some(0.25));
        assert_eq!(triangle_depth(tri, [9, 9]), None);
        assert_eq!(triangle_depth([[0.; 3]; 3], [0, 0]), None);
        for name in [
            "ready-0",
            "reload-1",
            "ads-1",
            "manifest-12",
            "rigid-alpha-1",
        ] {
            assert!(historical_pixels(name).len() <= MAX_PIXELS);
        }
    }
}
