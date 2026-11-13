//! System permissions owned by the macOS Computer Use helper.

use accessibility_sys::{
    kAXTrustedCheckOptionPrompt, AXIsProcessTrusted, AXIsProcessTrustedWithOptions,
};
use core_foundation::base::TCFType;
use core_foundation::boolean::CFBoolean;
use core_foundation::dictionary::CFDictionary;
use core_foundation::string::CFString;
use core_graphics::access::ScreenCaptureAccess;
use dispatch2::run_on_main;
use std::sync::atomic::{AtomicBool, Ordering};

static SCREEN_RECORDING_PROMPTED: AtomicBool = AtomicBool::new(false);
static ACCESSIBILITY_PROMPTED: AtomicBool = AtomicBool::new(false);

pub(crate) fn ensure_for(method: &str) -> Result<(), (&'static str, String)> {
    if method == "observe_window" && !screen_recording_authorized() {
        request_screen_recording();
        return Err((
            "screen_recording_permission_required",
            "Screen Recording access is required. Grant it to QwenPaw Computer Use in System Settings, then retry."
                .to_string(),
        ));
    }
    if needs_accessibility(method) && !accessibility_authorized() {
        request_accessibility();
        return Err((
            "accessibility_permission_required",
            "Accessibility access is required. Grant it to QwenPaw Computer Use in System Settings, then retry."
                .to_string(),
        ));
    }
    Ok(())
}

fn needs_accessibility(method: &str) -> bool {
    matches!(
        method,
        "observe_window"
            | "click"
            | "close_window"
            | "drag"
            | "invoke_element"
            | "press_key"
            | "scroll"
            | "set_value"
            | "type_text"
    )
}

fn screen_recording_authorized() -> bool {
    ScreenCaptureAccess::default().preflight()
}

fn accessibility_authorized() -> bool {
    unsafe { AXIsProcessTrusted() }
}

fn request_screen_recording() {
    if SCREEN_RECORDING_PROMPTED.swap(true, Ordering::Relaxed) {
        return;
    }
    run_on_main(|_| {
        let access = ScreenCaptureAccess::default();
        if !access.preflight() {
            let _ = access.request();
        }
    });
}

fn request_accessibility() {
    if ACCESSIBILITY_PROMPTED.swap(true, Ordering::Relaxed) {
        return;
    }
    run_on_main(|_| {
        let key = unsafe { CFString::wrap_under_get_rule(kAXTrustedCheckOptionPrompt) };
        let options: CFDictionary<CFString, CFBoolean> =
            CFDictionary::from_CFType_pairs(&[(key, CFBoolean::true_value())]);
        unsafe {
            AXIsProcessTrustedWithOptions(options.as_concrete_TypeRef());
        }
    });
}

#[cfg(test)]
mod tests {
    use super::needs_accessibility;

    #[test]
    fn only_actions_that_need_window_control_require_accessibility() {
        assert!(needs_accessibility("observe_window"));
        assert!(needs_accessibility("type_text"));
        assert!(needs_accessibility("close_window"));
        assert!(!needs_accessibility("list_apps"));
        assert!(!needs_accessibility("launch_app"));
    }
}
