//! Native adapter selection. An explicit backend never falls back to another API.
use crate::draw::BackendInfo;
use std::{str::FromStr, sync::Arc};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum BackendSelection {
    #[default]
    Auto,
    Dx12,
    Vulkan,
    Metal,
    Gl,
}
impl BackendSelection {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Auto => "auto",
            Self::Dx12 => "dx12",
            Self::Vulkan => "vulkan",
            Self::Metal => "metal",
            Self::Gl => "gl",
        }
    }
    pub fn backends(self) -> wgpu::Backends {
        match self {
            Self::Auto => wgpu::Backends::PRIMARY,
            Self::Dx12 => wgpu::Backends::DX12,
            Self::Vulkan => wgpu::Backends::VULKAN,
            Self::Metal => wgpu::Backends::METAL,
            Self::Gl => wgpu::Backends::GL,
        }
    }
    /// Parse only renderer options; unrelated application arguments remain owned by the caller.
    pub fn from_args(args: impl IntoIterator<Item = impl AsRef<str>>) -> Result<Self, String> {
        let mut selection = Self::Auto;
        let mut found = false;
        let mut args = args.into_iter();
        while let Some(arg) = args.next() {
            let arg = arg.as_ref();
            let value = if arg == "--renderer" {
                Some(
                    args.next()
                        .ok_or("--renderer requires a value")?
                        .as_ref()
                        .to_owned(),
                )
            } else {
                arg.strip_prefix("--renderer=").map(str::to_owned)
            };
            if let Some(value) = value {
                if found {
                    return Err("--renderer may be specified only once".into());
                }
                selection = value.parse()?;
                found = true;
            }
        }
        Ok(selection)
    }
}
impl FromStr for BackendSelection {
    type Err = String;
    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "auto" => Ok(Self::Auto),
            "dx12" => Ok(Self::Dx12),
            "vulkan" => Ok(Self::Vulkan),
            "metal" => Ok(Self::Metal),
            "gl" => Ok(Self::Gl),
            _ => Err(format!(
                "unknown renderer {value:?}; expected auto|dx12|vulkan|metal|gl"
            )),
        }
    }
}

