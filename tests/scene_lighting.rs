//! Independent CPU lighting contracts; these do not claim GPU capture coverage.
use macroquad::prelude::*;
use vector_range::{scene_lighting::SceneLighting, sim::Player};

fn mesh_with_normals(normals: &[Vec3]) -> Mesh {
    Mesh {
        vertices: normals
            .iter()
            .enumerate()
            .map(|(i, &normal)| {
                let mut vertex = Vertex::new2(
                    vec3(i as f32 * 0.2, -0.3, 0.7),
                    vec2(i as f32 * 0.1, 0.25),
                    MAGENTA,
                );
                vertex.normal = normal.extend(0.);
                vertex
            })
            .collect(),
        indices: vec![],
        texture: None,
    }
}

fn colors(mesh: &Mesh) -> Vec<[u8; 4]> {
    mesh.vertices.iter().map(|vertex| vertex.color).collect()
}

fn reference_color(light: SceneLighting, albedo: Color, normal: Vec3) -> [u8; 4] {
    let intensity =
        light.ambient + light.diffuse * normal.normalize().dot(light.direction_to_light).max(0.);
    Color::new(
        albedo.r * intensity,
        albedo.g * intensity,
        albedo.b * intensity,
        albedo.a,
    )
    .into()
}

#[test]
fn directional_rigid_lighting_is_translation_invariant() {
    let light = SceneLighting::range();
    let albedo = Color::new(0.73, 0.49, 0.31, 0.61);
    let mut mesh =
        mesh_with_normals(&[Vec3::X, Vec3::Y, Vec3::Z, vec3(-0.5, 0.8, 0.2).normalize()]);
    let shape = Mat4::from_scale_rotation_translation(
        vec3(2., 0.7, 1.4),
        Quat::from_euler(EulerRot::YXZ, 0.35, -0.2, 0.1),
        Vec3::ZERO,
    );
    light.shade_rigid(&mut mesh, albedo, shape);
    let reference = colors(&mesh);
    for translation in [Vec3::ZERO, vec3(10., 20., -30.), vec3(-500., 0.5, 700.)] {
        light.shade_rigid(
            &mut mesh,
            albedo,
            Mat4::from_translation(translation) * shape,
        );
        assert_eq!(colors(&mesh), reference, "translation {translation:?}");
    }
}

#[test]
fn view_light_uses_actual_recoiled_and_pitch_clamped_camera_direction() {
    let world = SceneLighting::range();
    for (yaw, pitch, recoil) in [
        (-1.1, 0.3, vec2(0.12, -0.09)),
        (0.7, 1.49, vec2(0.2, 0.05)),
        (2.4, -1.49, vec2(-0.2, -0.05)),
    ] {
        let player = Player {
            yaw,
            pitch,
            recoil,
            ..Default::default()
        };
        let forward = player.direction();
        let view_matrix = Mat4::look_at_rh(Vec3::ZERO, forward, Vec3::Y);
        let expected = view_matrix.transform_vector3(world.direction_to_light);
        let actual = world.in_view(forward);
        assert!(actual.direction_to_light.is_finite());
        assert!(actual.direction_to_light.distance(expected) < 1e-6);
        assert!((actual.direction_to_light.length() - 1.).abs() < 1e-6);

        let unrecoiled = world.in_view(vector_range::sim::direction(yaw, pitch));
        assert!(
            actual
                .direction_to_light
                .distance(unrecoiled.direction_to_light)
                > 0.01,
            "this fixture must detect accidentally using raw yaw/pitch"
        );
        for world_normal in [Vec3::X, Vec3::Y, Vec3::Z, vec3(-1., 2., 3.)] {
            let view_normal = view_matrix.transform_vector3(world_normal);
            assert!((actual.irradiance(view_normal) - world.irradiance(world_normal)).abs() < 1e-6);
        }
    }
}

