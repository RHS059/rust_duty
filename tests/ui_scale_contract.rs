//! Public-API DPI contract for the backend-neutral draw recorder and themed UI
//! adapters at 100/125/150/175/200% scale.
//!
//! Window coordinates are logical pixels and the recorder converts them to the
//! physical frame exactly once; named render targets keep their own pixels.
//! Logical values are chosen so every expected product is exact in `f32`.
//! These CPU checks drive `facade::begin_frame` directly. They do not exercise
//! winit `ScaleFactorChanged`/`CursorMoved`, the private pause-menu layout, or
//! any native OS DPI event, and cannot certify native DPI behavior.

use vector_range::draw::facade::*;
use vector_range::draw::{Camera, Command};
use vector_range::ui_theme::{UiClass, UiScope, UiTheme};

/// (scale factor, label) for 100%, the fractional Windows scales and 200%.
const SCALES: [(f64, &str); 5] = [
    (1.0, "100%"),
    (1.25, "125%"),
    (1.5, "150%"),
    (1.75, "175%"),
    (2.0, "200%"),
];
/// Physical extent that divides exactly by every scale in `SCALES`.
const PHYSICAL: (u32, u32) = (2100, 1050);

fn begin(scale: f64) -> f32 {
    begin_frame(PHYSICAL.0, PHYSICAL.1, scale).unwrap();
    scale as f32
}

fn rects(commands: &[Command]) -> Vec<Rect> {
    commands
        .iter()
        .filter_map(|command| match command {
            Command::Rect { rect, .. } => Some(*rect),
            _ => None,
        })
        .collect()
}

fn meshes(commands: &[Command]) -> Vec<&Mesh> {
    commands
        .iter()
        .filter_map(|command| match command {
            Command::Mesh { mesh, .. } => Some(mesh),
            _ => None,
        })
        .collect()
}

fn texts(commands: &[Command]) -> Vec<(Vec2, f32)> {
    commands
        .iter()
        .filter_map(|command| match command {
            Command::Text { baseline, size, .. } => Some((*baseline, *size)),
            _ => None,
        })
        .collect()
}

fn scaled(rect: Rect, scale: f32) -> Rect {
    Rect::new(
        rect.x * scale,
        rect.y * scale,
        rect.w * scale,
        rect.h * scale,
    )
}

#[test]
fn logical_screen_extent_round_trips_to_the_physical_frame_at_every_scale() {
    for (scale_factor, label) in SCALES {
        let scale = begin(scale_factor);
        let logical = vec2(screen_width(), screen_height());
        assert_eq!(
            logical,
            vec2(PHYSICAL.0 as f32 / scale, PHYSICAL.1 as f32 / scale),
            "{label}: logical extent must divide the physical frame once"
        );
        // A full-window logical rectangle must cover exactly the physical frame:
        // a missing or repeated conversion would under- or over-cover it.
        draw_rectangle(0., 0., logical.x, logical.y, WHITE);
        let list = take_draw_list().unwrap();
        assert_eq!((list.width, list.height), PHYSICAL, "{label}");
        let Some(Command::Camera(screen)) = list.commands.first() else {
            panic!("{label}: frame must start with the screen camera")
        };
        assert_eq!(
            screen.view_projection,
            Camera::screen(PHYSICAL.0, PHYSICAL.1).view_projection,
            "{label}: screen projection must stay in physical pixels"
        );
        assert_eq!(
            rects(&list.commands),
            [Rect::new(0., 0., PHYSICAL.0 as f32, PHYSICAL.1 as f32)],
            "{label}"
        );
    }
}

