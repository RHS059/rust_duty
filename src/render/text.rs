//! CPU-only text rasterization into the provisional backend-neutral draw contract.
//!
//! Uses the legacy default font, but no macroquad context or GPU resources. Each
//! cached glyph has an immutable texture ID so a backend uploads it only once.
//! Callers supply physical-pixel sizes and baselines, including their DPI scale;
//! rasterization happens at that size rather than stretching a lower-DPI bitmap.

use crate::draw::{Color, Mesh, Sampler, TextDimensions, Texture, Vertex};
use fontdue::{Font, FontSettings, Metrics};
use glam::Vec2;
use std::collections::HashMap;

const FONT_BYTES: &[u8] = include_bytes!("font/ProggyClean.ttf");
const MAX_SIZE_PX: f32 = 1024.0;
const MAX_CACHED_GLYPHS: usize = 4096;
const MAX_CACHE_BYTES: usize = 32 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
struct GlyphKey {
    index: u16,
    size_bits: u32,
}

struct CachedGlyph {
    metrics: Metrics,
    texture: Option<Texture>,
}

/// Single-line text with macroquad's advance-width and baseline semantics.
///
/// Kerning, shaping and multiline layout are deliberately not added here: the
/// legacy `draw_text` walks Unicode scalar values and advances by each glyph's
/// advance width. Missing characters use the font's missing-glyph fallback.
///
/// The initial port uses per-glyph textures, bounded by 4096 glyph/size pairs
/// and 32 MiB of RGBA data. It returns an explicit error at that limit rather
/// than churn resource IDs that an otherwise persistent GPU cache would retain.
/// A packed atlas can replace this storage without changing callers.
pub struct TextRenderer {
    font: Font,
    glyphs: HashMap<GlyphKey, CachedGlyph>,
    cache_bytes: usize,
}

impl TextRenderer {
    pub fn new() -> Result<Self, String> {
        let font = Font::from_bytes(FONT_BYTES, FontSettings::default())
            .map_err(|error| format!("cannot load embedded text font: {error}"))?;
        Ok(Self {
            font,
            glyphs: HashMap::new(),
            cache_bytes: 0,
        })
    }

    /// Measures a single line in physical pixels. `offset_y` is the distance
    /// from its baseline to the top; descenders extend below the baseline.
    /// Width includes whitespace advances, exactly like legacy macroquad.
    /// Empty text and invalid sizes return zero dimensions without rasterizing.
    pub fn measure_text(&self, text: &str, size: f32) -> TextDimensions {
        if text.is_empty() || validate_size(size).is_err() {
            return TextDimensions::default();
        }
        let mut width = 0.0;
        let mut bottom = f32::INFINITY;
        let mut top = f32::NEG_INFINITY;
        for character in text.chars() {
            let key = self.key(character, size);
            let metrics = self.glyphs.get(&key).map_or_else(
                || self.font.metrics_indexed(key.index, size),
                |glyph| glyph.metrics,
            );
            width += metrics.advance_width;
            bottom = bottom.min(metrics.ymin as f32);
            top = top.max(metrics.ymin as f32 + metrics.height as f32);
        }
        TextDimensions {
            width,
            height: top - bottom,
            offset_y: top,
        }
    }