#[test]
fn nonuniform_actor_normal_matches_perpendicular_transformed_tangents() {
    let light = SceneLighting::range();
    let albedo = Color::new(0.93, 0.74, 0.52, 0.82);
    let normal = vec3(1., 2., -0.7).normalize();
    let tangent = normal.cross(Vec3::Z).normalize();
    let bitangent = normal.cross(tangent).normalize();
    let mut mesh = mesh_with_normals(&[normal]);
    let mut distinguishes_naive_transform = false;
    for yaw in [-0.4, 0., 0.7] {
        let actor = Mat4::from_scale_rotation_translation(
            vec3(3.5, 0.3, 1.9),
            Quat::from_euler(EulerRot::YXZ, yaw, 0.17, -0.21),
            vec3(12., -3., 4.),
        );
        let transformed_tangent = actor.transform_vector3(tangent);
        let transformed_bitangent = actor.transform_vector3(bitangent);
        // Independent geometric oracle: do not use inverse-transpose here.
        let perpendicular_normal = transformed_tangent.cross(transformed_bitangent).normalize();
        assert!(perpendicular_normal.dot(transformed_tangent).abs() < 1e-6);
        assert!(perpendicular_normal.dot(transformed_bitangent).abs() < 1e-6);
        let inverse_transpose_normal = actor
            .inverse()
            .transpose()
            .transform_vector3(normal)
            .normalize();
        assert!(inverse_transpose_normal.distance(perpendicular_normal) < 1e-6);

        light.shade_rigid(&mut mesh, albedo, actor);
        assert_eq!(
            mesh.vertices[0].color,
            reference_color(light, albedo, perpendicular_normal)
        );
        distinguishes_naive_transform |=
            reference_color(light, albedo, actor.transform_vector3(normal))
                != mesh.vertices[0].color;
        assert_eq!(mesh.vertices[0].normal, normal.extend(0.));
    }
    assert!(distinguishes_naive_transform);
}

#[test]
fn weighted_skinned_bone_normals_have_identical_world_and_view_irradiance() {
    let world = SceneLighting::range();
    let normal = vec3(-0.4, 0.8, 0.3).normalize();
    let weights = [0.1, 0.2, 0.45, 0.25];
    let palettes = [
        Mat4::IDENTITY,
        Mat4::from_scale_rotation_translation(
            vec3(1.2, 0.8, 1.),
            Quat::from_rotation_x(0.3),
            vec3(0.2, 0.1, -0.4),
        ),
        Mat4::from_scale_rotation_translation(
            vec3(0.7, 1.3, 1.1),
            Quat::from_rotation_z(-0.4),
            vec3(-0.1, 0.3, -0.5),
        ),
        Mat4::from_rotation_y(0.5),
    ];
    let weighted_normal = |root: Mat4| {
        palettes
            .iter()
            .zip(weights)
            .fold(Vec3::ZERO, |sum, (palette, weight)| {
                sum + (root * *palette)
                    .inverse()
                    .transpose()
                    .transform_vector3(normal)
                    * weight
            })
            .normalize()
    };
    let view_normal = weighted_normal(Mat4::IDENTITY);
    for yaw in [-2.7, -1.1, 0., 1.8] {
        for pitch in [-1.1, 0., 1.1] {
            let forward = vector_range::sim::direction(yaw, pitch);
            let view_to_world = Mat4::look_at_rh(Vec3::ZERO, forward, Vec3::Y).inverse();
            let world_normal = weighted_normal(view_to_world);
            assert!(world_normal.distance(view_to_world.transform_vector3(view_normal)) < 1e-6);
            assert!(
                (world.irradiance(world_normal) - world.in_view(forward).irradiance(view_normal))
                    .abs()
                    < 1e-6
            );
        }
    }
}

#[test]
fn repeated_rigid_instances_relight_from_albedo_without_mutating_geometry() {
    let light = SceneLighting::range();
    let albedo = Color::new(0.84, 0.57, 0.39, 0.63);
    let mut mesh = mesh_with_normals(&[
        light.direction_to_light,
        -light.direction_to_light,
        Vec3::Y,
        Vec3::Z,
    ]);
    let geometry: Vec<_> = mesh
        .vertices
        .iter()
        .map(|vertex| (vertex.position, vertex.uv, vertex.normal))
        .collect();
    let instances = [
        Mat4::from_rotation_translation(Quat::IDENTITY, vec3(0.1, -0.2, -0.4)),
        Mat4::from_rotation_translation(
            Quat::from_rotation_x(std::f32::consts::PI),
            vec3(-0.2, -0.4, -0.5),
        ),
    ];
    light.shade_rigid(&mut mesh, albedo, instances[0]);
    let first_instance = colors(&mesh);
    light.shade_rigid(&mut mesh, albedo, instances[1]);
    let second_instance = colors(&mesh);
    assert_ne!(first_instance, second_instance);
    let alpha = Into::<[u8; 4]>::into(albedo)[3];
    for _ in 0..64 {
        for (transform, expected) in instances.iter().zip([&first_instance, &second_instance]) {
            light.shade_rigid(&mut mesh, albedo, *transform);
            assert_eq!(&colors(&mesh), expected);
            for (vertex, &(position, uv, normal)) in mesh.vertices.iter().zip(&geometry) {
                assert_eq!(
                    (vertex.position, vertex.uv, vertex.normal),
                    (position, uv, normal)
                );
                assert_eq!(vertex.color[3], alpha);
            }
        }
    }
}
