use std::path::Path;
use vector_range::animation_manifest::AnimationManifest;
const MANIFEST: &str = include_str!("../assets/animations.cfg");
#[test]
fn paths_are_manifest_relative_and_revisions_need_no_code_changes() {
    let a = AnimationManifest::parse(MANIFEST, Path::new("bundle/assets")).unwrap();
    assert_eq!(
        a.tactical.asset,
        Path::new("bundle/assets/reload/asset.vra")
    );
    assert!(a.empty.is_none());
    let text = MANIFEST
        .replace("reload_current_wip", "replacement_v2")
        .replace("reload/asset.vra", "revised/asset.vra");
    let b = AnimationManifest::parse(&text, Path::new("bundle/assets")).unwrap();
    assert_eq!(b.tactical.clip, "replacement_v2");
    assert_eq!(
        b.tactical.asset,
        Path::new("bundle/assets/revised/asset.vra")
    );
}
#[test]
fn missing_required_slots_typos_and_unsafe_paths_fail() {
    for text in [
        MANIFEST.replace("reload.tactical.clip=reload_current_wip", ""),
        format!("{MANIFEST}\nreload.tactical.clip=duplicate"),
        format!("{MANIFEST}\nreload.typo=foo"),
        MANIFEST.replace("reload/asset.vra", "../asset.vra"),
        MANIFEST.replace("reload/asset.vra", "C:\\asset.vra"),
        MANIFEST.replace("native_complete", "fit_gameplay_duration"),
        MANIFEST.replace("anchored_crossfade", "crossfade"),
        MANIFEST.replace("ads.clock=native_reversible", "ads.clock=pretend_authored"),
        MANIFEST.replace("ads.entry.clip=ads_entry_r1", ""),
        MANIFEST.replace("ads/asset.vra", "../ads.vra"),
    ] {
        assert!(
            AnimationManifest::parse(&text, Path::new("assets")).is_err(),
            "{text}"
        );
    }
}
#[test]
fn explicit_empty_clip_can_be_added_without_runtime_edits() {
    let text = MANIFEST.replace(
        "reload.empty=unavailable",
        "reload.empty.asset=empty/asset.vra\nreload.empty.clip=empty_v1",
    );
    let manifest = AnimationManifest::parse(&text, Path::new("assets")).unwrap();
    assert_eq!(manifest.empty.unwrap().clip, "empty_v1");
}

#[test]
fn ads_slots_are_revision_independent_and_unavailability_is_explicit() {
    let text = MANIFEST
        .replace("ads_entry_r1", "ads_entry_r2")
        .replace("ads/asset.vra", "new_ads/asset.vra");
    let manifest = AnimationManifest::parse(&text, Path::new("bundle/assets")).unwrap();
    let ads = manifest.ads.unwrap();
    assert_eq!(ads.entry_clip, "ads_entry_r2");
    assert_eq!(ads.asset, Path::new("bundle/assets/new_ads/asset.vra"));
    let unavailable = MANIFEST
        .lines()
        .filter(|line| !line.starts_with("ads."))
        .collect::<Vec<_>>()
        .join("\n")
        + "\nads=unavailable\n";
    assert!(AnimationManifest::parse(&unavailable, Path::new("assets"))
        .unwrap()
        .ads
        .is_none());
    assert!(AnimationManifest::parse(
        &(MANIFEST.to_owned() + "\nads=unavailable\n"),
        Path::new("assets")
    )
    .is_err());
}

#[test]
fn shared_layer_anchor_survives_an_unavailable_walk_slot() {
    let text = MANIFEST
        .lines()
        .filter(|line| !line.starts_with("regular_walk."))
        .collect::<Vec<_>>()
        .join("\n")
        + "\nregular_walk=unavailable\n";
    let manifest = AnimationManifest::parse(&text, Path::new("assets")).unwrap();
    assert!(manifest.regular_walk.is_none());
    assert_eq!(manifest.layer_anchor_actor, "hk416_weapon");
    let old = MANIFEST
        .lines()
        .filter(|line| !line.starts_with("layers.anchor_actor"))
        .collect::<Vec<_>>()
        .join("\n");
    assert_eq!(
        AnimationManifest::parse(&old, Path::new("assets"))
            .unwrap()
            .layer_anchor_actor,
        "hk416_weapon"
    );
}

#[test]
fn directional_walk_is_optional_and_requires_all_four_declared_clips() {
    let legacy = MANIFEST
        .lines()
        .filter(|line| !line.starts_with("regular_walk.direction."))
        .collect::<Vec<_>>()
        .join("\n");
    assert!(AnimationManifest::parse(&legacy, Path::new("assets"))
        .unwrap()
        .directional_walk
        .is_none());
    let manifest = AnimationManifest::parse(MANIFEST, Path::new("assets")).unwrap();
    assert_eq!(
        manifest.directional_walk.unwrap().names(),
        [
            "hip_walk_forward_r1",
            "hip_walk_backward_r1",
            "hip_strafe_left_r1",
            "hip_strafe_right_r1"
        ]
    );
    assert!(manifest.receiver_ads_wip);
    assert!(manifest.forward_ads_v9_wip);
    assert_eq!(manifest.ads_visual_transition_seconds, Some(0.30));
    let missing = MANIFEST.replace("regular_walk.direction.left=hip_strafe_left_r1", "");
    assert!(AnimationManifest::parse(&missing, Path::new("assets")).is_err());
}
