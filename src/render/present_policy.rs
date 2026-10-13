//! Opt-in, capability-checked presentation diagnostics. No GPU or environment access.
//!
//! Integration contract: parse the process arguments once; translate the surface's
//! advertised concrete `wgpu::PresentMode` values to `DiagnosticPresentMode`; select
//! before configuring the surface; and call `verify_applied` only after successful
//! configuration with the mode retained in that configuration. Preserve this request
//! on resize/recovery and recheck capabilities if the surface or adapter changes.
//! Never map `AutoVsync`, `AutoNoVsync`, or `FifoRelaxed` to one of these modes.
//!
//! Export the requested and actual configuration labels, the explicit-request flag,
//! and the existing run/adapter/backend identity together. An unsupported request
//! is a diagnostic error, not permission to fall back. With no flag the request is
//! FIFO, preserving the production default. The launch/device integration uses
//! this policy; native validation of that integration remains a separate check.
//!
//! A configured mode does not prove display cadence, tearing behavior, or GPU time.
//! In particular, Immediate does not remove the DX12 waitable-object acquire wait.
//! Keep the surface-acquire and present-call CPU spans in every mode comparison.

use std::fmt;

const FLAG: &str = "--present-mode";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DiagnosticPresentMode {
    Fifo,
    Mailbox,
    Immediate,
}

impl DiagnosticPresentMode {
    pub const fn label(self) -> &'static str {
        match self {
            Self::Fifo => "fifo",
            Self::Mailbox => "mailbox",
            Self::Immediate => "immediate",
        }
    }

    fn parse(value: &str) -> Result<Self, PresentPolicyError> {
        match value {
            "fifo" => Ok(Self::Fifo),
            "mailbox" => Ok(Self::Mailbox),
            "immediate" => Ok(Self::Immediate),
            _ => Err(PresentPolicyError::InvalidValue(value.to_owned())),
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum PresentModeRequest {
    #[default]
    DefaultFifo,
    Explicit(DiagnosticPresentMode),
}

impl PresentModeRequest {
    pub const fn mode(self) -> DiagnosticPresentMode {
        match self {
            Self::DefaultFifo => DiagnosticPresentMode::Fifo,
            Self::Explicit(mode) => mode,
        }
    }

    pub const fn is_explicit(self) -> bool {
        matches!(self, Self::Explicit(_))
    }

    /// Only an exactly advertised concrete mode can be selected. The ordering of
    /// the supported list never changes the request, including the default FIFO.
    pub fn select(
        self,
        supported: &[DiagnosticPresentMode],
    ) -> Result<PresentModeSelection, PresentPolicyError> {
        if !supported.contains(&self.mode()) {
            return Err(PresentPolicyError::Unsupported(self.mode()));
        }
        Ok(PresentModeSelection { request: self })
    }
}

/// Accept `--present-mode=MODE` or `--present-mode MODE`. Ignore unrelated args
/// and stop at `--`. Duplicate requests are errors even when the values agree.
/// Values are deliberately exact: unknown/automatic modes never imply fallback.
pub fn parse_present_mode_args<I, S>(args: I) -> Result<PresentModeRequest, PresentPolicyError>
where
    I: IntoIterator<Item = S>,
    S: AsRef<str>,
{
    let mut args = args.into_iter();
    let mut request = PresentModeRequest::DefaultFifo;
    while let Some(argument) = args.next() {
        let argument = argument.as_ref();
        if argument == "--" {
            break;
        }
        let mode = if argument == FLAG {
            if request.is_explicit() {
                return Err(PresentPolicyError::DuplicateRequest);
            }
            let value = args.next().ok_or(PresentPolicyError::MissingValue)?;
            DiagnosticPresentMode::parse(value.as_ref())?
        } else if let Some(value) = argument.strip_prefix("--present-mode=") {
            if request.is_explicit() {
                return Err(PresentPolicyError::DuplicateRequest);
            }
            DiagnosticPresentMode::parse(value)?
        } else {
            continue;
        };
        request = PresentModeRequest::Explicit(mode);
    }
    Ok(request)
}

/// Capability-checked choice, not yet evidence of successful configuration.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct PresentModeSelection {
    request: PresentModeRequest,
}

impl PresentModeSelection {
    pub const fn request(self) -> PresentModeRequest {
        self.request
    }

    pub const fn selected_mode(self) -> DiagnosticPresentMode {
        self.request.mode()
    }

    /// The caller must supply the actual retained surface configuration only
    /// after configuration succeeds. A mismatch must not produce success evidence.
    pub fn verify_applied(
        self,
        actual: DiagnosticPresentMode,
    ) -> Result<ConfiguredPresentMode, PresentPolicyError> {
        if actual != self.selected_mode() {
            return Err(PresentPolicyError::AppliedMismatch {
                selected: self.selected_mode(),
                actual,
            });
        }
        Ok(ConfiguredPresentMode {
            request: self.request,
            actual,
        })
    }
}

/// Requested versus actual configuration, to accompany the existing run identity.
/// This does not assert that the OS/display honored a particular presentation cadence.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ConfiguredPresentMode {
    request: PresentModeRequest,
    actual: DiagnosticPresentMode,
}