pub(crate) struct Gpu {
    pub device: wgpu::Device,
    pub queue: wgpu::Queue,
    pub info: BackendInfo,
    pub surface: Option<Surface>,
    // Keep instance and window ownership alive through surface teardown.
    pub _instance: wgpu::Instance,
}
pub(crate) struct Surface {
    pub surface: wgpu::Surface<'static>,
    pub config: wgpu::SurfaceConfiguration,
    pub window: Arc<winit::window::Window>,
    reconfigure: bool,
}
impl Gpu {
    pub async fn new(
        selection: BackendSelection,
        force_fallback: bool,
        window: Option<Arc<winit::window::Window>>,
        width: u32,
        height: u32,
    ) -> Result<Self, String> {
        if width == 0 || height == 0 {
            return Err("renderer extent must be nonzero".into());
        }
        let mut descriptor = if let Some(window) = &window {
            wgpu::InstanceDescriptor::new_with_display_handle(Box::new(window.clone()))
        } else {
            wgpu::InstanceDescriptor::new_without_display_handle()
        };
        descriptor.backends = selection.backends();
        let instance = wgpu::Instance::new(descriptor);
        let surface = window
            .as_ref()
            .map(|w| instance.create_surface(w.clone()))
            .transpose()
            .map_err(|e| format!("create surface: {e}"))?;
        let request = |fallback| wgpu::RequestAdapterOptions {
            power_preference: wgpu::PowerPreference::HighPerformance,
            force_fallback_adapter: fallback,
            compatible_surface: surface.as_ref(),
            ..Default::default()
        };
        let adapter = match instance.request_adapter(&request(force_fallback)).await {
            Ok(adapter) => adapter,
            Err(first) if !force_fallback => instance
                .request_adapter(&request(true))
                .await
                .map_err(|second| {
                    format!(
                        "no {} adapter (hardware: {first}; fallback: {second})",
                        selection.as_str()
                    )
                })?,
            Err(error) => {
                return Err(format!(
                    "no {} software adapter: {error}",
                    selection.as_str()
                ))
            }
        };
        let adapter_info = adapter.get_info();
        let info = BackendInfo {
            requested: selection.as_str().into(),
            backend: format!("{:?}", adapter_info.backend),
            adapter: adapter_info.name,
        };
        let limits = wgpu::Limits::downlevel_defaults().using_resolution(adapter.limits());
        let (device, queue) = adapter
            .request_device(&wgpu::DeviceDescriptor {
                label: Some("Rust Duty render device"),
                required_limits: limits,
                ..Default::default()
            })
            .await
            .map_err(|e| format!("request {} device: {e}", info.backend))?;
        let surface = if let Some(surface) = surface {
            let caps = surface.get_capabilities(&adapter);
            let format = caps
                .formats
                .iter()
                .copied()
                .find(|f| !f.is_srgb())
                .or_else(|| caps.formats.first().copied())
                .ok_or("surface has no supported color format")?;
            let mut config = surface
                .get_default_config(&adapter, width, height)
                .ok_or("adapter cannot present to this surface")?;
            config.format = format;
            config.present_mode = wgpu::PresentMode::Fifo;
            surface.configure(&device, &config);
            Some(Surface {
                surface,
                config,
                window: window.expect("surface creation requires window ownership"),
                reconfigure: false,
            })
        } else {
            None
        };
        eprintln!(
            "renderer requested={} backend={} adapter={}",
            info.requested, info.backend, info.adapter
        );
        Ok(Self {
            device,
            queue,
            info,
            surface,
            _instance: instance,
        })
    }
    pub fn resize(&mut self, width: u32, height: u32) {
        if let Some(surface) = &mut self.surface {
            if surface.config.width != width
                || surface.config.height != height
                || surface.reconfigure
            {
                surface.config.width = width;
                surface.config.height = height;
                surface.surface.configure(&self.device, &surface.config);
                surface.reconfigure = false;
            }
        }
    }
    pub fn acquire(&mut self) -> Result<Option<wgpu::SurfaceTexture>, String> {
        let Some(surface) = &mut self.surface else {
            return Ok(None);
        };
        for attempt in 0..2 {
            match surface.surface.get_current_texture() {
                wgpu::CurrentSurfaceTexture::Success(frame) => return Ok(Some(frame)),
                wgpu::CurrentSurfaceTexture::Suboptimal(frame) => {
                    surface.reconfigure = true;
                    return Ok(Some(frame));
                }
                wgpu::CurrentSurfaceTexture::Outdated if attempt == 0 => {
                    surface.surface.configure(&self.device, &surface.config)
                }
                wgpu::CurrentSurfaceTexture::Lost if attempt == 0 => {
                    surface.surface = self
                        ._instance
                        .create_surface(surface.window.clone())
                        .map_err(|e| format!("recreate lost surface: {e}"))?;
                    surface.surface.configure(&self.device, &surface.config);
                }
                status => return Err(format!("cannot acquire surface: {status:?}")),
            }
        }
        Err("surface acquisition recovery exhausted".into())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn parses_supported_backends_and_rejects_ambiguous_flags() {
        for value in ["auto", "dx12", "vulkan", "metal", "gl"] {
            assert_eq!(
                BackendSelection::from_args([format!("--renderer={value}")])
                    .unwrap()
                    .as_str(),
                value
            );
        }
        assert_eq!(
            BackendSelection::from_args(["--capture", "--renderer", "vulkan"]).unwrap(),
            BackendSelection::Vulkan
        );
        assert!(BackendSelection::from_args(["--renderer"]).is_err());
        assert!(BackendSelection::from_args(["--renderer=invalid"]).is_err());
        assert!(BackendSelection::from_args(["--renderer=gl", "--renderer=auto"]).is_err());
        assert_eq!(BackendSelection::Auto.backends(), wgpu::Backends::PRIMARY);
    }
}
