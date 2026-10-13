//! Contract-level permission policy for the shared automation service.
//!
//! Platform leaves answer whether a concrete permission is available and how
//! to request it.  They do not decide which business method needs it.  Keeping
//! that mapping here prevents Computer Use and the future EventStream contract
//! from growing two inconsistent permission policies.

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum Permission {
    Accessibility,
    ScreenRecording,
    InputMonitoring,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub(super) struct PermissionStatus {
    pub(super) accessibility: bool,
    pub(super) screen_recording: bool,
    pub(super) input_monitoring: bool,
}

#[derive(Default)]
pub(super) struct PermissionBroker;

impl PermissionBroker {
    pub(super) fn ensure_for(&self, method: &str) -> Result<(), (&'static str, String)> {
        super::ensure_permissions(Self::computer_use_requirements(method))
    }

    pub(super) fn ensure_recording(&self) -> Result<(), (&'static str, String)> {
        super::ensure_permissions(Self::recording_requirements())
    }

    /// Observe revocation without showing permission prompts from maintenance.
    pub(super) fn recording_granted() -> bool {
        Self::recording_requirements()
            .iter()
            .all(|permission| super::permission_granted(*permission))
    }

    pub(super) fn request_recording(&self) {
        for permission in Self::recording_requirements() {
            if !super::permission_granted(*permission) {
                super::request_permission(*permission);
            }
        }
    }

    pub(super) fn recording_status() -> PermissionStatus {
        PermissionStatus {
            accessibility: super::permission_granted(Permission::Accessibility),
            screen_recording: super::permission_granted(Permission::ScreenRecording),
            input_monitoring: super::permission_granted(Permission::InputMonitoring),
        }
    }

    pub(super) fn computer_use_requirements(method: &str) -> &'static [Permission] {
        use Permission::{Accessibility, ScreenRecording};
        match method {
            "observe_window" => &[ScreenRecording, Accessibility],
            "click" | "close_window" | "drag" | "invoke_element" | "press_key" | "scroll"
            | "sequence" | "set_value" | "type_text" => &[Accessibility],
            _ => &[],
        }
    }

    /// Permissions the EventStream recorder owns before event capture.
    ///
    /// Screen Recording remains observable in status but is not required
    /// until an evidence-frame producer is enabled.
    pub(super) fn recording_requirements() -> &'static [Permission] {
        use Permission::{Accessibility, InputMonitoring};
        &[InputMonitoring, Accessibility]
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn observation_and_actions_have_explicit_permission_sets() {
        assert_eq!(
            PermissionBroker::computer_use_requirements("observe_window"),
            &[Permission::ScreenRecording, Permission::Accessibility],
        );
        assert_eq!(
            PermissionBroker::computer_use_requirements("sequence"),
            &[Permission::Accessibility],
        );
        assert!(PermissionBroker::computer_use_requirements("list_apps").is_empty());
        assert!(PermissionBroker::computer_use_requirements("launch_app").is_empty());
    }

    #[test]
    fn recording_policy_is_owned_by_the_same_broker() {
        assert_eq!(
            PermissionBroker::recording_requirements(),
            &[Permission::InputMonitoring, Permission::Accessibility],
        );
    }
}