impl ConfiguredPresentMode {
    pub const fn request(self) -> PresentModeRequest {
        self.request
    }

    pub const fn requested_label(self) -> &'static str {
        self.request.mode().label()
    }

    pub const fn actual_label(self) -> &'static str {
        self.actual.label()
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum PresentPolicyError {
    MissingValue,
    InvalidValue(String),
    DuplicateRequest,
    Unsupported(DiagnosticPresentMode),
    AppliedMismatch {
        selected: DiagnosticPresentMode,
        actual: DiagnosticPresentMode,
    },
}

impl fmt::Display for PresentPolicyError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::MissingValue => write!(f, "{FLAG} requires fifo, mailbox, or immediate"),
            Self::InvalidValue(value) => write!(
                f,
                "invalid {FLAG} value {value:?}; expected fifo, mailbox, or immediate"
            ),
            Self::DuplicateRequest => write!(f, "{FLAG} may be specified only once"),
            Self::Unsupported(mode) => write!(
                f,
                "requested present mode {} is not advertised by this surface; no fallback selected",
                mode.label()
            ),
            Self::AppliedMismatch { selected, actual } => write!(
                f,
                "present mode configuration mismatch: selected {}, actual {}",
                selected.label(),
                actual.label()
            ),
        }
    }
}

impl std::error::Error for PresentPolicyError {}

#[cfg(test)]
mod tests {
    use super::*;
    use DiagnosticPresentMode::{Fifo, Immediate, Mailbox};

    const ALL: [DiagnosticPresentMode; 3] = [Fifo, Mailbox, Immediate];

    #[test]
    fn absent_opt_in_preserves_fifo() {
        for args in [
            vec![],
            vec!["vector-range", "--renderer=dx12", "--windowed"],
        ] {
            let request = parse_present_mode_args(args).unwrap();
            assert_eq!(request, PresentModeRequest::DefaultFifo);
            assert!(!request.is_explicit());
            assert_eq!(request.mode(), Fifo);
            assert_eq!(request.select(&ALL).unwrap().selected_mode(), Fifo);
        }
    }

    #[test]
    fn each_exact_mode_accepts_both_argument_forms() {
        for mode in ALL {
            let equal_form = format!("{FLAG}={}", mode.label());
            for request in [
                parse_present_mode_args([equal_form.as_str()]).unwrap(),
                parse_present_mode_args([FLAG, mode.label()]).unwrap(),
            ] {
                assert_eq!(request, PresentModeRequest::Explicit(mode));
                assert!(request.is_explicit());
            }
        }
    }

    #[test]
    fn owned_process_arguments_are_supported() {
        let args = vec![
            "vector-range".to_owned(),
            "--present-mode=immediate".to_owned(),
        ];
        assert_eq!(
            parse_present_mode_args(args).unwrap(),
            PresentModeRequest::Explicit(Immediate)
        );
    }

    #[test]
    fn malformed_values_cannot_silently_select_fifo() {
        for value in [
            "",
            "FIFO",
            " fifo",
            "fifo ",
            "auto",
            "auto-vsync",
            "relaxed",
            "unknown",
        ] {
            let arg = format!("{FLAG}={value}");
            assert_eq!(
                parse_present_mode_args([arg]),
                Err(PresentPolicyError::InvalidValue(value.to_owned()))
            );
        }
        assert_eq!(
            parse_present_mode_args([FLAG]),
            Err(PresentPolicyError::MissingValue)
        );
    }

