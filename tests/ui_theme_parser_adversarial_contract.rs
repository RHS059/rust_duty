//! Missing parser boundary cases through the public API. Basic selector,
//! cascade, numeric, color and reload coverage already lives with the parser.
use vector_range::ui_theme::{UiClass, UiScope, UiStyle, UiTheme, MAX_THEME_BYTES};

#[test]
fn utf8_comment_budget_counts_bytes_with_an_exact_limit_control() {
    let at_limit = format!("/*{}*/", "🦀".repeat((MAX_THEME_BYTES - 4) / 4));
    assert_eq!(at_limit.len(), MAX_THEME_BYTES);
    assert!(at_limit.chars().count() < MAX_THEME_BYTES);
    let empty = UiTheme::parse("exact-limit.css", &at_limit).unwrap();
    assert_eq!(
        empty.style(UiScope::Hud, &[UiClass::Label]),
        UiStyle::default()
    );

    let mut theme = UiTheme::parse("good.css", "#hud {opacity:.25}").unwrap();
    let before = theme.clone();
    let over_limit = format!("{at_limit}\n");
    let error = theme
        .reload_str("one-byte-over.css", &over_limit)
        .unwrap_err();
    assert_eq!(error.file, "one-byte-over.css");
    assert!(error.message.contains("65536 bytes"));
    assert_eq!(theme, before);
}

#[test]
fn comment_delimiters_do_not_nest_or_hide_a_trailing_invalid_rule() {
    // A second opening delimiter is literal comment text. The first closing
    // delimiter ends the comment; trailing text still has to parse normally.
    let control = UiTheme::parse(
        "literal-opener.css",
        "/* outer /* literal opener */ #hud {opacity:.25}",
    )
    .unwrap();
    assert_eq!(
        control.style(UiScope::Hud, &[UiClass::Label]).opacity,
        Some(0.25)
    );
    for invalid in [
        "/* outer /* nested */ */ #hud {opacity:.5}",
        "/* closed */ #hud {opacity:.5} /* unclosed",
        "/* closed */ #hud {opacity:.5} .label:hover {}",
    ] {
        let mut theme = control.clone();
        assert!(theme.reload_str("invalid-comment.css", invalid).is_err());
        assert_eq!(theme, control, "{invalid}");
    }
}