    /// Builds alpha-blended textured quads in top-left-origin screen space.
    /// Whitespace advances the pen without allocating a zero-extent texture.
    pub fn meshes(
        &mut self,
        text: &str,
        baseline: Vec2,
        size: f32,
        color: Color,
    ) -> Result<Vec<Mesh>, String> {
        validate_size(size)?;
        if !baseline.is_finite()
            || ![color.r, color.g, color.b, color.a]
                .iter()
                .all(|c| c.is_finite())
        {
            return Err("text baseline and color must be finite".into());
        }
        let mut meshes = Vec::new();
        let mut advance = 0.0;
        for character in text.chars() {
            let key = self.key(character, size);
            self.cache_glyph(key, size)?;
            let glyph = &self.glyphs[&key];
            let metrics = glyph.metrics;
            if let Some(texture) = &glyph.texture {
                let left = baseline.x + advance + metrics.xmin as f32;
                let top = baseline.y - metrics.ymin as f32 - metrics.height as f32;
                let right = left + metrics.width as f32;
                let bottom = top + metrics.height as f32;
                let mesh = Mesh {
                    vertices: vec![
                        Vertex::new(left, top, 0.0, 0.0, 0.0, color),
                        Vertex::new(right, top, 0.0, 1.0, 0.0, color),
                        Vertex::new(right, bottom, 0.0, 1.0, 1.0, color),
                        Vertex::new(left, bottom, 0.0, 0.0, 1.0, color),
                    ],
                    indices: vec![0, 1, 2, 0, 2, 3],
                    texture: Some(texture.clone()),
                };
                mesh.validate()?;
                meshes.push(mesh);
            }
            advance += metrics.advance_width;
            if !advance.is_finite() {
                return Err("text advance exceeds finite screen coordinates".into());
            }
        }
        Ok(meshes)
    }

    fn key(&self, character: char, size: f32) -> GlyphKey {
        GlyphKey {
            index: self.font.lookup_glyph_index(character),
            size_bits: size.to_bits(),
        }
    }

    fn cache_glyph(&mut self, key: GlyphKey, size: f32) -> Result<(), String> {
        if self.glyphs.contains_key(&key) {
            return Ok(());
        }
        if self.glyphs.len() >= MAX_CACHED_GLYPHS {
            return Err("text glyph cache reached its 4096-entry limit".into());
        }
        // Check the extent and budget before the rasterizer allocates a bitmap.
        let metrics = self.font.metrics_indexed(key.index, size);
        let bytes = metrics
            .width
            .checked_mul(metrics.height)
            .and_then(|pixels| pixels.checked_mul(4))
            .ok_or("text glyph extent overflow")?;
        if bytes > MAX_CACHE_BYTES - self.cache_bytes {
            return Err("text glyph cache reached its 32 MiB limit".into());
        }
        let texture = if bytes == 0 {
            None
        } else {
            let (_, bitmap) = self.font.rasterize_indexed(key.index, size);
            let mut rgba = Vec::with_capacity(bytes);
            for alpha in bitmap {
                // Straight alpha: coverage lives only in alpha; the mesh tint
                // controls RGB. Black RGB would make all tinted text black.
                rgba.extend_from_slice(&[255, 255, 255, alpha]);
            }
            Some(Texture::rgba8(
                metrics.width as u32,
                metrics.height as u32,
                &rgba,
                Sampler::default(),
            )?)
        };
        self.glyphs.insert(key, CachedGlyph { metrics, texture });
        self.cache_bytes += bytes;
        Ok(())
    }
}