#[test]
fn window_primitives_scale_logical_coordinates_exactly_once_at_fractional_scales() {
    let texture = Texture2D::rgba8(2, 1, &[255; 8], Sampler::default()).unwrap();
    let mut first_measure = None;
    for (scale_factor, label) in SCALES {
        let scale = begin(scale_factor);
        draw_rectangle(8., 12., 40., 20., WHITE);
        draw_texture_ex(&texture, 4., 8., WHITE, DrawTextureParams::default());
        let measured = measure_text("Ag ", None, 16, 1.);
        let drawn = draw_text("Ag ", 16., 24., 16., WHITE);
        draw_triangle(vec2(4., 8.), vec2(12., 8.), vec2(4., 16.), WHITE);
        draw_circle(40., 40., 8., WHITE);
        draw_rectangle_lines(8., 12., 40., 20., 4., WHITE);
        let list = take_draw_list().unwrap();

        // Text metrics stay logical and identical at every scale.
        assert_eq!(drawn, measured, "{label}");
        assert_eq!(*first_measure.get_or_insert(measured), measured, "{label}");
        assert_eq!(
            rects(&list.commands),
            [scaled(Rect::new(8., 12., 40., 20.), scale)],
            "{label}"
        );
        let sprites: Vec<_> = list
            .commands
            .iter()
            .filter_map(|command| match command {
                Command::Sprite { destination, .. } => Some(*destination),
                _ => None,
            })
            .collect();
        assert_eq!(
            sprites,
            [scaled(Rect::new(4., 8., 2., 1.), scale)],
            "{label}"
        );
        assert_eq!(
            texts(&list.commands),
            [(vec2(16., 24.) * scale, 16. * scale)],
            "{label}"
        );

        let meshes = meshes(&list.commands);
        assert_eq!(meshes.len(), 3, "{label}: triangle, circle, outline");
        let positions = |mesh: &Mesh| -> Vec<Vec3> {
            mesh.vertices.iter().map(|vertex| vertex.position).collect()
        };
        assert_eq!(
            positions(meshes[0]),
            [
                vec3(4. * scale, 8. * scale, 0.),
                vec3(12. * scale, 8. * scale, 0.),
                vec3(4. * scale, 16. * scale, 0.),
            ],
            "{label}: triangle"
        );
        let circle = positions(meshes[1]);
        assert_eq!(circle[0], vec3(40. * scale, 40. * scale, 0.), "{label}");
        assert_eq!(circle[1], vec3(48. * scale, 40. * scale, 0.), "{label}");
        let outline = positions(meshes[2]);
        assert_eq!(outline[0], vec3(8. * scale, 12. * scale, 0.), "{label}");
        assert_eq!(outline[2], vec3(48. * scale, 32. * scale, 0.), "{label}");
        // Thickness is logical too: the inner edge is inset by thickness/2.
        assert_eq!(outline[4], vec3(10. * scale, 14. * scale, 0.), "{label}");
        assert_eq!(outline[6], vec3(46. * scale, 30. * scale, 0.), "{label}");

        // Every scoped screen-mesh camera stays in physical pixels.
        let physical = Camera::screen(PHYSICAL.0, PHYSICAL.1).view_projection;
        for command in &list.commands {
            if let Command::Camera(camera) = command {
                assert!(camera.target.is_none(), "{label}");
                assert_eq!(camera.view_projection, physical, "{label}");
            }
        }
    }
}

