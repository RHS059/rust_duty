//! Ordered GPU readback. Padded rows are stripped without changing orientation.
//!
//! Explicit render-target PNGs are lossless diagnostic dumps: RGB is associated
//! radiance (including emission), alpha is coverage. PNG viewers normally assume
//! straight alpha, so these files are not directly reusable transparent artwork.
//! In particular RGB at zero alpha and RGB greater than alpha must be retained.
//! Default framebuffer PNGs are ordinary opaque images of the display over black:
//! stored RGB is preserved and alpha is 255. Neither path unpremultiplies/clamps
//! emission or multiplies associated RGB by alpha for a second time.
use std::{path::PathBuf, sync::mpsc, time::Duration};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum CaptureEncoding {
    AssociatedTargetDiagnostic,
    OpaqueDisplay,
}
impl CaptureEncoding {
    pub fn for_target(target: Option<&crate::draw::RenderTarget>) -> Self {
        if target.is_some() {
            Self::AssociatedTargetDiagnostic
        } else {
            Self::OpaqueDisplay
        }
    }
    fn apply(self, pixels: &mut [u8]) {
        if self == Self::OpaqueDisplay {
            for pixel in pixels.as_chunks_mut::<4>().0 {
                pixel[3] = 255;
            }
        }
    }
}

pub(crate) fn padded_bytes_per_row(width: u32) -> Result<u32, String> {
    if width == 0 {
        return Err("capture width must be nonzero".into());
    }
    width
        .checked_mul(4)
        .and_then(|n| n.checked_add(wgpu::COPY_BYTES_PER_ROW_ALIGNMENT - 1))
        .map(|n| n / wgpu::COPY_BYTES_PER_ROW_ALIGNMENT * wgpu::COPY_BYTES_PER_ROW_ALIGNMENT)
        .ok_or_else(|| "capture row size overflow".into())
}
pub(crate) fn unpack_rows(mapped: &[u8], width: u32, height: u32) -> Result<Vec<u8>, String> {
    if height == 0 {
        return Err("capture height must be nonzero".into());
    }
    let stride = padded_bytes_per_row(width)? as usize;
    let needed = stride
        .checked_mul(height as usize)
        .ok_or("capture buffer size overflow")?;
    if mapped.len() != needed {
        return Err("mapped capture length differs from padded extent".into());
    }
    let mut pixels = Vec::with_capacity(width as usize * 4 * height as usize);
    for row in mapped.chunks_exact(stride) {
        pixels.extend_from_slice(&row[..width as usize * 4]);
    }
    Ok(pixels)
}

pub(crate) struct Readback {
    buffer: wgpu::Buffer,
    width: u32,
    height: u32,
    path: PathBuf,
    encoding: CaptureEncoding,
}
impl Readback {
    pub fn encode(
        device: &wgpu::Device,
        encoder: &mut wgpu::CommandEncoder,
        texture: &wgpu::Texture,
        path: PathBuf,
        encoding: CaptureEncoding,
    ) -> Result<Self, String> {
        let (width, height) = (texture.width(), texture.height());
        let row = padded_bytes_per_row(width)?;
        let size = u64::from(row) * u64::from(height);
        if size > device.limits().max_buffer_size {
            return Err("capture exceeds adapter readback buffer limit".into());
        }
        let buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("ordered PNG readback"),
            size,
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
            mapped_at_creation: false,
        });
        encoder.copy_texture_to_buffer(
            wgpu::TexelCopyTextureInfo {
                texture,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            wgpu::TexelCopyBufferInfo {
                buffer: &buffer,
                layout: wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(row),
                    rows_per_image: Some(height),
                },
            },
            wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
        );
        Ok(Self {
            buffer,
            width,
            height,
            path,
            encoding,
        })
    }
    pub fn finish(self, device: &wgpu::Device) -> Result<PathBuf, String> {
        let (sender, receiver) = mpsc::sync_channel(1);
        self.buffer
            .slice(..)
            .map_async(wgpu::MapMode::Read, move |result| {
                let _ = sender.send(result);
            });
        device
            .poll(wgpu::PollType::Wait {
                submission_index: None,
                timeout: Some(Duration::from_secs(30)),
            })
            .map_err(|e| format!("capture GPU wait: {e}"))?;
        receiver
            .recv_timeout(Duration::from_secs(1))
            .map_err(|e| format!("capture map callback: {e}"))?
            .map_err(|e| format!("capture buffer map: {e}"))?;
        let mapped = self
            .buffer
            .slice(..)
            .get_mapped_range()
            .map_err(|e| format!("capture mapped range: {e}"))?;
        let pixels = unpack_rows(&mapped, self.width, self.height);
        drop(mapped);
        self.buffer.unmap();
        let mut pixels = pixels?;
        self.encoding.apply(&mut pixels);
        save_png(&self.path, self.width, self.height, &pixels)?;
        Ok(self.path)
    }
}

fn save_png(path: &std::path::Path, width: u32, height: u32, pixels: &[u8]) -> Result<(), String> {
    if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
        std::fs::create_dir_all(parent)
            .map_err(|e| format!("create capture directory {}: {e}", parent.display()))?;
    }
    image::save_buffer_with_format(
        path,
        pixels,
        width,
        height,
        image::ColorType::Rgba8,
        image::ImageFormat::Png,
    )
    .map_err(|e| format!("write capture {}: {e}", path.display()))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn capture_encoding_preserves_associated_emission_without_unpremultiply() {
        let original = [128, 128, 128, 128, 200, 25, 0, 0, 240, 20, 10, 64];
        let target = crate::draw::RenderTarget::new(3, 1, false).unwrap();
        let mut diagnostic = original;
        CaptureEncoding::for_target(Some(&target)).apply(&mut diagnostic);
        assert_eq!(diagnostic, original);
        let mut display = original;
        CaptureEncoding::for_target(None).apply(&mut display);
        assert_eq!(
            display,
            [128, 128, 128, 255, 200, 25, 0, 255, 240, 20, 10, 255]
        );
    }

    #[test]
    fn diagnostic_png_roundtrip_preserves_zero_alpha_emission_and_rgb_above_alpha() {
        let path = std::env::temp_dir().join(format!(
            "rust-duty-associated-target-{}.png",
            std::process::id()
        ));
        let pixels = [128, 128, 128, 128, 200, 25, 0, 0, 240, 20, 10, 64];
        save_png(&path, 3, 1, &pixels).unwrap();
        let image = image::open(&path).unwrap().to_rgba8();
        std::fs::remove_file(&path).unwrap();
        assert_eq!(image.dimensions(), (3, 1));
        assert_eq!(image.as_raw(), &pixels);
    }

    #[test]
    fn readback_alignment_and_orientation_are_independent() {
        for (width, expected) in [(1, 256), (63, 256), (64, 256), (65, 512), (960, 3840)] {
            assert_eq!(padded_bytes_per_row(width).unwrap(), expected);
        }
        let mut padded = vec![99; 512];
        padded[..8].copy_from_slice(&[255, 0, 0, 255, 0, 255, 0, 255]);
        padded[256..264].copy_from_slice(&[0, 0, 255, 255, 255, 255, 0, 255]);
        assert_eq!(
            unpack_rows(&padded, 2, 2).unwrap(),
            vec![255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 255, 255, 0, 255]
        );
        assert!(unpack_rows(&padded[..511], 2, 2).is_err());
        assert!(padded_bytes_per_row(u32::MAX).is_err());
        assert!(padded_bytes_per_row(0).is_err());
    }
}
