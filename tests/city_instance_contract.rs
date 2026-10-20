//! Optional regenerated-scene acceptance. No external assets are committed by
//! this test; the pinned exporter must first create the directory it names.
use glam::{Mat4, Vec3};
use vector_range::city_level::{CityLevel, CITY_FAR_PLANE};

#[test]
#[ignore = "requires an isolated pinned RDCITY04 export in RUST_DUTY_CITY_V4_DIR"]
fn regenerated_city_loads_real_instances_and_culls_with_the_runtime_bvh() {
    let path = std::path::PathBuf::from(
        std::env::var("RUST_DUTY_CITY_V4_DIR")
            .expect("set the explicitly regenerated scene directory"),
    )
    .join("level.json");
    let level = CityLevel::load(&path).expect("regenerated source scene must load");
    assert_eq!(level.chunks.len(), 12_464);
    assert_eq!(
        level
            .chunks
            .iter()
            .map(|c| c.mesh.vertices().len())
            .sum::<usize>(),
        5_740_304
    );
    assert_eq!(
        level
            .chunks
            .iter()
            .map(|c| c.mesh.indices().len() / 3)
            .sum::<usize>(),
        2_740_498
    );
    assert_eq!(
        level
            .chunks
            .iter()
            .filter(|c| c.instance.as_ref().is_some_and(|i| i.max_distance == 120.))
            .count(),
        359
    );
    assert!(level.chunks.iter().all(|c| c.instance.is_some()));
    let eye = level.spawn_position + Vec3::Y * 1.7;
    let matrix = Mat4::perspective_rh_gl(60_f32.to_radians(), 16. / 9., 0.035, CITY_FAR_PLANE)
        * Mat4::look_at_rh(eye, eye - Vec3::Z, Vec3::Y);
    let mut visible = Vec::new();
    let stats = level.visit_visible(eye, matrix, |i| visible.push(i));
    assert_eq!(stats.total_records, 12_464);
    assert!(stats.visible_records > 0 && stats.visible_records < stats.total_records);
    assert!(stats.tested_records < stats.total_records);
    visible.sort_unstable();
    let original_count = visible.len();
    visible.dedup();
    assert_eq!(visible.len(), original_count, "no duplicate submissions");
    let manifest: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    if !manifest["visibility"].is_null() {
        assert!(
            stats.interior_occlusion_enabled,
            "complete authored graph must be admitted"
        );
        let mut largest_rejection = 0;
        for building in manifest["buildings"].as_array().unwrap() {
            let center = &building["center"];
            let center = Vec3::new(
                center[0].as_f64().unwrap() as f32,
                1.7,
                center[2].as_f64().unwrap() as f32,
            );
            for direction in [Vec3::X, -Vec3::X, Vec3::Z, -Vec3::Z] {
                for offset in [-4., 0., 4.] {
                    let target = center + Vec3::new(-direction.z, 0., direction.x) * offset;
                    let eye = target + direction * 9.5;
                    let matrix = Mat4::perspective_rh_gl(
                        30_f32.to_radians(),
                        16. / 9.,
                        0.035,
                        CITY_FAR_PLANE,
                    ) * Mat4::look_at_rh(eye, target, Vec3::Y);
                    let stats = level.visit_visible(eye, matrix, |_| {});
                    largest_rejection = largest_rejection.max(stats.occlusion_culled_records);
                }
            }
        }
        assert!(
            largest_rejection > 0,
            "authored portals reject actual hidden interior candidates"
        );
        eprintln!(
            "largest rejected interior candidate set over 192 exterior views: {largest_rejection}"
        );
    }
    eprintln!("regenerated city runtime visibility: {stats:?}");
}
