//! CPU-only production renderer contracts using original tiny fixtures.
//! No private payload, native gameplay capture or artistic equivalence is claimed.
#![allow(dead_code)]
#[path = "../src/authored_viewmodel.rs"]
mod authored_viewmodel;
#[path = "../src/viewmodel_draw.rs"]
mod viewmodel_draw;
#[path = "../src/weapon_model.rs"]
mod weapon_model;
#[path = "../src/world_draw.rs"]
mod world_draw;

use std::path::Path;
use vector_range::{
    animation_manifest::AnimationManifest,
    authored_high_mantle::{ACTION, POLICY},
};

const BASE: &str = "schema=rust-duty-animation-slots/v1
locomotion.asset=locomotion/asset.vra
layers.anchor_actor=hk416_weapon
ready.clip=ready
regular_walk=unavailable
sprint.entry.clip=entry
sprint.loop.clip=loop
sprint.bridges=bridge0,bridge1
sprint.exit.clip=exit
sprint.settle.clip=settle
sprint.response_seconds=0.05
sprint.residual_seconds=0.03
reload.tactical.asset=reload/asset.vra
reload.tactical.clip=reload
reload.empty=unavailable
reload.route=anchored_crossfade
reload.clock=native_complete
ads=unavailable
fire=unavailable
mantle=unavailable
";
fn configured() -> String {
    format!("{BASE}high_mantle.policy={POLICY}\nhigh_mantle.asset=onehand/asset.vra\nhigh_mantle.clip={ACTION}\nhigh_mantle.receipt=onehand/receipt.json\nhigh_mantle.receipt_sha256={}\n", "1".repeat(64))
}
#[test]
fn high_mantle_manifest_is_separate_explicit_and_absent_by_default() {
    assert!(AnimationManifest::parse(BASE, Path::new("assets"))
        .unwrap()
        .high_mantle
        .is_none());
    let manifest = AnimationManifest::parse(&configured(), Path::new("assets")).unwrap();
    let reference = manifest.high_mantle.unwrap();
    assert_eq!(reference.clip, ACTION);
    assert_eq!(reference.asset, Path::new("assets/onehand/asset.vra"));
    assert_eq!(reference.receipt_sha256, "1".repeat(64));
    // The generic action slot cannot silently become low-vault or pull-up.
    assert!(manifest.actions.is_empty());
}
#[test]
fn high_mantle_manifest_rejects_partial_wrong_and_unsafe_bindings() {
    let configured = configured();
    for invalid in [
        configured.replace(POLICY, "low_mantle_native_wip"),
        configured.replace(ACTION, "truncated"),
        configured.replace("onehand/receipt.json", "../receipt.json"),
        configured.replace("onehand/asset.vra", "C:\\asset.vra"),
        configured.replace(&"1".repeat(64), "pending"),
        configured.replace("high_mantle.asset=onehand/asset.vra\n", ""),
        configured.replace("mantle=unavailable", "mantle=high_onto_onehand_v6_native"),
        format!("{configured}\nhigh_mantle.extra=unsupported"),
    ] {
        assert!(
            AnimationManifest::parse(&invalid, Path::new("assets")).is_err(),
            "{invalid}"
        );
    }
}
