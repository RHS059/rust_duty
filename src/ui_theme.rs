//! Bounded CSS-inspired styling for native UI. No DOM, network, or layout engine.
use crate::draw::{facade, Color, Rect, TextDimensions};
use cssparser::{Parser as CssParser, Token};
use std::{
    cell::RefCell,
    fmt,
    fs::File,
    io::Read,
    path::{Path, PathBuf},
};

pub const MAX_THEME_BYTES: usize = 64 * 1024;
pub const MAX_THEME_RULES: usize = 128;
pub const MAX_THEME_DECLARATIONS: usize = 1024;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum UiScope {
    Hud,
    PauseMenu,
    UpdaterPanel,
    AmmoHint,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum UiClass {
    Panel,
    Label,
    Muted,
    Accent,
    Warning,
    Button,
    Slider,
}
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct UiColor {
    pub r: f32,
    pub g: f32,
    pub b: f32,
    pub a: f32,
}
impl UiColor {
    fn from_bytes(v: [u8; 4]) -> Self {
        Self {
            r: v[0] as f32 / 255.,
            g: v[1] as f32 / 255.,
            b: v[2] as f32 / 255.,
            a: v[3] as f32 / 255.,
        }
    }
}
/// Missing properties deliberately preserve the native caller's existing defaults.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct UiStyle {
    pub color: Option<UiColor>,
    pub background_color: Option<UiColor>,
    pub font_size: Option<f32>,
    pub border_width: Option<f32>,
    pub border_color: Option<UiColor>,
    pub opacity: Option<f32>,
}
impl UiStyle {
    fn overlay(&mut self, other: Self) {
        macro_rules! overlay { ($($field:ident),*) => { $(if other.$field.is_some() { self.$field = other.$field; })* }; }
        overlay!(
            color,
            background_color,
            font_size,
            border_width,
            border_color,
            opacity
        );
    }
}
#[derive(Clone, Debug, PartialEq)]
struct Rule {
    scope: Option<UiScope>,
    class: Option<UiClass>,
    style: UiStyle,
}
impl Rule {
    fn specificity(&self) -> u8 {
        u8::from(self.scope.is_some()) * 100 + u8::from(self.class.is_some())
    }
}
#[derive(Clone, Debug, Default, PartialEq)]
pub struct UiTheme {
    rules: Vec<Rule>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ThemeError {
    pub file: String,
    pub line: usize,
    pub column: usize,
    pub message: String,
}
impl fmt::Display for ThemeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "{}:{}:{}: {}",
            self.file, self.line, self.column, self.message
        )
    }
}
impl std::error::Error for ThemeError {}
impl UiTheme {
    pub fn parse(source_name: &str, text: &str) -> Result<Self, ThemeError> {
        let mut parser = Parser {
            file: source_name,
            text,
            pos: 0,
            declarations: 0,
        };
        if text.len() > MAX_THEME_BYTES {
            return Err(parser.error("theme exceeds 65536 bytes"));
        }
        let mut rules = Vec::new();
        while !parser.done()? {
            if rules.len() == MAX_THEME_RULES {
                return Err(parser.error("theme exceeds 128 rules"));
            }
            rules.push(parser.rule()?);
        }
        Ok(Self { rules })
    }
    pub fn reload_str(&mut self, source_name: &str, text: &str) -> Result<(), ThemeError> {
        let replacement = Self::parse(source_name, text)?;
        *self = replacement;
        Ok(())
    }
    /// Bounded read and atomic replacement. Any I/O, UTF-8, or parse error keeps the old theme.
    pub fn reload_file(&mut self, path: &Path) -> Result<(), ThemeError> {
        let name = path.to_string_lossy();
        let io_error = |message: String| ThemeError {
            file: name.to_string(),
            line: 1,
            column: 1,
            message,
        };
        let file = File::open(path).map_err(|e| io_error(e.to_string()))?;
        let mut bytes = Vec::new();
        file.take(MAX_THEME_BYTES as u64 + 1)
            .read_to_end(&mut bytes)
            .map_err(|e| io_error(e.to_string()))?;
        if bytes.len() > MAX_THEME_BYTES {
            return Err(io_error("theme exceeds 65536 bytes".into()));
        }
        let text = std::str::from_utf8(&bytes).map_err(|e| io_error(e.to_string()))?;
        self.reload_str(&name, text)
    }
    pub fn style(&self, scope: UiScope, classes: &[UiClass]) -> UiStyle {
        let mut result = UiStyle::default();
        // Stable specificity passes preserve source order without allocations per draw.
        for specificity in [1, 100, 101] {
            for rule in &self.rules {
                if rule.specificity() == specificity
                    && rule.scope.is_none_or(|s| s == scope)
                    && rule.class.is_none_or(|c| classes.contains(&c))
                {
                    result.overlay(rule.style);
                }
            }
        }
        result
    }
}
/// The app owns when a theme is loaded/reloaded. Drawing only reads this snapshot.
/// Like the draw recorder, it is local to the native event-loop thread.
#[derive(Default)]
struct ActiveTheme {
    theme: UiTheme,
    path: Option<PathBuf>,
}
thread_local! {
    static ACTIVE_THEME: RefCell<ActiveTheme> = RefCell::new(ActiveTheme::default());
}

