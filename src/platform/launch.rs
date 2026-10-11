//! Application runtime selection before either window backend is initialized.
use crate::render::present_policy::{parse_present_mode_args, PresentModeRequest};

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct LaunchOptions {
    pub renderer: Option<String>,
    pub force_fallback_adapter: bool,
    pub ui_theme: Option<std::path::PathBuf>,
    pub present_mode: PresentModeRequest,
    pub gpu_timestamps: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum RuntimeChoice {
    Legacy,
    Wgpu {
        requested: String,
        force_fallback: bool,
    },
}

impl LaunchOptions {
    pub fn parse(args: &[String]) -> Result<Self, String> {
        let mut options = Self {
            present_mode: parse_present_mode_args(args).map_err(|error| error.to_string())?,
            ..Self::default()
        };
        let mut index = 0;
        while index < args.len() {
            let arg = &args[index];
            if arg == "--" {
                break;
            }
            if arg == "--gpu-timestamps" {
                if options.gpu_timestamps
                    || args
                        .get(index + 1)
                        .is_some_and(|next| !next.starts_with("--"))
                {
                    return Err("--gpu-timestamps is a boolean flag accepted only once".into());
                }
                options.gpu_timestamps = true;
                index += 1;
                continue;
            }
            if arg.starts_with("--gpu-timestamps=") {
                return Err("--gpu-timestamps is a boolean flag and takes no value".into());
            }
            if arg == "--ui-theme" || arg.starts_with("--ui-theme=") {
                if options.ui_theme.is_some() {
                    return Err("--ui-theme may be specified only once".into());
                }
                let path = if arg == "--ui-theme" {
                    index += 1;
                    args.get(index)
                        .ok_or("--ui-theme requires a path")?
                        .as_str()
                } else {
                    arg.strip_prefix("--ui-theme=")
                        .expect("matched theme option")
                };
                if path.is_empty() || path.starts_with("--") {
                    return Err("--ui-theme requires a path".into());
                }
                options.ui_theme = Some(path.into());
                index += 1;
                continue;
            }
            let renderer = if arg == "--renderer" {
                index += 1;
                Some(
                    args.get(index)
                        .ok_or("--renderer requires a value")?
                        .as_str(),
                )
            } else {
                arg.strip_prefix("--renderer=")
            };
            if let Some(renderer) = renderer {
                if options.renderer.is_some() {
                    return Err("--renderer may be specified only once".into());
                }
                if !matches!(renderer, "auto" | "dx12" | "vulkan" | "metal" | "gl") {
                    return Err(format!(
                        "unknown renderer {renderer:?}; expected auto|dx12|vulkan|metal|gl"
                    ));
                }
                options.renderer = Some(renderer.to_owned());
            } else if arg == "--force-fallback-adapter" {
                if options.force_fallback_adapter {
                    return Err("--force-fallback-adapter may be specified only once".into());
                }
                if args
                    .get(index + 1)
                    .is_some_and(|next| !next.starts_with("--"))
                {
                    return Err(
                        "--force-fallback-adapter is a boolean flag and takes no value".into(),
                    );
                }
                options.force_fallback_adapter = true;
            } else if arg.starts_with("--force-fallback-adapter=") {
                return Err("--force-fallback-adapter is a boolean flag and takes no value".into());
            }
            index += 1;
        }
        Ok(options)
    }

    /// Legacy remains the default until the human DX12 cutover sign-off. An
    /// explicitly requested native API never silently becomes legacy OpenGL.
    pub fn runtime(
        &self,
        legacy_available: bool,
        wgpu_available: bool,
    ) -> Result<RuntimeChoice, String> {
        let legacy =
            self.renderer.as_deref() == Some("gl") || (self.renderer.is_none() && legacy_available);
        if legacy {
            if self.gpu_timestamps {
                return Err("--gpu-timestamps requires the native wgpu runtime".into());
            }
            if self.present_mode.is_explicit() {
                return Err("--present-mode requires the native wgpu runtime; select --renderer=dx12 or another native backend".into());
            }
            if !legacy_available {
                return Err("legacy OpenGL is unavailable; build with legacy-macroquad".into());
            }
            if self.force_fallback_adapter {
                return Err("--force-fallback-adapter requires an explicit wgpu renderer, such as --renderer=dx12".into());
            }
            return Ok(RuntimeChoice::Legacy);
        }
        if !wgpu_available {
            return Err("requested renderer is unavailable; build with wgpu-runtime".into());
        }
        Ok(RuntimeChoice::Wgpu {
            requested: self.renderer.clone().unwrap_or_else(|| "auto".into()),
            force_fallback: self.force_fallback_adapter,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn parse(args: &[&str]) -> Result<LaunchOptions, String> {
        LaunchOptions::parse(&args.iter().map(|s| (*s).to_owned()).collect::<Vec<_>>())
    }
    #[test]
    fn gpu_timestamp_flag_is_explicit_boolean_and_requires_native_runtime() {
        assert!(!parse(&[]).unwrap().gpu_timestamps);
        assert!(!parse(&["--", "--gpu-timestamps"]).unwrap().gpu_timestamps);
        let enabled = parse(&["--renderer=dx12", "--gpu-timestamps"]).unwrap();
        assert!(enabled.gpu_timestamps);
        assert!(matches!(
            enabled.runtime(true, true),
            Ok(RuntimeChoice::Wgpu { .. })
        ));
        assert!(parse(&["--gpu-timestamps"])
            .unwrap()
            .runtime(true, true)
            .is_err());
        assert!(parse(&["--renderer=gl", "--gpu-timestamps"])
            .unwrap()
            .runtime(true, true)
            .is_err());
        for args in [
            vec!["--gpu-timestamps", "--gpu-timestamps"],
            vec!["--gpu-timestamps=true"],
            vec!["--gpu-timestamps", "true"],
        ] {
            assert!(parse(&args).is_err());
        }
    }
    #[test]
    fn present_request_is_retained_and_explicit_legacy_modes_are_rejected() {
        use crate::render::present_policy::DiagnosticPresentMode;
        for mode in ["fifo", "mailbox", "immediate"] {
            let flag = format!("--present-mode={mode}");
            let options = parse(&["--renderer=dx12", &flag]).unwrap();
            assert_eq!(options.present_mode.mode().label(), mode);
            assert!(options.present_mode.is_explicit());
            assert!(matches!(
                options.runtime(true, true),
                Ok(RuntimeChoice::Wgpu { .. })
            ));
            assert!(parse(&["--renderer=gl", &flag])
                .unwrap()
                .runtime(true, true)
                .is_err());
            assert!(parse(&[&flag]).unwrap().runtime(true, true).is_err());
            assert!(parse(&[&flag]).unwrap().runtime(false, true).is_ok());
        }
        let defaults = parse(&[]).unwrap();
        assert_eq!(defaults.present_mode.mode(), DiagnosticPresentMode::Fifo);
        assert!(!defaults.present_mode.is_explicit());
        assert_eq!(defaults.runtime(true, true).unwrap(), RuntimeChoice::Legacy);
    }
    #[test]
    fn renderer_and_present_options_share_the_end_of_options_boundary() {
        let options = parse(&[
            "--",
            "--renderer=dx12",
            "--present-mode=immediate",
            "--force-fallback-adapter",
            "--ui-theme=ignored.css",
        ])
        .unwrap();
        assert_eq!(options, LaunchOptions::default());
        let options = parse(&[
            "--renderer=dx12",
            "--present-mode=mailbox",
            "--",
            "--renderer=gl",
            "--present-mode=fifo",
        ])
        .unwrap();
        assert_eq!(options.renderer.as_deref(), Some("dx12"));
        assert_eq!(options.present_mode.mode().label(), "mailbox");
    }
    #[test]
    fn legacy_default_and_explicit_auto_are_distinct_until_cutover() {
        assert_eq!(
            parse(&[]).unwrap().runtime(true, true).unwrap(),
            RuntimeChoice::Legacy
        );
        assert_eq!(
            parse(&["--renderer=auto"])
                .unwrap()
                .runtime(true, true)
                .unwrap(),
            RuntimeChoice::Wgpu {
                requested: "auto".into(),
                force_fallback: false
            }
        );
        assert_eq!(
            parse(&[]).unwrap().runtime(false, true).unwrap(),
            RuntimeChoice::Wgpu {
                requested: "auto".into(),
                force_fallback: false
            }
        );
    }
    #[test]
    fn explicit_dx12_and_software_request_are_preserved() {
        let options = parse(&[
            "game",
            "--renderer",
            "dx12",
            "--force-fallback-adapter",
            "--no-update",
        ])
        .unwrap();
        assert_eq!(
            options.runtime(true, true).unwrap(),
            RuntimeChoice::Wgpu {
                requested: "dx12".into(),
                force_fallback: true
            }
        );
        assert!(options.runtime(true, false).is_err());
    }
    #[test]
    fn boolean_flag_rejects_value_forms_and_duplicates() {
        for args in [
            vec!["--force-fallback-adapter=true"],
            vec!["--force-fallback-adapter", "false"],
            vec!["--force-fallback-adapter", "--force-fallback-adapter"],
        ] {
            assert!(parse(&args).is_err(), "{args:?}");
        }
        assert!(parse(&["--renderer=gl", "--force-fallback-adapter"])
            .unwrap()
            .runtime(true, true)
            .is_err());
    }
    #[test]
    fn unknown_missing_and_repeated_backends_fail_closed() {
        for args in [
            vec!["--renderer"],
            vec!["--renderer="],
            vec!["--renderer=unknown"],
            vec!["--renderer=dx12", "--renderer", "gl"],
        ] {
            assert!(parse(&args).is_err(), "{args:?}");
        }
        assert!(parse(&["--renderer=gl"])
            .unwrap()
            .runtime(false, true)
            .is_err());
        assert!(parse(&[]).unwrap().runtime(false, false).is_err());
    }
    #[test]
    fn theme_paths_are_explicit_bounded_options_without_consuming_other_flags() {
        let options = parse(&[
            "--ui-theme=themes/native.css",
            "--renderer=dx12",
            "--no-update",
        ])
        .unwrap();
        assert_eq!(
            options.ui_theme.as_deref(),
            Some(std::path::Path::new("themes/native.css"))
        );
        assert_eq!(options.renderer.as_deref(), Some("dx12"));
        assert_eq!(
            parse(&["--ui-theme", "theme with spaces.css"])
                .unwrap()
                .ui_theme,
            Some("theme with spaces.css".into())
        );
        for args in [
            vec!["--ui-theme"],
            vec!["--ui-theme="],
            vec!["--ui-theme", "--no-update"],
            vec!["--ui-theme=a", "--ui-theme=b"],
        ] {
            assert!(parse(&args).is_err(), "{args:?}");
        }
    }
}
