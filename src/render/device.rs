//! Native adapter selection. An explicit backend never falls back to another API.
use super::present_policy::{
    ConfiguredPresentMode, DiagnosticPresentMode, PresentModeRequest, PresentModeSelection,
};
use crate::{
    draw::BackendInfo,
    graphics_device::{self, Candidate, Fingerprint, Preference},
};
use std::{
    str::FromStr,
    sync::{Arc, Mutex},
};

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
    /// Windows Auto starts with DX12 only. PRIMARY is attempted only when
    /// initialization of that first API fails, never alongside its first try.
    fn attempts(self, windows: bool) -> Vec<wgpu::Backends> {
        if self == Self::Auto && windows {
            vec![wgpu::Backends::DX12, wgpu::Backends::PRIMARY]
        } else {
            vec![self.backends()]
        }
    }
    /// Parse only renderer options; unrelated application arguments remain owned by the caller.
    pub fn from_args(args: impl IntoIterator<Item = impl AsRef<str>>) -> Result<Self, String> {
        let mut selection = Self::Auto;
        let mut found = false;
        let mut args = args.into_iter();
        while let Some(arg) = args.next() {
            let arg = arg.as_ref();
            if arg == "--" {
                break;
            }
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
    failures: DeviceFailures,
    adapter: wgpu::Adapter,
    pub(super) gpu_diagnostics: Option<crate::frame_gpu_capture::Registration>,
    // Keep instance and window ownership alive through surface teardown.
    pub _instance: wgpu::Instance,
}

/// Callbacks may run on a driver thread. Preserve the first fatal diagnostic
/// until the renderer is dropped; observing it must never make a dead device
/// usable again or allow a later, less useful error to replace the cause.
#[derive(Clone, Default)]
struct DeviceFailures(Arc<Mutex<Option<String>>>);

impl DeviceFailures {
    fn record(&self, error: String) {
        let mut first = self.0.lock().unwrap_or_else(|poison| poison.into_inner());
        if first.is_none() {
            *first = Some(error);
        }
    }

    fn uncaptured(&self, error: wgpu::Error) {
        let kind = match &error {
            wgpu::Error::OutOfMemory { .. } => "out of memory",
            wgpu::Error::Internal { .. } => "internal",
            wgpu::Error::Validation { .. } => "validation",
        };
        let source = std::error::Error::source(&error)
            .map(|source| format!("; source: {source}"))
            .unwrap_or_default();
        self.record(format!("uncaptured GPU {kind} error: {error}{source}"));
    }

    fn lost(&self, reason: wgpu::DeviceLostReason, message: String) {
        self.record(format!("GPU device lost ({reason:?}): {message}"));
    }

    fn check(&self) -> Result<(), String> {
        self.0
            .lock()
            .unwrap_or_else(|poison| poison.into_inner())
            .clone()
            .map_or(Ok(()), Err)
    }
}

fn check_device(device: &wgpu::Device, failures: &DeviceFailures) -> Result<(), String> {
    failures.check()?;
    // Nonblocking polling dispatches device-loss callbacks even on ordinary
    // frames with no PNG readback. Do not impose a GPU wait on every frame.
    if let Err(error) = device.poll(wgpu::PollType::Poll) {
        failures.record(format!("GPU device poll failed: {error}"));
    }
    failures.check()
}
pub(crate) struct Surface {
    pub surface: wgpu::Surface<'static>,
    pub config: wgpu::SurfaceConfiguration,
    pub window: Arc<winit::window::Window>,
    reconfigure: bool,
    present: ConfiguredPresentMode,
}

#[derive(Debug)]
enum InitializationError {
    Retryable(String),
    Terminal(String),
}
impl From<String> for InitializationError {
    fn from(error: String) -> Self {
        Self::Retryable(error)
    }
}
impl From<&str> for InitializationError {
    fn from(error: &str) -> Self {
        Self::Retryable(error.to_owned())
    }
}
impl InitializationError {
    fn message(self) -> String {
        match self {
            Self::Retryable(error) | Self::Terminal(error) => error,
        }
    }
}

fn diagnostic_mode(mode: wgpu::PresentMode) -> Option<DiagnosticPresentMode> {
    match mode {
        wgpu::PresentMode::Fifo => Some(DiagnosticPresentMode::Fifo),
        wgpu::PresentMode::Mailbox => Some(DiagnosticPresentMode::Mailbox),
        wgpu::PresentMode::Immediate => Some(DiagnosticPresentMode::Immediate),
        _ => None,
    }
}

fn concrete_mode(mode: DiagnosticPresentMode) -> wgpu::PresentMode {
    match mode {
        DiagnosticPresentMode::Fifo => wgpu::PresentMode::Fifo,
        DiagnosticPresentMode::Mailbox => wgpu::PresentMode::Mailbox,
        DiagnosticPresentMode::Immediate => wgpu::PresentMode::Immediate,
    }
}

fn select_present_mode(
    request: PresentModeRequest,
    supported: &[wgpu::PresentMode],
) -> Result<PresentModeSelection, String> {
    let supported: Vec<_> = supported
        .iter()
        .copied()
        .filter_map(diagnostic_mode)
        .collect();
    request
        .select(&supported)
        .map_err(|error| error.to_string())
}

fn verify_present_mode(
    selection: PresentModeSelection,
    actual: wgpu::PresentMode,
) -> Result<ConfiguredPresentMode, String> {
    let actual = diagnostic_mode(actual)
        .ok_or("configured present mode is not a concrete diagnostic mode")?;
    selection
        .verify_applied(actual)
        .map_err(|error| error.to_string())
}

fn configure_instance(descriptor: &mut wgpu::InstanceDescriptor, backends: wgpu::Backends) {
    descriptor.backends = backends;
    // Pin the same system compiler for WARP CI and distributed Windows builds.
    // Auto can pick up a runner-only dxcompiler.dll and silently differ locally.
    descriptor.backend_options.dx12.shader_compiler = wgpu::Dx12Compiler::Fxc;
}

/// Final descriptor passed to wgpu, not a claim that a backend validation
/// layer was installed. Application/dependency debug profiles may differ.
fn instance_descriptor_evidence(flags: wgpu::InstanceFlags) -> serde_json::Value {
    serde_json::json!({
        "schema": "rust-duty-wgpu-instance-descriptor/v1",
        "wgpu_version": "30.0.1",
        "flags_bits": flags.bits(),
        "debug": flags.contains(wgpu::InstanceFlags::DEBUG),
        "validation": flags.contains(wgpu::InstanceFlags::VALIDATION),
        "gpu_based_validation": flags.contains(wgpu::InstanceFlags::GPU_BASED_VALIDATION),
        "validation_indirect_call": flags.contains(wgpu::InstanceFlags::VALIDATION_INDIRECT_CALL),
        "application_debug_assertions": cfg!(debug_assertions),
        "environment_overrides_applied": false,
    })
}

fn fingerprint(info: &wgpu::AdapterInfo) -> Fingerprint {
    Fingerprint {
        backend: match info.backend {
            wgpu::Backend::Dx12 => "dx12",
            wgpu::Backend::Vulkan => "vulkan",
            wgpu::Backend::Metal => "metal",
            wgpu::Backend::Gl => "gl",
            _ => "unknown",
        }
        .into(),
        name: info.name.clone(),
        vendor: info.vendor,
        device: info.device,
        device_type: format!("{:?}", info.device_type),
    }
}

fn candidates(adapters: &[wgpu::Adapter], surface: Option<&wgpu::Surface<'_>>) -> Vec<Candidate> {
    adapters
        .iter()
        .map(|adapter| Candidate {
            id: fingerprint(&adapter.get_info()),
            surface_supported: surface.is_none_or(|surface| adapter.is_surface_supported(surface)),
        })
        .collect()
}

pub(crate) async fn menu_candidates() -> Vec<Candidate> {
    let mut descriptor = wgpu::InstanceDescriptor::new_without_display_handle();
    configure_instance(&mut descriptor, wgpu::Backends::PRIMARY);
    let instance = wgpu::Instance::new(descriptor);
    candidates(
        &instance.enumerate_adapters(wgpu::Backends::PRIMARY).await,
        None,
    )
}

impl Gpu {
    pub async fn new(
        selection: BackendSelection,
        force_fallback: bool,
        window: Option<Arc<winit::window::Window>>,
        width: u32,
        height: u32,
    ) -> Result<Self, String> {
        Self::new_with_diagnostics(
            selection,
            force_fallback,
            window,
            width,
            height,
            Default::default(),
        )
        .await
    }

    pub async fn new_with_diagnostics(
        selection: BackendSelection,
        force_fallback: bool,
        window: Option<Arc<winit::window::Window>>,
        width: u32,
        height: u32,
        diagnostics: super::RuntimeDiagnostics,
    ) -> Result<Self, String> {
        if width == 0 || height == 0 {
            return Err("renderer extent must be nonzero".into());
        }
        // Headless jobs and forced WARP/lavapipe never consult interactive preferences.
        let preferred = graphics_device::device_preference(window.is_some(), force_fallback);
        if let Preference::Adapter(id) = preferred {
            let backend: BackendSelection = id.backend.parse()?;
            if selection != BackendSelection::Auto && selection != backend {
                return Err(format!(
                    "Selected graphics device uses {}, conflicting with renderer {}",
                    id.backend,
                    selection.as_str()
                ));
            }
            // An explicit device has exactly one initialization attempt. No API or
            // software retry may silently replace it after any initialization failure.
            return Self::new_for_backends(
                selection,
                false,
                window,
                [width, height],
                diagnostics,
                backend.backends(),
                Some(id),
            )
            .await
            .map_err(InitializationError::message);
        }
        initialize_with_policy(selection, cfg!(target_os = "windows"), |backends| {
            Self::new_for_backends(
                selection,
                force_fallback,
                window.clone(),
                [width, height],
                diagnostics,
                backends,
                None,
            )
        })
        .await
    }

    async fn new_for_backends(
        selection: BackendSelection,
        force_fallback: bool,
        window: Option<Arc<winit::window::Window>>,
        extent: [u32; 2],
        diagnostics: super::RuntimeDiagnostics,
        backends: wgpu::Backends,
        preferred: Option<Fingerprint>,
    ) -> Result<Self, InitializationError> {
        let [width, height] = extent;
        if !backends.intersects(wgpu::Instance::enabled_backend_features()) {
            return Err(format!("{backends:?} is not available in this build").into());
        }
        let mut descriptor = if let Some(window) = &window {
            wgpu::InstanceDescriptor::new_with_display_handle(Box::new(window.clone()))
        } else {
            wgpu::InstanceDescriptor::new_without_display_handle()
        };
        configure_instance(&mut descriptor, backends);
        let instance_descriptor = instance_descriptor_evidence(descriptor.flags);
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
        // Keep the actual Adapter objects: the resolved fingerprint indexes this
        // exact inventory, never a fresh request_adapter ranking or substring match.
        let adapters = if window.is_some() || preferred.is_some() {
            instance.enumerate_adapters(backends).await
        } else {
            Vec::new()
        };
        let inventory = candidates(&adapters, surface.as_ref());
        if window.is_some() {
            graphics_device::update_catalog(inventory.clone());
        }
        let adapter = if let Some(id) = &preferred {
            let index = graphics_device::exact_match(id, &inventory)?;
            adapters
                .into_iter()
                .nth(index)
                .expect("resolved adapter inventory index")
        } else {
            match instance.request_adapter(&request(force_fallback)).await {
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
                    return Err(
                        format!("no {} software adapter: {error}", selection.as_str()).into(),
                    )
                }
            }
        };
        let adapter_info = adapter.get_info();
        let actual_id = fingerprint(&adapter_info);
        let info = BackendInfo {
            requested: selection.as_str().into(),
            backend: format!("{:?}", adapter_info.backend),
            adapter: adapter_info.name.clone(),
        };
        // Reject an unsupported diagnostic before device creation, so it cannot
        // be obscured by a retryable device initialization failure on Auto.
        let surface_capabilities = surface
            .as_ref()
            .map(|surface| surface.get_capabilities(&adapter));
        let present_selection = surface_capabilities
            .as_ref()
            .map(|caps| select_present_mode(diagnostics.present_mode, &caps.present_modes))
            .transpose()
            .map_err(InitializationError::Terminal)?;
        let limits = wgpu::Limits::downlevel_defaults().using_resolution(adapter.limits());
        let gpu_timestamps = diagnostics.gpu_timestamps && window.is_some();
        let timestamp_features =
            super::gpu_timing::requested_features(gpu_timestamps, adapter.features());
        let (device, queue) = adapter
            .request_device(&wgpu::DeviceDescriptor {
                label: Some("Rust Duty render device"),
                required_limits: limits,
                required_features: timestamp_features,
                ..Default::default()
            })
            .await
            .map_err(|e| format!("request {} device: {e}", info.backend))?;
        // Install these before the first surface/resource operation. Validation
        // scopes retain their contextual errors; all other failures are fatal
        // Results instead of wgpu's default uncaptured-error panic.
        let failures = DeviceFailures::default();
        let uncaptured = failures.clone();
        device.on_uncaptured_error(Arc::new(move |error| uncaptured.uncaptured(error)));
        let lost = failures.clone();
        device.set_device_lost_callback(move |reason, message| lost.lost(reason, message));
        let surface = if let Some(surface) = surface {
            let caps = surface_capabilities.expect("surface capabilities were queried");
            let selection = present_selection.expect("surface present mode was selected");
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
            config.present_mode = concrete_mode(selection.selected_mode());
            let validation = device.push_error_scope(wgpu::ErrorFilter::Validation);
            surface.configure(&device, &config);
            if let Some(error) = validation.pop().await {
                return Err(format!("configure {} surface: {error}", info.backend).into());
            }
            let present = verify_present_mode(selection, config.present_mode)
                .map_err(InitializationError::Terminal)?;
            Some(Surface {
                surface,
                config,
                window: window.expect("surface creation requires window ownership"),
                reconfigure: false,
                present,
            })
        } else {
            None
        };
        check_device(&device, &failures)?;
        let gpu_diagnostics = gpu_timestamps
            .then(|| {
                crate::frame_gpu_capture::register(
                    &device,
                    &queue,
                    adapter
                        .features()
                        .contains(super::gpu_timing::required_features()),
                )
            })
            .flatten();
        eprintln!(
            "renderer requested={} backend={} adapter={}",
            info.requested, info.backend, info.adapter
        );
        // Runtime evidence uses the actual adapter classification, not the
        // absence of a fallback request or a guess based on the adapter name.
        let evidence = serde_json::json!({
            "name": adapter_info.name,
            "backend": info.backend,
            "device_type": format!("{:?}", adapter_info.device_type),
            "vendor_id": adapter_info.vendor,
            "device_id": adapter_info.device,
            "driver": adapter_info.driver,
            "driver_info": adapter_info.driver_info,
            "instance_descriptor": instance_descriptor,
            "present_mode": surface.as_ref().map(|s| format!("{:?}", s.config.present_mode)),
            "gpu_timestamps_requested": gpu_timestamps,
            "gpu_timestamp_features_enabled": device.features().contains(super::gpu_timing::required_features()),
            "present_policy": surface.as_ref().map(|s| serde_json::json!({
                "requested_mode": s.present.requested_label(),
                "actual_mode": s.present.actual_label(),
                "explicit_request": s.present.request().is_explicit(),
            })),
            "force_fallback_requested": force_fallback,
            "selection_mode": if force_fallback { "forced_fallback" } else if preferred.is_some() { "explicit_fingerprint" } else { "automatic" },
            "requested_fingerprint": preferred.as_ref().map(Fingerprint::json),
            "actual_fingerprint": actual_id.json(),
        });
        // Keep the existing seven-field diagnostic contract for pinned benchmark
        // consumers. Richer selection identity has a separate, additive log and
        // is also retained in the local session/frame exports.
        eprintln!(
            "renderer device_evidence={}",
            serde_json::json!({
                "device_type": evidence["device_type"], "vendor_id": evidence["vendor_id"],
                "device_id": evidence["device_id"], "driver": evidence["driver"],
                "driver_info": evidence["driver_info"], "present_mode": evidence["present_mode"],
                "force_fallback_requested": evidence["force_fallback_requested"],
            })
        );
        eprintln!("renderer graphics_device_evidence={evidence}");
        if surface.is_some() {
            graphics_device::update_actual(info.clone(), evidence);
        }
        if adapter_info.backend == wgpu::Backend::Dx12 {
            eprintln!("renderer dx12_shader_compiler=Fxc");
        }
        Ok(Self {
            device,
            queue,
            info,
            surface,
            failures,
            adapter,
            gpu_diagnostics,
            _instance: instance,
        })
    }

    pub(super) fn check_errors(&self) -> Result<(), String> {
        let result = check_device(&self.device, &self.failures);
        if let Some(registration) = self.gpu_diagnostics {
            crate::frame_gpu_capture::collect_ready(registration);
        }
        result
    }

    pub fn resize(&mut self, width: u32, height: u32) -> Result<(), String> {
        self.check_errors()?;
        // Winit can report zero dimensions while minimized. Never configure
        // such an extent, even if this low-level helper is called directly.
        if width == 0 || height == 0 {
            return Ok(());
        }
        if let Some(surface) = &mut self.surface {
            if surface.config.width != width
                || surface.config.height != height
                || surface.reconfigure
            {
                surface.config.width = width;
                surface.config.height = height;
                configure(&self.device, &self.adapter, surface)?;
                surface.reconfigure = false;
            }
        }
        self.check_errors()
    }
    pub fn acquire(&mut self) -> Result<Option<wgpu::SurfaceTexture>, String> {
        self.check_errors()?;
        let Some(surface) = &mut self.surface else {
            return Ok(None);
        };
        for attempt in 0..2 {
            let validation = self.device.push_error_scope(wgpu::ErrorFilter::Validation);
            let status = crate::frame_performance_session::measure_cpu_substage(
                crate::frame_cpu_substages::CpuSubstage::AcquireTexture,
                || surface.surface.get_current_texture(),
            );
            let validation_result = crate::frame_performance_session::measure_cpu_substage(
                crate::frame_cpu_substages::CpuSubstage::AcquireValidation,
                || pollster::block_on(validation.pop()),
            );
            if let Some(error) = validation_result {
                return Err(format!("acquire surface validation: {error}"));
            }
            // A lost device is terminal; it must not be mistaken for a lost
            // surface and sent through the surface-only recovery path below.
            check_device(&self.device, &self.failures)?;
            match status {
                wgpu::CurrentSurfaceTexture::Success(frame) => return Ok(Some(frame)),
                wgpu::CurrentSurfaceTexture::Suboptimal(frame) => {
                    surface.reconfigure = true;
                    return Ok(Some(frame));
                }
                status => match acquisition_action(&status, attempt) {
                    AcquisitionAction::Skip => return Ok(None),
                    AcquisitionAction::Reconfigure => {
                        configure(&self.device, &self.adapter, surface)?
                    }
                    AcquisitionAction::Recreate => {
                        surface.surface = self
                            ._instance
                            .create_surface(surface.window.clone())
                            .map_err(|e| format!("recreate lost surface: {e}"))?;
                        configure(&self.device, &self.adapter, surface)?;
                    }
                    AcquisitionAction::Fail => {
                        return Err(format!("cannot acquire surface: {status:?}"));
                    }
                },
            }
        }
        Err("surface acquisition recovery exhausted".into())
    }
}