/// Remember the requested path even after a failed first load, so reload can retry.
pub fn load_theme(path: &Path) -> Result<(), ThemeError> {
    ACTIVE_THEME.with_borrow_mut(|active| {
        active.path = Some(path.to_owned());
        active.theme.reload_file(path)
    })
}

pub fn reload_theme() -> Result<(), ThemeError> {
    ACTIVE_THEME.with_borrow_mut(|active| {
        let path = active.path.as_deref().ok_or_else(|| ThemeError {
            file: "ui/theme.css".into(),
            line: 1,
            column: 1,
            message: "no UI theme path selected".into(),
        })?;
        active.theme.reload_file(path)
    })
}

/// Install a validated snapshot, e.g. for an embedded theme or CPU-only tests.
pub fn set_theme(theme: UiTheme) {
    ACTIVE_THEME.with_borrow_mut(|active| active.theme = theme);
}

pub fn style(scope: UiScope, classes: &[UiClass]) -> UiStyle {
    ACTIVE_THEME.with_borrow(|active| active.theme.style(scope, classes))
}

impl UiStyle {
    pub fn size(self, default: f32) -> f32 {
        self.font_size.unwrap_or(default)
    }
    pub fn tint(self, default: Color) -> Color {
        self.apply_opacity(self.color.map_or(default, Color::from))
    }
    pub fn background(self, default: Color) -> Color {
        self.apply_opacity(self.background_color.map_or(default, Color::from))
    }
    pub fn apply_opacity(self, mut color: Color) -> Color {
        color.a *= self.opacity.unwrap_or(1.);
        color
    }
    pub fn measure(self, text: &str, default_size: f32) -> TextDimensions {
        // A unit base preserves fractional CSS pixels instead of truncating to u16.
        facade::measure_text(text, None, 1, self.size(default_size))
    }
    pub fn text(self, text: &str, x: f32, y: f32, default_size: f32, color: Color) {
        self.text_scaled(text, x, y, default_size, color, 1.);
    }
    pub fn text_scaled(
        self,
        text: &str,
        x: f32,
        y: f32,
        default_size: f32,
        color: Color,
        scale: f32,
    ) {
        facade::draw_text(
            text,
            x,
            y,
            self.size(default_size) * scale,
            self.tint(color),
        );
    }
    /// Retain a Unicode-safe prefix that fits the same measured font used to draw.
    pub fn fit_text(self, text: &str, default_size: f32, width: f32) -> String {
        let mut result = text.to_owned();
        while self.measure(&result, default_size).width > width.max(0.) {
            if result.pop().is_none() {
                break;
            }
        }
        result
    }
    /// Circular native panels use the same inward-border rule as rectangles.
    pub fn circle(self, center: glam::Vec2, radius: f32, background: Color, border: Color) {
        facade::draw_circle(center.x, center.y, radius, self.background(background));
        let width = self.border_width.unwrap_or(0.).min(radius).max(0.);
        if width == 0. {
            return;
        }
        let color = self.apply_opacity(self.border_color.map_or(border, Color::from));
        for index in 0..80 {
            let a = index as f32 / 80. * std::f32::consts::TAU;
            let b = (index + 1) as f32 / 80. * std::f32::consts::TAU;
            let a = glam::Vec2::new(a.cos(), a.sin());
            let b = glam::Vec2::new(b.cos(), b.sin());
            let outer_a = center + a * radius;
            let outer_b = center + b * radius;
            let inner_a = center + a * (radius - width);
            let inner_b = center + b * (radius - width);
            facade::draw_triangle(outer_a, outer_b, inner_a, color);
            facade::draw_triangle(inner_a, outer_b, inner_b, color);
        }
    }
    /// Borders are painted inward, never outside the shared visual/hit-test box.
    pub fn rect(self, rect: Rect, background: Color, border: Color, scale: f32) {
        facade::draw_rectangle(rect.x, rect.y, rect.w, rect.h, self.background(background));
        let width = (self.border_width.unwrap_or(0.) * scale)
            .min(rect.w * 0.5)
            .min(rect.h * 0.5)
            .max(0.);
        if width == 0. {
            return;
        }
        let color = self.apply_opacity(self.border_color.map_or(border, Color::from));
        facade::draw_rectangle(rect.x, rect.y, rect.w, width, color);
        facade::draw_rectangle(rect.x, rect.y + rect.h - width, rect.w, width, color);
        facade::draw_rectangle(rect.x, rect.y + width, width, rect.h - width * 2., color);
        facade::draw_rectangle(
            rect.x + rect.w - width,
            rect.y + width,
            width,
            rect.h - width * 2.,
            color,
        );
    }
}
impl From<UiColor> for Color {
    fn from(color: UiColor) -> Self {
        Self::new(color.r, color.g, color.b, color.a)
    }
}