    #[test]
    fn duplicate_equal_and_conflicting_requests_are_rejected() {
        for args in [
            vec!["--present-mode=fifo", "--present-mode=fifo"],
            vec!["--present-mode=fifo", FLAG, "immediate"],
            vec![FLAG, "mailbox", "--present-mode=immediate"],
            vec![FLAG, "mailbox", FLAG, "mailbox"],
        ] {
            assert_eq!(
                parse_present_mode_args(args),
                Err(PresentPolicyError::DuplicateRequest)
            );
        }
    }

    #[test]
    fn end_of_options_and_unrelated_flags_do_not_request_a_mode() {
        assert_eq!(
            parse_present_mode_args([
                "--present-mode-extra=immediate",
                "--",
                "--present-mode=mailbox"
            ]),
            Ok(PresentModeRequest::DefaultFifo)
        );
        assert_eq!(
            parse_present_mode_args(["--present-mode=immediate", "--", "--present-mode=fifo"]),
            Ok(PresentModeRequest::Explicit(Immediate))
        );
    }

    #[test]
    fn another_option_is_rejected_as_a_separated_mode_value() {
        assert!(parse_present_mode_args([FLAG, "--renderer=dx12"]).is_err());
        assert!(parse_present_mode_args([FLAG, "--"]).is_err());
    }

    #[test]
    fn every_capability_subset_selects_exactly_the_requested_mode_or_errors() {
        for mask in 0..8 {
            let supported: Vec<_> = ALL
                .into_iter()
                .enumerate()
                .filter_map(|(index, mode)| ((mask & (1 << index)) != 0).then_some(mode))
                .collect();
            for mode in ALL {
                let request = PresentModeRequest::Explicit(mode);
                match request.select(&supported) {
                    Ok(selection) => {
                        assert!(supported.contains(&mode));
                        assert_eq!(selection.selected_mode(), mode);
                        assert_eq!(selection.request(), request);
                    }
                    Err(error) => {
                        assert!(!supported.contains(&mode));
                        assert_eq!(error, PresentPolicyError::Unsupported(mode));
                    }
                }
            }
        }
    }

    #[test]
    fn default_fifo_also_fails_closed_when_not_advertised() {
        for supported in [vec![], vec![Mailbox, Immediate]] {
            assert_eq!(
                PresentModeRequest::default().select(&supported),
                Err(PresentPolicyError::Unsupported(Fifo))
            );
        }
    }

    #[test]
    fn capability_order_and_duplicates_do_not_change_selection() {
        for supported in [
            vec![Immediate, Mailbox, Fifo],
            vec![Fifo, Fifo, Immediate, Mailbox],
        ] {
            for mode in ALL {
                assert_eq!(
                    PresentModeRequest::Explicit(mode)
                        .select(&supported)
                        .unwrap()
                        .selected_mode(),
                    mode
                );
            }
        }
    }

    #[test]
    fn actual_configuration_must_match_every_selected_mode() {
        for selected in ALL {
            let request = PresentModeRequest::Explicit(selected);
            let selection = request.select(&ALL).unwrap();
            for actual in ALL {
                let result = selection.verify_applied(actual);
                if actual == selected {
                    let configured = result.unwrap();
                    assert_eq!(configured.request(), request);
                    assert_eq!(configured.requested_label(), selected.label());
                    assert_eq!(configured.actual_label(), actual.label());
                } else {
                    assert_eq!(
                        result,
                        Err(PresentPolicyError::AppliedMismatch { selected, actual })
                    );
                }
            }
        }
    }

    #[test]
    fn default_and_explicit_fifo_have_distinct_evidence() {
        let default = PresentModeRequest::DefaultFifo
            .select(&[Fifo])
            .unwrap()
            .verify_applied(Fifo)
            .unwrap();
        let explicit = PresentModeRequest::Explicit(Fifo)
            .select(&[Fifo])
            .unwrap()
            .verify_applied(Fifo)
            .unwrap();
        assert_eq!(default.actual_label(), "fifo");
        assert_eq!(explicit.actual_label(), "fifo");
        assert!(!default.request().is_explicit());
        assert!(explicit.request().is_explicit());
        assert_ne!(default, explicit);
    }

    #[test]
    fn unsupported_diagnostic_explains_that_no_fallback_was_selected() {
        let error = PresentModeRequest::Explicit(Mailbox)
            .select(&[Fifo, Immediate])
            .unwrap_err();
        assert_eq!(
            error.to_string(),
            "requested present mode mailbox is not advertised by this surface; no fallback selected"
        );
    }
}
