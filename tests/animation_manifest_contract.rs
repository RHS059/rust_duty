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
        MANIFEST.replace("whole_model_cut", "crossfade"),
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
