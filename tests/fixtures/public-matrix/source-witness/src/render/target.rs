//! All sampled textures and render targets use top-left UVs. No legacy flip-Y is applied.
// Target storage is associated RGB plus additive emission, and coverage alpha.
// Uploaded Rgba8 textures instead contain ordinary straight-alpha image data.
use crate::draw::{Color, FilterMode, Sampler, Texture, TextureSource, WrapMode};

pub(crate) const COLOR_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Rgba8Unorm;
pub(crate) const DEPTH_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Depth32Float;

/// Clear colors use the public straight-alpha Color contract. A transparent
/// colored clear must not inject unrequested additive emission into a target.
pub(crate) fn clear_color(color: Color) -> wgpu::Color {
    let alpha = color.a.clamp(0., 1.);
    wgpu::Color {
        r: (color.r.clamp(0., 1.) * alpha) as f64,
        g: (color.g.clamp(0., 1.) * alpha) as f64,
        b: (color.b.clamp(0., 1.) * alpha) as f64,
        a: alpha as f64,
    }
}

pub(crate) struct GpuTexture {
    pub descriptor: Texture,
    pub texture: wgpu::Texture,
    pub view: wgpu::TextureView,
    pub depth: Option<wgpu::TextureView>,
    pub binding: wgpu::BindGroup,
}

pub(crate) fn validate(texture: &Texture, limits: &wgpu::Limits) -> Result<(), String> {
    if texture.width == 0 || texture.height == 0 {
        return Err("texture extent must be nonzero".into());
    }
    if texture.width > limits.max_texture_dimension_2d
        || texture.height > limits.max_texture_dimension_2d
    {
        return Err(format!(
            "texture {}x{} exceeds adapter limit {}",
            texture.width, texture.height, limits.max_texture_dimension_2d
        ));
    }
    if let TextureSource::Rgba8(bytes) = &texture.source {
        let expected = u64::from(texture.width) * u64::from(texture.height) * 4;
        if bytes.len() as u64 != expected {
            return Err("texture extent does not match RGBA8 data".into());
        }
    }
    Ok(())
}

impl GpuTexture {
    pub fn new(
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        layout: &wgpu::BindGroupLayout,
        descriptor: &Texture,
    ) -> Result<Self, String> {
        validate(descriptor, &device.limits())?;
        let is_target = matches!(descriptor.source, TextureSource::Target { .. });
        let size = wgpu::Extent3d {
            width: descriptor.width,
            height: descriptor.height,
            depth_or_array_layers: 1,
        };
        let mut usage = wgpu::TextureUsages::TEXTURE_BINDING
            | wgpu::TextureUsages::COPY_DST
            | wgpu::TextureUsages::COPY_SRC;
        if is_target {
            usage |= wgpu::TextureUsages::RENDER_ATTACHMENT;
        }
        let texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("top-left RGBA texture"),
            size,
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: COLOR_FORMAT,
            usage,
            view_formats: &[],
        });
        if let TextureSource::Rgba8(bytes) = &descriptor.source {
            queue.write_texture(
                wgpu::TexelCopyTextureInfo {
                    texture: &texture,
                    mip_level: 0,
                    origin: wgpu::Origin3d::ZERO,
                    aspect: wgpu::TextureAspect::All,
                },
                bytes,
                wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(descriptor.width * 4),
                    rows_per_image: Some(descriptor.height),
                },
                size,
            );
        }
        let view = texture.create_view(&wgpu::TextureViewDescriptor::default());
        let sampler = sampler(device, descriptor.sampler);
        let binding = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("top-left texture binding"),
            layout,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: wgpu::BindingResource::TextureView(&view),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::Sampler(&sampler),
                },
            ],
        });
        let depth = if matches!(descriptor.source, TextureSource::Target { depth: true }) {
            Some(
                device
                    .create_texture(&wgpu::TextureDescriptor {
                        label: Some("camera depth"),
                        size,
                        mip_level_count: 1,
                        sample_count: 1,
                        dimension: wgpu::TextureDimension::D2,
                        format: DEPTH_FORMAT,
                        usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
                        view_formats: &[],
                    })
                    .create_view(&wgpu::TextureViewDescriptor::default()),
            )
        } else {
            None
        };
        let result = Self {
            descriptor: descriptor.clone(),
            texture,
            view,
            depth,
            binding,
        };
        if is_target {
            // New depth storage must start at the far plane rather than WebGPU's
            // security-initialized zero. Subsequent camera switches preserve it.
            let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
                label: Some("initialize render target"),
            });
            super::frame::clear(&mut encoder, &result, crate::draw::Color::TRANSPARENT);
            queue.submit([encoder.finish()]);
        }
        Ok(result)
    }

    pub fn matches(&self, other: &Texture) -> bool {
        let own = &self.descriptor;
        own.width == other.width
            && own.height == other.height
            && own.sampler == other.sampler
            && match (&own.source, &other.source) {
                (TextureSource::Rgba8(a), TextureSource::Rgba8(b)) => {
                    std::sync::Arc::ptr_eq(a, b) || a == b
                }
                (TextureSource::Target { depth: a }, TextureSource::Target { depth: b }) => a == b,
                _ => false,
            }
    }
}

fn sampler(device: &wgpu::Device, descriptor: Sampler) -> wgpu::Sampler {
    let filter = match descriptor.filter {
        FilterMode::Nearest => wgpu::FilterMode::Nearest,
        FilterMode::Linear => wgpu::FilterMode::Linear,
    };
    let wrap = |mode| match mode {
        WrapMode::Clamp => wgpu::AddressMode::ClampToEdge,
        WrapMode::Repeat => wgpu::AddressMode::Repeat,
    };
    device.create_sampler(&wgpu::SamplerDescriptor {
        label: Some("presentation sampler"),
        address_mode_u: wrap(descriptor.wrap_x),
        address_mode_v: wrap(descriptor.wrap_y),
        mag_filter: filter,
        min_filter: filter,
        ..Default::default()
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn clear_converts_straight_color_to_associated_storage() {
        let color = clear_color(Color::new(1., 0.5, 0.25, 0.5));
        assert_eq!(
            [color.r, color.g, color.b, color.a],
            [0.5, 0.25, 0.125, 0.5]
        );
        assert_eq!(
            clear_color(Color::new(1., 0., 0., 0.)),
            wgpu::Color::TRANSPARENT
        );
        assert_eq!(clear_color(Color::WHITE), wgpu::Color::WHITE);
        let color = clear_color(Color::new(2., -1., 0.5, 2.));
        assert_eq!([color.r, color.g, color.b, color.a], [1., 0., 0.5, 1.]);
    }
}