#[test]
fn named_target_coordinates_stay_target_local_at_fractional_scales() {
    let source = Texture2D::rgba8(2, 1, &[255; 8], Sampler::default()).unwrap();
    for (scale_factor, label) in SCALES {
        let scale = begin(scale_factor);
        let window = vec2(screen_width(), screen_height());
        let target = RenderTarget::new(320, 200, true).unwrap();
        set_camera(&Camera3D {
            position: vec3(2., 3., 4.),
            target: Vec3::ZERO,
            up: Vec3::Y,
            render_target: Some(target.clone()),
            ..Camera3D::default()
        });
        // The logical window extent does not change while a target is bound.
        assert_eq!(vec2(screen_width(), screen_height()), window, "{label}");
        draw_rectangle(10., 20., 30., 40., WHITE);
        draw_texture_ex(&source, 4., 8., WHITE, DrawTextureParams::default());
        draw_text("A", 5., 6., 16., WHITE);
        draw_triangle(vec2(1., 2.), vec2(3., 4.), vec2(5., 6.), WHITE);
        set_default_camera();
        draw_rectangle(10., 20., 30., 40., WHITE);
        let list = take_draw_list().unwrap();

        assert_eq!(
            rects(&list.commands),
            [
                Rect::new(10., 20., 30., 40.),
                scaled(Rect::new(10., 20., 30., 40.), scale),
            ],
            "{label}: target-local, then window logical-to-physical"
        );
        assert!(
            list.commands.iter().any(|command| matches!(command,
                Command::Sprite { destination, .. } if *destination == Rect::new(4., 8., 2., 1.))),
            "{label}: target sprite must not be DPI scaled"
        );
        assert_eq!(texts(&list.commands), [(vec2(5., 6.), 16.)], "{label}");
        let index = list
            .commands
            .iter()
            .position(|command| matches!(command, Command::Mesh { .. }))
            .expect("target triangle");
        let Command::Camera(scoped) = &list.commands[index - 1] else {
            panic!("{label}: scoped target screen camera missing")
        };
        assert_eq!(
            scoped.target.as_ref().map(|t| t.texture.id),
            Some(target.texture.id),
            "{label}"
        );
        assert!(!scoped.depth_test, "{label}");
        assert_eq!(
            scoped.view_projection,
            Camera::screen(320, 200).view_projection,
            "{label}: target screen projection uses target pixels"
        );
        let Command::Mesh { mesh, .. } = &list.commands[index] else {
            unreachable!()
        };
        assert_eq!(mesh.vertices[0].position, vec3(1., 2., 0.), "{label}");
        assert_eq!(mesh.vertices[2].position, vec3(5., 6., 0.), "{label}");
    }
}

#[test]
fn themed_box_paint_and_inclusive_hit_box_agree_at_fractional_scales() {
    let theme = UiTheme::parse(
        "ui_scale_contract.css",
        "#pause-menu .button {font-size:25.5px;background-color:#123456;border-width:3px}",
    )
    .unwrap();
    let style = theme.style(UiScope::PauseMenu, &[UiClass::Button]);
    let control = Rect::new(10., 20., 60., 30.);
    let fitted = style.fit_text("Resume game", 17., 60.);
    // Logical pointer samples: corners, edges, centre and quarter-pixel misses.
    let pointers = [
        vec2(10., 20.),
        vec2(70., 50.),
        vec2(10., 50.),
        vec2(70., 20.),
        vec2(40., 35.),
        vec2(9.75, 35.),
        vec2(70.25, 35.),
        vec2(40., 19.75),
        vec2(40., 50.25),
    ];
    for (scale_factor, label) in SCALES {
        let scale = begin(scale_factor);
        style.rect(control, WHITE, WHITE, 1.);
        style.text("Resume", 14., 43., 17., WHITE);
        let list = take_draw_list().unwrap();

        let painted = rects(&list.commands);
        assert_eq!(painted.len(), 5, "{label}: background and four borders");
        let background = painted[0];
        assert_eq!(background, scaled(control, scale), "{label}");
        for border in &painted[1..] {
            assert!(
                background.contains(vec2(border.x, border.y))
                    && background.contains(vec2(border.x + border.w, border.y + border.h)),
                "{label}: border {border:?} escapes {background:?}"
            );
        }
        for pointer in pointers {
            assert_eq!(
                control.contains(pointer),
                background.contains(pointer * scale),
                "{label}: logical hit test and physical paint disagree at {pointer:?}"
            );
        }
        // Fractional CSS font size is converted once and fitting stays logical.
        assert_eq!(
            texts(&list.commands),
            [(vec2(14., 43.) * scale, 25.5 * scale)],
            "{label}"
        );
        assert_eq!(style.fit_text("Resume game", 17., 60.), fitted, "{label}");
    }
}