impl Drop for Gpu {
    fn drop(&mut self) {
        if let Some(registration) = self.gpu_diagnostics {
            crate::frame_gpu_capture::unregister(registration);
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum AcquisitionAction {
    Skip,
    Reconfigure,
    Recreate,
    Fail,
}
fn acquisition_action(status: &wgpu::CurrentSurfaceTexture, attempt: u8) -> AcquisitionAction {
    use wgpu::CurrentSurfaceTexture as Status;
    match status {
        Status::Timeout | Status::Occluded => AcquisitionAction::Skip,
        Status::Outdated if attempt == 0 => AcquisitionAction::Reconfigure,
        Status::Lost if attempt == 0 => AcquisitionAction::Recreate,
        _ => AcquisitionAction::Fail,
    }
}

fn configure(
    device: &wgpu::Device,
    adapter: &wgpu::Adapter,
    surface: &mut Surface,
) -> Result<(), String> {
    // Re-query the current surface, including a newly recreated one. A mode
    // supported by the old surface never authorizes fallback on its replacement.
    let caps = surface.surface.get_capabilities(adapter);
    let selection = select_present_mode(surface.present.request(), &caps.present_modes)?;
    surface.config.present_mode = concrete_mode(selection.selected_mode());
    let validation = device.push_error_scope(wgpu::ErrorFilter::Validation);
    surface.surface.configure(device, &surface.config);
    if let Some(error) = pollster::block_on(validation.pop()) {
        return Err(format!("configure surface: {error}"));
    }
    surface.present = verify_present_mode(selection, surface.config.present_mode)?;
    Ok(())
}

/// The policy is separate from GPU calls so both OS modes and failure ordering
/// are exercised on every host without opening a graphics device.
async fn initialize_with_policy<T, F, Fut>(
    selection: BackendSelection,
    windows: bool,
    mut initialize: F,
) -> Result<T, String>
where
    F: FnMut(wgpu::Backends) -> Fut,
    Fut: std::future::Future<Output = Result<T, InitializationError>>,
{
    let mut errors = Vec::new();
    for backends in selection.attempts(windows) {
        match initialize(backends).await {
            Ok(value) => return Ok(value),
            Err(InitializationError::Retryable(error)) => {
                errors.push(format!("{backends:?}: {error}"))
            }
            Err(InitializationError::Terminal(error)) => {
                return Err(format!(
                    "renderer {} initialization failed ({backends:?}: {error})",
                    selection.as_str()
                ));
            }
        }
    }
    Err(format!(
        "renderer {} initialization failed ({})",
        selection.as_str(),
        errors.join("; ")
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn encode_detail_instance_evidence_reports_passed_bits_without_changing_defaults() {
        let mut descriptor = wgpu::InstanceDescriptor::new_without_display_handle();
        let flags = descriptor.flags;
        configure_instance(&mut descriptor, wgpu::Backends::DX12);
        assert_eq!(descriptor.flags, flags);
        for flags in [
            wgpu::InstanceFlags::empty(),
            wgpu::InstanceFlags::DEBUG | wgpu::InstanceFlags::VALIDATION,
            wgpu::InstanceFlags::GPU_BASED_VALIDATION
                | wgpu::InstanceFlags::VALIDATION_INDIRECT_CALL,
        ] {
            let evidence = instance_descriptor_evidence(flags);
            assert_eq!(evidence["flags_bits"], flags.bits());
            assert_eq!(
                evidence["debug"],
                flags.contains(wgpu::InstanceFlags::DEBUG)
            );
            assert_eq!(
                evidence["validation"],
                flags.contains(wgpu::InstanceFlags::VALIDATION)
            );
            assert_eq!(
                evidence["gpu_based_validation"],
                flags.contains(wgpu::InstanceFlags::GPU_BASED_VALIDATION)
            );
            assert_eq!(
                evidence["validation_indirect_call"],
                flags.contains(wgpu::InstanceFlags::VALIDATION_INDIRECT_CALL)
            );
            assert_eq!(
                evidence["application_debug_assertions"],
                cfg!(debug_assertions)
            );
            assert_eq!(evidence["environment_overrides_applied"], false);
        }
    }

    #[test]
    fn concrete_surface_modes_never_accept_automatic_or_relaxed_substitutes() {
        let other = [
            wgpu::PresentMode::AutoVsync,
            wgpu::PresentMode::AutoNoVsync,
            wgpu::PresentMode::FifoRelaxed,
        ];
        for mode in [
            DiagnosticPresentMode::Fifo,
            DiagnosticPresentMode::Mailbox,
            DiagnosticPresentMode::Immediate,
        ] {
            let request = PresentModeRequest::Explicit(mode);
            assert!(select_present_mode(request, &other).is_err());
            let exact = concrete_mode(mode);
            let selected = select_present_mode(request, &[exact]).unwrap();
            assert_eq!(
                verify_present_mode(selected, exact).unwrap().request(),
                request
            );
            for substitute in other {
                assert!(verify_present_mode(selected, substitute).is_err());
            }
        }
        assert_eq!(
            concrete_mode(PresentModeRequest::default().mode()),
            wgpu::PresentMode::Fifo
        );
    }

    #[test]
    fn changed_surface_capabilities_require_the_original_request_again() {
        let request = PresentModeRequest::Explicit(DiagnosticPresentMode::Mailbox);
        let original = select_present_mode(
            request,
            &[wgpu::PresentMode::Fifo, wgpu::PresentMode::Mailbox],
        )
        .unwrap();
        let configured = verify_present_mode(original, wgpu::PresentMode::Mailbox).unwrap();
        assert!(select_present_mode(configured.request(), &[wgpu::PresentMode::Fifo]).is_err());
        assert!(select_present_mode(configured.request(), &[wgpu::PresentMode::Mailbox]).is_ok());
    }

    #[test]
    fn unsupported_present_mode_is_terminal_even_for_windows_auto() {
        let mut attempted = Vec::new();
        let error = pollster::block_on(initialize_with_policy::<(), _, _>(
            BackendSelection::Auto,
            true,
            |backends| {
                attempted.push(backends);
                let error = select_present_mode(
                    PresentModeRequest::Explicit(DiagnosticPresentMode::Mailbox),
                    &[wgpu::PresentMode::Fifo],
                )
                .unwrap_err();
                std::future::ready(Err(InitializationError::Terminal(error)))
            },
        ))
        .unwrap_err();
        assert!(error.contains("not advertised"));
        assert_eq!(attempted, [wgpu::Backends::DX12]);
    }

    #[test]
    fn low_level_renderer_parser_stops_at_end_of_options() {
        assert_eq!(
            BackendSelection::from_args(["--", "--renderer=dx12"]).unwrap(),
            BackendSelection::Auto
        );
        assert_eq!(
            BackendSelection::from_args(["--renderer=dx12", "--", "--renderer=gl"]).unwrap(),
            BackendSelection::Dx12
        );
    }

    #[test]
    fn uncaptured_error_classes_retain_their_diagnostics_as_fatal_results() {
        let source = || Box::new(std::io::Error::other("driver failure")) as wgpu::ErrorSource;
        for (error, expected) in [
            (
                wgpu::Error::OutOfMemory { source: source() },
                "uncaptured GPU out of memory error: Out of Memory; source: driver failure",
            ),
            (
                wgpu::Error::Internal {
                    source: source(),
                    description: "submission rejected by driver".into(),
                },
                "uncaptured GPU internal error: submission rejected by driver; source: driver failure",
            ),
            (
                wgpu::Error::Validation {
                    source: source(),
                    description: "present validation failed".into(),
                },
                "uncaptured GPU validation error: present validation failed; source: driver failure",
            ),
        ] {
            let failures = DeviceFailures::default();
            assert!(failures.check().is_ok());
            failures.uncaptured(error);
            assert_eq!(failures.check().unwrap_err(), expected);
            assert_eq!(failures.check().unwrap_err(), expected);
        }
    }

    #[test]
    fn device_loss_callback_is_thread_safe_sticky_and_preserves_the_first_failure() {
        for reason in [
            wgpu::DeviceLostReason::Unknown,
            wgpu::DeviceLostReason::Destroyed,
        ] {
            let failures = DeviceFailures::default();
            let callback = failures.clone();
            std::thread::spawn(move || callback.lost(reason, "adapter removed".into()))
                .join()
                .unwrap();
            let first = format!("GPU device lost ({reason:?}): adapter removed");
            assert_eq!(failures.check().unwrap_err(), first);
            failures.record("secondary surface recovery failure".into());
            assert_eq!(failures.check().unwrap_err(), first);
        }
    }

    #[test]
    fn device_loss_does_not_replace_an_earlier_out_of_memory_error() {
        let failures = DeviceFailures::default();
        failures.uncaptured(wgpu::Error::OutOfMemory {
            source: Box::new(std::io::Error::other("allocation exhausted")),
        });
        let first = failures.check().unwrap_err();
        failures.lost(
            wgpu::DeviceLostReason::Unknown,
            "device became invalid".into(),
        );
        assert_eq!(failures.check().unwrap_err(), first);
    }

    #[test]
    fn dx12_compiler_is_explicit_system_fxc_for_every_instance_policy() {
        for backends in [wgpu::Backends::DX12, wgpu::Backends::PRIMARY] {
            let mut descriptor = wgpu::InstanceDescriptor::new_without_display_handle();
            descriptor.backend_options.dx12.shader_compiler = wgpu::Dx12Compiler::Auto;
            configure_instance(&mut descriptor, backends);
            assert_eq!(descriptor.backends, backends);
            assert!(matches!(
                descriptor.backend_options.dx12.shader_compiler,
                wgpu::Dx12Compiler::Fxc
            ));
        }
    }
    #[test]
    fn lost_and_outdated_recover_once_while_timeout_and_occlusion_skip() {
        use wgpu::CurrentSurfaceTexture as Status;
        assert_eq!(
            acquisition_action(&Status::Lost, 0),
            AcquisitionAction::Recreate
        );
        assert_eq!(
            acquisition_action(&Status::Outdated, 0),
            AcquisitionAction::Reconfigure
        );
        for attempt in [0, 1] {
            assert_eq!(
                acquisition_action(&Status::Timeout, attempt),
                AcquisitionAction::Skip
            );
            assert_eq!(
                acquisition_action(&Status::Occluded, attempt),
                AcquisitionAction::Skip
            );
            assert_eq!(
                acquisition_action(&Status::Validation, attempt),
                AcquisitionAction::Fail
            );
        }
        assert_eq!(
            acquisition_action(&Status::Lost, 1),
            AcquisitionAction::Fail
        );
        assert_eq!(
            acquisition_action(&Status::Outdated, 1),
            AcquisitionAction::Fail
        );
    }

    #[test]
    fn windows_auto_is_dx12_first_and_primary_only_after_failure() {
        let mut attempted = Vec::new();
        let result = pollster::block_on(initialize_with_policy(
            BackendSelection::Auto,
            true,
            |backends| {
                attempted.push(backends);
                std::future::ready(if backends == wgpu::Backends::DX12 {
                    Err("DX12 initialization unavailable".into())
                } else {
                    Ok(42)
                })
            },
        ));
        assert_eq!(result.unwrap(), 42);
        assert_eq!(attempted, [wgpu::Backends::DX12, wgpu::Backends::PRIMARY]);
    }

    #[test]
    fn successful_windows_dx12_does_not_initialize_primary() {
        let mut attempted = Vec::new();
        pollster::block_on(initialize_with_policy(
            BackendSelection::Auto,
            true,
            |backends| {
                attempted.push(backends);
                std::future::ready(Ok(()))
            },
        ))
        .unwrap();
        assert_eq!(attempted, [wgpu::Backends::DX12]);
    }

    #[test]
    fn explicit_dx12_failure_never_falls_back_on_either_platform() {
        for windows in [false, true] {
            let mut attempted = Vec::new();
            let error = pollster::block_on(initialize_with_policy::<(), _, _>(
                BackendSelection::Dx12,
                windows,
                |backends| {
                    attempted.push(backends);
                    std::future::ready(Err("DX12 initialization unavailable".into()))
                },
            ))
            .unwrap_err();
            assert!(error.contains("DX12 initialization unavailable"));
            assert_eq!(attempted, [wgpu::Backends::DX12]);
        }
    }

    #[test]
    fn non_windows_auto_initializes_primary_once() {
        let mut attempted = Vec::new();
        let _ = pollster::block_on(initialize_with_policy::<(), _, _>(
            BackendSelection::Auto,
            false,
            |backends| {
                attempted.push(backends);
                std::future::ready(Err("unavailable".into()))
            },
        ));
        assert_eq!(attempted, [wgpu::Backends::PRIMARY]);
    }

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
