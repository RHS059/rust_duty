//! CPU-only VRANIM01 parity probe. Each requested time produces one JSON line.
//! Usage: sample_viewmodel_clip PATH.vra CLIP TIME [TIME...] [--clamp] [--game-axis]
use macroquad::math::{Mat4, Vec3};
use std::{
    error::Error,
    io::{self, BufWriter, Write},
};
use vector_range::viewmodel_animation::{game_model_root, AnimationSet};

fn json_string(out: &mut impl Write, value: &str) -> io::Result<()> {
    write!(out, "\"")?;
    for ch in value.chars() {
        match ch {
            '"' => write!(out, "\\\"")?,
            '\\' => write!(out, "\\\\")?,
            '\n' => write!(out, "\\n")?,
            '\r' => write!(out, "\\r")?,
            '\t' => write!(out, "\\t")?,
            c if c <= '\u{1f}' => write!(out, "\\u{:04x}", c as u32)?,
            c => write!(out, "{c}")?,
        }
    }
    write!(out, "\"")
}
fn floats(out: &mut impl Write, values: &[f32]) -> io::Result<()> {
    if values.iter().any(|value| !value.is_finite()) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "non-finite transformed output",
        ));
    }
    write!(out, "[")?;
    for (index, value) in values.iter().enumerate() {
        if index > 0 {
            write!(out, ",")?;
        }
        write!(out, "{value}")?;
    }
    write!(out, "]")
}
fn run() -> Result<(), Box<dyn Error>> {
    let usage = "usage: sample_viewmodel_clip PATH.vra CLIP TIME [TIME...] [--clamp] [--game-axis]";
    let mut args = std::env::args().skip(1);
    let path = args.next().ok_or(usage)?;
    if path == "--help" || path == "-h" {
        println!("{usage}");
        return Ok(());
    }
    let clip = args.next().ok_or(usage)?;
    let mut times = Vec::new();
    let mut clamp = false;
    let mut game_axis = false;
    for argument in args {
        match argument.as_str() {
            "--clamp" => clamp = true,
            "--game-axis" => game_axis = true,
            _ => {
                let value: f32 = argument
                    .parse()
                    .map_err(|_| format!("invalid sample time: {argument}"))?;
                if !value.is_finite() {
                    return Err("sample time must be finite".into());
                }
                times.push(value);
            }
        }
    }
    if times.is_empty() {
        return Err(usage.into());
    }
    let (animation, skin, rigid) = AnimationSet::load_with_companions(path)?;
    let root = if game_axis {
        game_model_root()
    } else {
        Mat4::IDENTITY
    };
    let mut out = BufWriter::new(io::stdout().lock());
    for time in times {
        let pose = if clamp {
            animation.sample_clamped(&clip, time)?
        } else {
            animation.sample(&clip, time)?
        };
        let globals = animation.bone_globals(&pose, root)?;
        let palette = animation.skin_palette(&pose, &skin.bones, root)?;
        let actor_matrices = animation.actor_matrices(&pose, root)?;
        write!(out, "{{\"clip\":")?;
        json_string(&mut out, &clip)?;
        write!(
            out,
            ",\"time\":{time},\"sample_time\":{},\"game_axis\":{game_axis},\"bones\":[",
            pose.sample_time
        )?;
        for (index, bone) in animation.bones().iter().enumerate() {
            if index > 0 {
                write!(out, ",")?;
            }
            write!(out, "{{\"name\":")?;
            json_string(&mut out, &bone.name)?;
            write!(out, ",\"global\":")?;
            floats(&mut out, &globals[index].to_cols_array())?;
            write!(out, "}}")?;
        }
        write!(out, "],\"skin_meshes\":[")?;
        for (index, mesh) in skin.meshes.iter().enumerate() {
            if index > 0 {
                write!(out, ",")?;
            }
            write!(out, "{{\"mesh\":{index},\"positions\":[")?;
            for (vertex_index, vertex) in mesh.vertices.iter().enumerate() {
                if vertex_index > 0 {
                    write!(out, ",")?;
                }
                let position = Vec3::from_array(vertex.position);
                let mut skinned = Vec3::ZERO;
                for (&joint, &weight) in vertex.joints.iter().zip(&vertex.weights) {
                    if weight != 0. {
                        skinned += palette[joint as usize].transform_point3(position) * weight;
                    }
                }
                floats(&mut out, &skinned.to_array())?;
            }
            write!(out, "]}}")?;
        }
        let mut mesh_actors = vec![0; rigid.meshes.len()];
        for (actor_index, actor) in animation.actors().iter().enumerate() {
            for &mesh_index in &actor.mesh_indices {
                mesh_actors[mesh_index] = actor_index;
            }
        }
        write!(out, "],\"rigid_meshes\":[")?;
        for (index, mesh) in rigid.meshes.iter().enumerate() {
            if index > 0 {
                write!(out, ",")?;
            }
            let actor_index = mesh_actors[index];
            let matrix = actor_matrices[actor_index];
            write!(
                out,
                "{{\"mesh\":{index},\"actor\":{actor_index},\"visible\":{},\"positions\":[",
                pose.actor_visible[actor_index]
            )?;
            for (vertex_index, vertex) in mesh.vertices.iter().enumerate() {
                if vertex_index > 0 {
                    write!(out, ",")?;
                }
                floats(
                    &mut out,
                    &matrix
                        .transform_point3(Vec3::from_array(vertex.position))
                        .to_array(),
                )?;
            }
            write!(out, "]}}")?;
        }
        write!(out, "],\"actors\":[")?;
        for (index, actor) in animation.actors().iter().enumerate() {
            if index > 0 {
                write!(out, ",")?;
            }
            write!(out, "{{\"name\":")?;
            json_string(&mut out, &actor.name)?;
            write!(
                out,
                ",\"visible\":{},\"global\":",
                pose.actor_visible[index]
            )?;
            floats(
                &mut out,
                &(root * pose.actor_globals[index].matrix()).to_cols_array(),
            )?;
            write!(out, ",\"matrix\":")?;
            floats(&mut out, &actor_matrices[index].to_cols_array())?;
            write!(out, ",\"mesh_indices\":[")?;
            for (mesh_index, value) in actor.mesh_indices.iter().enumerate() {
                if mesh_index > 0 {
                    write!(out, ",")?;
                }
                write!(out, "{value}")?;
            }
            write!(out, "]}}")?;
        }
        writeln!(out, "]}}")?;
    }
    out.flush()?;
    Ok(())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("sample_viewmodel_clip: {error}");
        std::process::exit(1);
    }
}