/// A native vertical flow band. Larger fonts grow their row and move later rows.
/// No CSS positioning/layout engine is involved. All coordinates, including
/// pointer rectangles, must pass through the same flow and viewport transform.
#[derive(Clone, Copy, Debug)]
pub struct FlowBand {
    start: f32,
    end: f32,
    growth: f32,
}
impl FlowBand {
    pub fn new(start: f32, end: f32, typography: &[(UiStyle, f32)]) -> Self {
        let ratio = typography.iter().fold(1_f32, |ratio, (style, size)| {
            ratio.max(style.size(*size) / size)
        });
        Self {
            start,
            end,
            growth: ratio - 1.,
        }
    }
}
pub fn flow_y(y: f32, bands: &[FlowBand]) -> f32 {
    y + bands
        .iter()
        .map(|band| (y - band.start).clamp(0., band.end - band.start) * band.growth)
        .sum::<f32>()
}

struct Parser<'a> {
    file: &'a str,
    text: &'a str,
    pos: usize,
    declarations: usize,
}
impl Parser<'_> {
    fn error(&self, message: impl Into<String>) -> ThemeError {
        self.error_at(self.pos, message)
    }
    fn error_at(&self, pos: usize, message: impl Into<String>) -> ThemeError {
        let prefix = &self.text[..pos];
        let mut line = 1;
        let mut column = 1;
        let mut previous_cr = false;
        for ch in prefix.chars() {
            match ch {
                '\r' | '\u{c}' => {
                    line += 1;
                    column = 1;
                }
                '\n' => {
                    if !previous_cr {
                        line += 1;
                    }
                    column = 1;
                }
                _ => column += 1,
            }
            previous_cr = ch == '\r';
        }
        ThemeError {
            file: self.file.into(),
            line,
            column,
            message: message.into(),
        }
    }
    fn peek(&self) -> Option<u8> {
        self.text.as_bytes().get(self.pos).copied()
    }
    fn whitespace(&mut self) -> Result<(), ThemeError> {
        loop {
            while self.peek().is_some_and(|b| b.is_ascii_whitespace()) {
                self.pos += 1;
            }
            if !self.text[self.pos..].starts_with("/*") {
                return Ok(());
            }
            let start = self.pos;
            match self.text[self.pos + 2..].find("*/") {
                Some(end) => self.pos += end + 4,
                None => return Err(self.error_at(start, "unterminated comment")),
            }
        }
    }
    fn done(&mut self) -> Result<bool, ThemeError> {
        self.whitespace()?;
        Ok(self.peek().is_none())
    }
    fn expect(&mut self, byte: u8, description: &str) -> Result<(), ThemeError> {
        self.whitespace()?;
        if self.peek() != Some(byte) {
            return Err(self.error(description));
        }
        self.pos += 1;
        Ok(())
    }
    fn ident(&mut self) -> Result<&str, ThemeError> {
        let start = self.pos;
        let (token, length) =
            lex(&self.text[start..]).ok_or_else(|| self.error("expected identifier"))?;
        if !matches!(token, Token::Ident(_))
            || !self.text[start..start + length]
                .bytes()
                .all(|b| b.is_ascii_lowercase() || b == b'-')
        {
            return Err(self.error("expected a lowercase identifier; escapes are unsupported"));
        }
        self.pos += length;
        Ok(&self.text[start..self.pos])
    }
    fn rule(&mut self) -> Result<Rule, ThemeError> {
        let mut scope = None;
        let mut class = None;
        if self.peek() == Some(b'#') {
            self.pos += 1;
            let start = self.pos;
            scope = Some(match self.ident()? {
                "hud" => UiScope::Hud,
                "pause-menu" => UiScope::PauseMenu,
                "updater-panel" => UiScope::UpdaterPanel,
                "ammo-hint" => UiScope::AmmoHint,
                _ => return Err(self.error_at(start, "unsupported UI scope")),
            });
            self.whitespace()?;
        }
        if self.peek() == Some(b'.') {
            self.pos += 1;
            let start = self.pos;
            class = Some(match self.ident()? {
                "panel" => UiClass::Panel,
                "label" => UiClass::Label,
                "muted" => UiClass::Muted,
                "accent" => UiClass::Accent,
                "warning" => UiClass::Warning,
                "button" => UiClass::Button,
                "slider" => UiClass::Slider,
                _ => return Err(self.error_at(start, "unsupported UI class")),
            });
        }
        if scope.is_none() && class.is_none() {
            return Err(self.error("unsupported selector or at-rule"));
        }
        self.expect(
            b'{',
            "expected '{'; selector lists, combinators, and pseudo-selectors are unsupported",
        )?;
        let mut style = UiStyle::default();
        loop {
            self.whitespace()?;
            if self.peek() == Some(b'}') {
                self.pos += 1;
                break;
            }
            if self.declarations == MAX_THEME_DECLARATIONS {
                return Err(self.error("theme exceeds 1024 declarations"));
            }
            self.declarations += 1;
            let property_start = self.pos;
            let property = self.ident()?.to_owned();
            self.expect(b':', "expected ':' after property")?;
            self.whitespace()?;
            let value_start = self.pos;
            // cssparser owns tokenization. The whitelist below deliberately rejects
            // functions, URLs, escapes, percentages, CSS-wide keywords and expressions.
            let (token, length) = lex(&self.text[value_start..])
                .ok_or_else(|| self.error("expected property value"))?;
            if !matches!(
                token,
                Token::Hash(_)
                    | Token::IDHash(_)
                    | Token::Ident(_)
                    | Token::Number { .. }
                    | Token::Dimension { .. }
            ) {
                return Err(self.error("unsupported value token; functions and URLs are forbidden"));
            }
            self.pos += length;
            let value = &self.text[value_start..self.pos];
            let invalid = || self.error_at(value_start, format!("invalid value for {property}"));
            match property.as_str() {
                "color" => style.color = Some(parse_color(value).ok_or_else(invalid)?),
                "background-color" => {
                    style.background_color = Some(parse_color(value).ok_or_else(invalid)?)
                }
                "border-color" => {
                    style.border_color = Some(parse_color(value).ok_or_else(invalid)?)
                }
                "font-size" => {
                    style.font_size = Some(parse_px(value, 6., 96.).ok_or_else(invalid)?)
                }
                "border-width" => {
                    style.border_width = Some(parse_px(value, 0., 16.).ok_or_else(invalid)?)
                }
                "opacity" => style.opacity = Some(parse_number(value, 0., 1.).ok_or_else(invalid)?),
                _ => {
                    return Err(
                        self.error_at(property_start, format!("unsupported property '{property}'"))
                    )
                }
            }
            self.whitespace()?;
            match self.peek() {
                Some(b';') => self.pos += 1,
                Some(b'}') => {}
                _ => return Err(self.error(
                    "expected ';' or '}'; functions and additional value tokens are unsupported",
                )),
            }
        }
        Ok(Rule {
            scope,
            class,
            style,
        })
    }
}
/// Read one token only: explicit structure handling above rejects CSS's usual
/// implicit closing/recovery rules instead of silently accepting broken files.
fn lex(text: &str) -> Option<(Token<'_>, usize)> {
    let mut parser = CssParser::new(text);
    let token = parser
        .next_including_whitespace_and_comments()
        .ok()?
        .clone();
    Some((token, parser.position().byte_index()))
}
fn parse_number(text: &str, min: f32, max: f32) -> Option<f32> {
    if text.is_empty() || !text.bytes().all(|b| b.is_ascii_digit() || b == b'.') {
        return None;
    }
    let number: f64 = text.parse().ok()?;
    (number.is_finite() && number >= f64::from(min) && number <= f64::from(max))
        .then_some(number as f32)
}
fn parse_px(text: &str, min: f32, max: f32) -> Option<f32> {
    parse_number(text.strip_suffix("px")?, min, max)
}
fn parse_color(text: &str) -> Option<UiColor> {
    if text == "transparent" {
        return Some(UiColor::from_bytes([0, 0, 0, 0]));
    }
    let hex = text.strip_prefix('#')?;
    if !hex.bytes().all(|b| b.is_ascii_hexdigit()) {
        return None;
    }
    let mut bytes = [0, 0, 0, 255];
    match hex.len() {
        3 | 4 => {
            for (i, c) in hex.bytes().enumerate() {
                bytes[i] = (c as char).to_digit(16)? as u8 * 17;
            }
        }
        6 | 8 => {
            for (i, pair) in hex.as_bytes().as_chunks::<2>().0.iter().enumerate() {
                bytes[i] = u8::from_str_radix(std::str::from_utf8(pair).ok()?, 16).ok()?;
            }
        }
        _ => return None,
    }
    Some(UiColor::from_bytes(bytes))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn parse(text: &str) -> UiTheme {
        UiTheme::parse("test.css", text).unwrap()
    }
    #[test]
    fn empty_theme_preserves_all_native_defaults() {
        assert_eq!(
            parse("/* optional theme */").style(UiScope::Hud, &[UiClass::Label]),
            UiStyle::default()
        );
    }
    #[test]
    fn cascade_is_property_specific_with_source_order_tiebreak() {
        let theme = parse("#hud .label {color:#abc; opacity:.5} .label {color:#fff; font-size:20px} #hud {color:#123456} #hud.label {color:#abcd} #hud.label {opacity:.8}");
        let style = theme.style(UiScope::Hud, &[UiClass::Label]);
        assert_eq!(style.color, parse_color("#abcd"));
        assert_eq!(style.opacity, Some(0.8));
        assert_eq!(style.font_size, Some(20.));
        assert_eq!(
            theme.style(UiScope::PauseMenu, &[UiClass::Label]).color,
            parse_color("#fff")
        );
    }
    #[test]
    fn parses_every_scope_class_and_property() {
        for scope in ["hud", "pause-menu", "updater-panel", "ammo-hint"] {
            for class in [
                "panel", "label", "muted", "accent", "warning", "button", "slider",
            ] {
                parse(&format!("#{scope} .{class} {{color:#01020304;background-color:transparent;font-size:96px;border-width:16px;border-color:#ABCDEF;opacity:0}}"));
            }
        }
    }
    #[test]
    fn unsupported_features_fail_closed() {
        for css in [
            "@import 'https://example.com';",
            "@media screen {}",
            "* {}",
            "button {}",
            "#other {}",
            ".unknown {}",
            ".label:hover {}",
            ".label,.panel {}",
            "#hud > .label {}",
            ".label.accent {}",
            "#hud {padding:2px}",
            "#hud {color:rgb(0,0,0)}",
            "#hud {background-color:url(x)}",
            "#hud {color:var(--x)}",
            "#hud {opacity:inherit}",
            "#hud {color:#fff!important}",
            "#hud {color:#fff;",
            "/* unclosed",
            "#hud {opacity:1/*comment*/0}",
            "#hud {opacity:1} trailing",
            "#hud {color:#fff} 💣",
        ] {
            assert!(UiTheme::parse("bad.css", css).is_err(), "accepted {css}");
        }
    }
    #[test]
    fn numeric_and_color_validation() {
        for (name, values) in [
            (
                "font-size",
                vec!["5px", "97px", "NaNpx", "1e2px", "12", "12em", "-1px"],
            ),
            ("border-width", vec!["17px", "-1px", "infpx"]),
            (
                "opacity",
                vec!["NaN", "inf", "1.01", "-0.1", "1e0", "1..0", "."],
            ),
            ("color", vec!["#12", "#xyz", "#12345", "#123456789"]),
        ] {
            for value in values {
                assert!(
                    UiTheme::parse("bad.css", &format!("#hud {{{name}:{value}}}")).is_err(),
                    "accepted {name}:{value}"
                );
            }
        }
        parse("#hud {font-size:6px; border-width:0px; opacity:1}");
    }
    #[test]
    fn error_reports_file_line_and_column() {
        let error =
            UiTheme::parse("ui/theme.css", "/* hello */\n#hud {\n  padding: 2px;\n}").unwrap_err();
        assert_eq!((error.line, error.column), (3, 3));
        assert!(error.to_string().starts_with("ui/theme.css:3:3:"));
        let error = UiTheme::parse("x", "/* 🦀 */\n#hud { opacity: 2 }").unwrap_err();
        assert_eq!((error.line, error.column), (2, 17));
    }
    #[test]
    fn reload_is_atomic_for_parse_and_io_errors() {
        let mut theme = parse("#hud {color:#fff}");
        let original = theme.clone();
        assert!(theme
            .reload_str("new.css", "#hud {color:#000} .label {opacity:NaN}")
            .is_err());
        assert_eq!(theme, original);
        assert!(theme
            .reload_file(Path::new(
                "/nonexistent-rust-duty-theme-directory/theme.css"
            ))
            .is_err());
        assert_eq!(theme, original);
        theme.reload_str("new.css", "#hud {color:#000}").unwrap();
        assert_ne!(theme, original);
    }
    #[test]
    fn bounded_file_reload_keeps_last_good_on_encoding_size_and_syntax_errors() {
        let path = std::env::temp_dir().join(format!(
            "rust-duty-theme-{}-{}.css",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let mut theme = parse("#hud {color:#fff}");
        let original = theme.clone();
        for bytes in [
            vec![0xff],
            vec![b' '; MAX_THEME_BYTES + 1],
            b"#hud { opacity: 4 }".to_vec(),
        ] {
            std::fs::write(&path, bytes).unwrap();
            assert!(theme.reload_file(&path).is_err());
            assert_eq!(theme, original);
        }
        std::fs::write(&path, "#hud {color:#000}").unwrap();
        theme.reload_file(&path).unwrap();
        assert_ne!(theme, original);
        std::fs::remove_file(path).unwrap();
    }
    #[test]
    fn class_order_does_not_change_cascade_and_duplicate_property_last_wins() {
        let theme = parse(".warning {opacity:.1;opacity:.2} .accent {opacity:.3}");
        assert_eq!(
            theme.style(UiScope::Hud, &[UiClass::Warning]).opacity,
            Some(0.2)
        );
        let a = theme.style(UiScope::Hud, &[UiClass::Warning, UiClass::Accent]);
        let b = theme.style(UiScope::Hud, &[UiClass::Accent, UiClass::Warning]);
        assert_eq!(a, b);
        assert_eq!(a.opacity, Some(0.3));
    }
    #[test]
    fn resource_limits_are_enforced() {
        assert!(UiTheme::parse("x", &" ".repeat(MAX_THEME_BYTES + 1)).is_err());
        parse(&".label {}".repeat(MAX_THEME_RULES));
        assert!(UiTheme::parse("x", &".label {}".repeat(MAX_THEME_RULES + 1)).is_err());
        parse(&format!(
            "#hud {{{}}}",
            "opacity:1;".repeat(MAX_THEME_DECLARATIONS)
        ));
        assert!(UiTheme::parse(
            "x",
            &format!(
                "#hud {{{}}}",
                "opacity:1;".repeat(MAX_THEME_DECLARATIONS + 1)
            )
        )
        .is_err());
    }
    #[test]
    fn diagnostics_count_unicode_and_all_css_line_endings() {
        for newline in ["\n", "\r\n", "\r", "\u{c}"] {
            let error = UiTheme::parse(
                "line.css",
                &format!("/* 🦀 */{newline}#hud {{{newline}  opacity: 2;}}"),
            )
            .unwrap_err();
            assert_eq!((error.line, error.column), (3, 12), "{newline:?}");
        }
        let error = UiTheme::parse("unicode.css", "/* 🦀 */ #hud { oops: 1 }").unwrap_err();
        assert_eq!((error.line, error.column), (1, 16));
    }
    #[test]
    fn active_reload_retries_failed_first_path_and_preserves_complete_last_good() {
        let path = std::env::temp_dir().join(format!(
            "native-ui-reload-{}.css",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        set_theme(parse("#hud {color:#abc;opacity:.5}"));
        let old = style(UiScope::Hud, &[UiClass::Label]);
        assert!(load_theme(&path).is_err());
        assert_eq!(style(UiScope::Hud, &[UiClass::Label]), old);
        std::fs::write(&path, "#hud {font-size:25.5px;opacity:.2}").unwrap();
        reload_theme().unwrap();
        let new = style(UiScope::Hud, &[UiClass::Label]);
        assert_eq!(new.font_size, Some(25.5));
        assert_eq!(
            new.color, None,
            "replacement must not merge stale properties"
        );
        std::fs::write(&path, "#hud{color:#000} .label:hover{}").unwrap();
        assert!(reload_theme().is_err());
        assert_eq!(style(UiScope::Hud, &[UiClass::Label]), new);
        std::fs::remove_file(path).unwrap();
        ACTIVE_THEME.with_borrow_mut(|active| *active = ActiveTheme::default());
    }
    #[test]
    fn native_adapter_draws_measured_fractional_font_and_inset_border() {
        use crate::draw::Command;
        let style = parse(".button {font-size:25.5px;color:#f008;background-color:#1234;border-width:16px;border-color:#fff;opacity:.5}")
            .style(UiScope::PauseMenu, &[UiClass::Button]);
        let rect = Rect::new(10., 20., 60., 30.);
        facade::begin_frame(320, 240, 1.).unwrap();
        style.rect(rect, Color::WHITE, Color::WHITE, 1.);
        style.text("Test", 14., 43., 17., Color::WHITE);
        let list = facade::take_draw_list().unwrap();
        let mut painted = 0;
        for command in list.commands {
            match command {
                Command::Rect {
                    rect: actual,
                    color,
                } => {
                    assert!(rect.contains(glam::Vec2::new(actual.x, actual.y)));
                    assert!(
                        rect.contains(glam::Vec2::new(actual.x + actual.w, actual.y + actual.h))
                    );
                    assert!(color.a <= 0.5);
                    painted += 1;
                }
                Command::Text {
                    size, color, text, ..
                } => {
                    assert_eq!(size, 25.5);
                    assert_eq!(color, Color::new(1., 0., 0., (136. / 255.) * 0.5));
                    assert_eq!(
                        style.measure(&text, 17.),
                        facade::measure_text(&text, None, 1, size)
                    );
                }
                _ => {}
            }
        }
        assert_eq!(painted, 5);
    }
    #[test]
    fn native_flow_grows_rows_and_keeps_following_rows_disjoint() {
        let style = UiStyle {
            font_size: Some(40.),
            ..UiStyle::default()
        };
        let bands = [
            FlowBand::new(10., 40., &[(style, 20.)]),
            FlowBand::new(60., 90., &[(style, 20.)]),
        ];
        assert_eq!(flow_y(10., &bands), 10.);
        assert_eq!(flow_y(40., &bands), 70.);
        assert_eq!(flow_y(60., &bands), 90.);
        assert_eq!(flow_y(90., &bands), 150.);
        assert_eq!(flow_y(120., &bands), 180.);
        let plain = [FlowBand::new(10., 40., &[(UiStyle::default(), 20.)])];
        for y in [0., 10., 25., 40., 200.] {
            assert_eq!(flow_y(y, &plain), y);
        }
    }
    #[test]
    fn native_text_fitting_uses_the_resolved_font_without_splitting_unicode() {
        let style = UiStyle {
            font_size: Some(30.5),
            ..UiStyle::default()
        };
        let expected = "Ré";
        let width = style.measure(expected, 17.).width;
        assert_eq!(style.fit_text("Rétry update", 17., width), expected);
        assert_eq!(style.fit_text("Retry", 17., 0.), "");
    }
}
