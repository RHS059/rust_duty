//! The shipped example themes parse through the production parser and resolve
//! the styles their documentation promises.

use vector_range::ui_theme::{UiClass, UiColor, UiScope, UiTheme};

fn example(name: &str) -> UiTheme {
    let path = format!("{}/ui/examples/{name}", env!("CARGO_MANIFEST_DIR"));
    let text = std::fs::read_to_string(&path).unwrap();
    UiTheme::parse(name, &text).unwrap_or_else(|e| panic!("{e}"))
}

fn hex(v: u32) -> UiColor {
    let b = v.to_be_bytes();
    UiColor {
        r: b[0] as f32 / 255.,
        g: b[1] as f32 / 255.,
        b: b[2] as f32 / 255.,
        a: b[3] as f32 / 255.,
    }
}

#[test]
fn high_contrast_resolves_class_and_scoped_colors() {
    let theme = example("high-contrast.css");

    // Class-only rules apply in every scope.
    let label = theme.style(UiScope::PauseMenu, &[UiClass::Label]);
    assert_eq!(label.color, Some(hex(0xffffffff)));
    let warning = theme.style(UiScope::PauseMenu, &[UiClass::Warning]);
    assert_eq!(warning.color, Some(hex(0xff5c5cff)));

    // Scope + class beats class alone.
    let hud_muted = theme.style(UiScope::Hud, &[UiClass::Muted]);
    assert_eq!(hud_muted.color, Some(hex(0xffffffff)));
    let menu_muted = theme.style(UiScope::PauseMenu, &[UiClass::Muted]);
    assert_eq!(menu_muted.color, Some(hex(0xd8d8d8ff)));
    let updater_warning = theme.style(UiScope::UpdaterPanel, &[UiClass::Warning]);
    assert_eq!(updater_warning.color, Some(hex(0xff8a00ff)));
    let hint = theme.style(UiScope::AmmoHint, &[UiClass::Accent]);
    assert_eq!(hint.color, Some(hex(0x00ffffff)));

    let panel = theme.style(UiScope::PauseMenu, &[UiClass::Panel]);
    assert_eq!(panel.background_color, Some(hex(0x000000f2)));
    assert_eq!(panel.border_color, Some(hex(0xffffffff)));
    assert_eq!(panel.border_width, Some(2.0));

    // Several classes combine; each property cascades on its own.
    let button = theme.style(UiScope::PauseMenu, &[UiClass::Label, UiClass::Button]);
    assert_eq!(button.color, Some(hex(0xffffffff)));
    assert_eq!(button.border_color, Some(hex(0xffe100ff)));
    assert_eq!(button.font_size, None, "native font size is kept");
    assert_eq!(button.opacity, None);
}

#[test]
fn large_type_resolves_font_precedence_and_opacity() {
    let theme = example("large-type.css");

    let menu_label = theme.style(UiScope::PauseMenu, &[UiClass::Label]);
    assert_eq!(menu_label.font_size, Some(26.0));
    let menu_button = theme.style(UiScope::PauseMenu, &[UiClass::Label, UiClass::Button]);
    assert_eq!(menu_button.font_size, Some(32.0));
    let updater_button = theme.style(UiScope::UpdaterPanel, &[UiClass::Button]);
    assert_eq!(updater_button.font_size, Some(28.0));

    // Scope alone beats class alone: `#hud` overrides `.label` in the HUD.
    let hud_label = theme.style(UiScope::Hud, &[UiClass::Label]);
    assert_eq!(hud_label.font_size, Some(20.0));
    let hud_muted = theme.style(UiScope::Hud, &[UiClass::Label, UiClass::Muted]);
    assert_eq!(hud_muted.font_size, Some(18.0));
    assert_eq!(hud_muted.opacity, Some(0.9));

    // The ammo hint has no scope-only rule, so `.label` applies there.
    let hint_label = theme.style(UiScope::AmmoHint, &[UiClass::Label]);
    assert_eq!(hint_label.font_size, Some(22.0));
    let hint_key = theme.style(UiScope::AmmoHint, &[UiClass::Accent]);
    assert_eq!(hint_key.font_size, Some(24.0));

    // Typography only: colors stay native.
    assert_eq!(menu_button.color, None);
    assert_eq!(menu_button.background_color, None);
}

#[test]
fn examples_stay_inside_documented_limits() {
    for name in ["high-contrast.css", "large-type.css"] {
        let theme = example(name);
        for scope in [
            UiScope::Hud,
            UiScope::PauseMenu,
            UiScope::UpdaterPanel,
            UiScope::AmmoHint,
        ] {
            for class in [
                UiClass::Panel,
                UiClass::Label,
                UiClass::Muted,
                UiClass::Accent,
                UiClass::Warning,
                UiClass::Button,
                UiClass::Slider,
            ] {
                let s = theme.style(scope, &[class]);
                if let Some(size) = s.font_size {
                    assert!((6.0..=96.0).contains(&size), "{name}: {size}");
                }
                if let Some(width) = s.border_width {
                    assert!((0.0..=16.0).contains(&width), "{name}: {width}");
                }
                if let Some(opacity) = s.opacity {
                    assert!((0.0..=1.0).contains(&opacity), "{name}: {opacity}");
                }
            }
        }
    }
}

#[test]
fn an_edited_example_with_unsupported_css_is_rejected_and_last_good_kept() {
    let good = example("high-contrast.css");
    let path = format!(
        "{}/ui/examples/high-contrast.css",
        env!("CARGO_MANIFEST_DIR")
    );
    let text = std::fs::read_to_string(path).unwrap();

    for (bad, snippet) in [
        ("padding", "\n#hud .label { padding: 4px; }\n"),
        ("pseudo-class", "\n.button:hover { color: #ffffff; }\n"),
        ("function", "\n.label { color: rgb(255, 0, 0); }\n"),
        ("percentage", "\n.label { opacity: 50%; }\n"),
        ("out of range", "\n.label { font-size: 200px; }\n"),
    ] {
        let edited = format!("{text}{snippet}");
        let mut theme = good.clone();
        let err = theme
            .reload_str("high-contrast.css", &edited)
            .expect_err(bad);
        assert_eq!(err.file, "high-contrast.css", "{bad}");
        assert!(err.line > text.lines().count(), "{bad}: {err}");
        assert_eq!(theme, good, "{bad}: last-good theme retained");
    }
}
