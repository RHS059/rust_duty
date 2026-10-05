//! Action slot bindings in the semantic animation manifest.
use std::path::Path;
use vector_range::{
    action::{ActionSlot, ActionTimings},
    animation_manifest::AnimationManifest,
};

fn shipped() -> String {
    std::fs::read_to_string(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/assets/animations.cfg"
    ))
    .unwrap()
}
fn with(replace: &str, lines: &str) -> String {
    shipped().replace(&format!("{replace}\n"), &format!("{lines}\n"))
}

#[test]
fn shipped_manifest_declares_every_action_slot_unavailable() {
    let text = shipped();
    for slot in ActionSlot::ALL {
        assert!(
            text.contains(&format!("action.{}=unavailable\n", slot.name())),
            "{}",
            slot.name()
        );
    }
    let manifest = AnimationManifest::parse(&text, Path::new("assets")).unwrap();
    assert!(manifest.actions.is_empty());
    let mut timings = ActionTimings::default();
    manifest
        .bind_action_timings(&mut timings, |_, _| panic!("nothing bound"))
        .unwrap();
    assert!(timings.get(ActionSlot::PullUp).placeholder);
}

#[test]
fn bound_clip_retimes_gameplay_from_its_duration_and_events() {
    let text = with(
        "action.pistol_draw=unavailable",
        "action.pistol_draw.asset=hang/asset.vra\naction.pistol_draw.clip=draw_r1\naction.pistol_draw.events=release_grip:0.2,pistol_in_hand:0.5,ready:0.9",
    );
    let manifest = AnimationManifest::parse(&text, Path::new("assets")).unwrap();
    let binding = &manifest.actions[&ActionSlot::PistolDraw];
    assert_eq!(binding.asset, Path::new("assets/hang/asset.vra"));
    let mut timings = ActionTimings::default();
    manifest
        .bind_action_timings(&mut timings, |asset, clip| {
            assert_eq!(
                (asset, clip),
                (Path::new("assets/hang/asset.vra"), "draw_r1")
            );
            Ok(0.8)
        })
        .unwrap();
    let clip = timings.get(ActionSlot::PistolDraw);
    assert!(!clip.placeholder);
    assert!((clip.event_seconds("ready") - 0.72).abs() < 1e-6);
    // Missing clips fail visibly instead of silently keeping placeholders.
    let mut timings = ActionTimings::default();
    assert!(manifest
        .bind_action_timings(&mut timings, |_, _| Err("missing clip".into()))
        .is_err());
}

#[test]
fn malformed_action_bindings_are_rejected() {
    for (replace, lines) in [
        ("action.slide_enter=unavailable", "action.slid_enter=unavailable"),
        ("action.slide_enter=unavailable", "action.slide_enter=maybe"),
        (
            "action.slide_enter=unavailable",
            "action.slide_enter.asset=../escape.vra\naction.slide_enter.clip=a",
        ),
        (
            "action.slide_enter=unavailable",
            "action.slide_enter.asset=a.vra\naction.slide_enter.clip=a\naction.slide_enter.events=x:1.5",
        ),
        (
            "action.slide_enter=unavailable",
            "action.slide_enter.asset=a.vra\naction.slide_enter.clip=a\naction.slide_enter.events=x",
        ),
    ] {
        let text = with(replace, lines);
        assert!(
            AnimationManifest::parse(&text, Path::new("assets")).is_err(),
            "{lines}"
        );
    }
}