pub(crate) fn validate_size(size: f32) -> Result<(), String> {
    if !size.is_finite() || size <= 0.0 || size > MAX_SIZE_PX {
        return Err("text size must be finite, positive and at most 1024 physical pixels".into());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::draw::{FilterMode, TextureSource, WrapMode};
    use std::sync::Arc;

    fn renderer() -> TextRenderer {
        TextRenderer::new().expect("embedded, licensed font is valid")
    }

    #[test]
    fn legacy_default_font_baseline_and_advance_goldens() {
        let mut renderer = renderer();
        // These are fixed ProggyClean metrics at its 16px design size, not
        // expectations recomputed by the implementation under test.
        let expected = TextDimensions {
            width: 21.0,
            height: 11.0,
            offset_y: 8.0,
        };
        assert_eq!(renderer.measure_text("Ag ", 16.0), expected);
        let meshes = renderer
            .meshes("Ag ", Vec2::new(10.0, 20.0), 16.0, Color::WHITE)
            .unwrap();
        assert_eq!(meshes.len(), 2);
        assert_eq!(meshes[0].vertices[0].position, glam::vec3(11.0, 12.0, 0.0));
        assert_eq!(meshes[0].vertices[2].position, glam::vec3(17.0, 20.0, 0.0));
        assert_eq!(meshes[1].vertices[0].position, glam::vec3(18.0, 14.0, 0.0));
        assert_eq!(meshes[1].vertices[2].position, glam::vec3(23.0, 23.0, 0.0));
        assert_eq!(meshes[0].vertices[0].uv, Vec2::ZERO);
        assert_eq!(meshes[0].vertices[2].uv, Vec2::ONE);
        assert_eq!(renderer.measure_text("Ag ", 16.0), expected);
        // Like draw_text (as distinct from draw_multiline_text), a newline
        // does not implement a line break or change the supplied baseline.
        assert_eq!(renderer.measure_text("A\ng", 16.0), expected);
        let newline = renderer
            .meshes("A\ng", Vec2::new(10.0, 20.0), 16.0, Color::WHITE)
            .unwrap();
        assert_eq!(newline[1].vertices[0].position, glam::vec3(25.0, 14.0, 0.0));
    }

    #[test]
    fn two_hundred_percent_dpi_rasterizes_full_resolution() {
        let mut renderer = renderer();
        let dimensions = renderer.measure_text("Ag ", 32.0);
        assert_eq!(
            dimensions,
            TextDimensions {
                width: 42.0,
                height: 22.0,
                offset_y: 16.0
            }
        );
        let one = renderer
            .meshes("Ag", Vec2::new(10.0, 20.0), 16.0, Color::WHITE)
            .unwrap();
        let two = renderer
            .meshes("Ag", Vec2::new(20.0, 40.0), 32.0, Color::WHITE)
            .unwrap();
        for (low, high) in one.iter().zip(&two) {
            for (low_vertex, high_vertex) in low.vertices.iter().zip(&high.vertices) {
                assert_eq!(high_vertex.position, low_vertex.position * 2.0);
            }
            let low_texture = low.texture.as_ref().unwrap();
            let high_texture = high.texture.as_ref().unwrap();
            assert_ne!(low_texture.id, high_texture.id);
            assert_eq!(high_texture.width, low_texture.width * 2);
            assert_eq!(high_texture.height, low_texture.height * 2);
        }
    }

    #[test]
    fn empty_and_whitespace_do_not_create_invalid_textures() {
        let mut renderer = renderer();
        assert_eq!(renderer.measure_text("", 13.0), TextDimensions::default());
        assert!(renderer
            .meshes("", Vec2::ZERO, 13.0, Color::WHITE)
            .unwrap()
            .is_empty());
        assert!(renderer.glyphs.is_empty());
        assert!(renderer
            .meshes("   ", Vec2::ZERO, 13.0, Color::WHITE)
            .unwrap()
            .is_empty());
        assert!(renderer.measure_text("   ", 13.0).width > 0.0);
        assert_eq!(renderer.cache_bytes, 0);
        assert_eq!(renderer.glyphs.len(), 1);
    }

    #[test]
    fn cached_textures_reuse_ids_and_immutable_rgba_across_tints() {
        let mut renderer = renderer();
        let tint = Color::new(0.25, 0.5, 0.75, 0.8);
        let first = renderer.meshes("AA", Vec2::ZERO, 13.0, tint).unwrap();
        let second = renderer
            .meshes("A", Vec2::new(23.0, 50.0), 13.0, Color::WHITE)
            .unwrap();
        assert_eq!(first.len(), 2);
        assert_eq!(second.len(), 1);
        let a = first[0].texture.as_ref().unwrap();
        let b = first[1].texture.as_ref().unwrap();
        let c = second[0].texture.as_ref().unwrap();
        assert_eq!(a.id, b.id);
        assert_eq!(a.id, c.id);
        assert_eq!(renderer.glyphs.len(), 1);
        assert_eq!(a.sampler.filter, FilterMode::Linear);
        assert_eq!(a.sampler.wrap_x, WrapMode::Clamp);
        assert_eq!(a.sampler.wrap_y, WrapMode::Clamp);
        let (TextureSource::Rgba8(bytes_a), TextureSource::Rgba8(bytes_c)) = (&a.source, &c.source)
        else {
            panic!("glyph textures must contain CPU RGBA bytes");
        };
        assert!(Arc::ptr_eq(bytes_a, bytes_c));
        assert_eq!(bytes_a.len(), a.width as usize * a.height as usize * 4);
        assert!(bytes_a
            .as_chunks::<4>()
            .0
            .iter()
            .all(|px| px[..3] == [255; 3]));
        assert!(bytes_a.as_chunks::<4>().0.iter().any(|px| px[3] == 0));
        assert!(bytes_a.as_chunks::<4>().0.iter().any(|px| px[3] == 255));
        assert!(first[0]
            .vertices
            .iter()
            .all(|v| v.color == [63, 127, 191, 204]));
        assert_eq!(first[0].indices, [0, 1, 2, 0, 2, 3]);
        first[0].validate().unwrap();
    }

    #[test]
    fn fractional_sizes_have_antialiased_coverage_and_distinct_cache_keys() {
        let mut renderer = renderer();
        let first = renderer
            .meshes("g", Vec2::ZERO, 16.5, Color::WHITE)
            .unwrap();
        let second = renderer
            .meshes("g", Vec2::ZERO, 16.75, Color::WHITE)
            .unwrap();
        let first = first[0].texture.as_ref().unwrap();
        let second = second[0].texture.as_ref().unwrap();
        assert_ne!(first.id, second.id);
        let TextureSource::Rgba8(bytes) = &first.source else {
            panic!("glyph texture must contain CPU RGBA bytes");
        };
        assert!(bytes
            .as_chunks::<4>()
            .0
            .iter()
            .any(|px| px[3] > 0 && px[3] < 255));
    }

    #[test]
    fn invalid_sizes_and_positions_fail_without_allocating_glyphs() {
        let mut renderer = renderer();
        for size in [
            0.0,
            -1.0,
            f32::NAN,
            f32::INFINITY,
            f32::NEG_INFINITY,
            1025.0,
        ] {
            assert_eq!(renderer.measure_text("Ag", size), TextDimensions::default());
            assert!(renderer
                .meshes("Ag", Vec2::ZERO, size, Color::WHITE)
                .is_err());
        }
        assert!(renderer
            .meshes("A", Vec2::new(f32::NAN, 0.0), 13.0, Color::WHITE)
            .is_err());
        assert!(renderer
            .meshes("A", Vec2::ZERO, 13.0, Color::new(1.0, 1.0, 1.0, f32::NAN))
            .is_err());
        assert!(renderer.glyphs.is_empty());
        assert_eq!(renderer.cache_bytes, 0);
    }

    #[test]
    fn cache_budget_error_does_not_corrupt_an_existing_glyph() {
        let mut renderer = renderer();
        let first = renderer
            .meshes("A", Vec2::ZERO, 13.0, Color::WHITE)
            .unwrap();
        renderer.cache_bytes = MAX_CACHE_BYTES;
        assert!(renderer
            .meshes("g", Vec2::ZERO, 13.0, Color::WHITE)
            .is_err());
        let cached = renderer
            .meshes("A", Vec2::ZERO, 13.0, Color::WHITE)
            .unwrap();
        assert_eq!(renderer.glyphs.len(), 1);
        assert_eq!(
            cached[0].texture.as_ref().unwrap().id,
            first[0].texture.as_ref().unwrap().id
        );
    }

    #[test]
    fn cache_entry_limit_is_checked_before_insertion() {
        let mut renderer = renderer();
        for size_bits in 0..MAX_CACHED_GLYPHS as u32 {
            renderer.glyphs.insert(
                GlyphKey {
                    index: 0,
                    size_bits,
                },
                CachedGlyph {
                    metrics: Metrics::default(),
                    texture: None,
                },
            );
        }
        assert!(renderer
            .meshes("A", Vec2::ZERO, 13.0, Color::WHITE)
            .is_err());
        assert_eq!(renderer.glyphs.len(), MAX_CACHED_GLYPHS);
        assert_eq!(renderer.cache_bytes, 0);
    }
}
