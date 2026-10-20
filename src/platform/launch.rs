//! Application runtime selection before the native window is initialized.

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct LaunchOptions {
    pub renderer: Option<String>,
    pub force_fallback_adapter: bool,
    pub ui_theme: Option<std::path::PathBuf>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum RuntimeChoice {
    Wgpu {
        requested: String,
        force_fallback: bool,
    },
}

impl LaunchOptions {
    pub fn parse(args: &[String]) -> Result<Self, String> {
        let mut options = Self::default();
        let mut index = 0;
        while index < args.len() {
            let arg = &args[index];
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
                if !matches!(renderer, "auto" | "dx12" | "vulkan" | "metal") {
                    return Err(format!(
                        "unknown renderer {renderer:?}; expected auto|dx12|vulkan|metal"
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

    /// wgpu is the only window runtime. An unavailable explicit native API
    /// fails closed; it never falls back to a removed renderer.
    pub fn runtime(&self, wgpu_available: bool) -> Result<RuntimeChoice, String> {
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
    fn wgpu_is_the_only_default_and_requires_its_feature() {
        for args in [vec![], vec!["--renderer=auto"]] {
            assert_eq!(
                parse(&args).unwrap().runtime(true).unwrap(),
                RuntimeChoice::Wgpu {
                    requested: "auto".into(),
                    force_fallback: false
                }
            );
            assert!(parse(&args).unwrap().runtime(false).is_err());
        }
        assert!(parse(&["--renderer=gl"]).is_err());
        assert!(parse(&["--renderer", "gl"]).is_err());
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
            options.runtime(true).unwrap(),
            RuntimeChoice::Wgpu {
                requested: "dx12".into(),
                force_fallback: true
            }
        );
        assert!(options.runtime(false).is_err());
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
        assert!(parse(&["--renderer=gl", "--force-fallback-adapter"]).is_err());
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
        assert!(parse(&["--renderer=gl"]).is_err());
        assert!(parse(&[]).unwrap().runtime(false).is_err());
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
