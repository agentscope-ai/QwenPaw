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

use super::super::permission_broker::Permission;

static SCREEN_RECORDING_PROMPTED: AtomicBool = AtomicBool::new(false);
static ACCESSIBILITY_PROMPTED: AtomicBool = AtomicBool::new(false);
static INPUT_MONITORING_PROMPTED: AtomicBool = AtomicBool::new(false);

pub(crate) fn ensure(permissions: &[Permission]) -> Result<(), (&'static str, String)> {
    for permission in permissions {
        match permission {
            Permission::ScreenRecording if !screen_recording_authorized() => {
                request_screen_recording();
                return Err((
                    "screen_recording_permission_required",
                    "Screen Recording access is required. Grant it to QwenPaw Computer Use in System Settings, then retry."
                        .to_string(),
                ));
            }
            Permission::Accessibility if !accessibility_authorized() => {
                request_accessibility();
                return Err((
                    "accessibility_permission_required",
                    "Accessibility access is required. Grant it to QwenPaw Computer Use in System Settings, then retry."
                        .to_string(),
                ));
            }
            Permission::InputMonitoring if !input_monitoring_authorized() => {
                request_input_monitoring();
                return Err((
                    "input_monitoring_permission_required",
                    "Input Monitoring access is required. Grant it to QwenPaw Computer Use in System Settings, then retry."
                        .to_string(),
                ));
            }
            _ => {}
        }
    }
    Ok(())
}

pub(crate) fn granted(permission: Permission) -> bool {
    match permission {
        Permission::Accessibility => accessibility_authorized(),
        Permission::ScreenRecording => screen_recording_authorized(),
        Permission::InputMonitoring => input_monitoring_authorized(),
    }
}

pub(crate) fn request(permission: Permission) {
    match permission {
        Permission::Accessibility => request_accessibility(),
        Permission::ScreenRecording => request_screen_recording(),
        Permission::InputMonitoring => request_input_monitoring(),
    }
}

fn screen_recording_authorized() -> bool {
    ScreenCaptureAccess::default().preflight()
}

fn accessibility_authorized() -> bool {
    unsafe { AXIsProcessTrusted() }
}

fn input_monitoring_authorized() -> bool {
    unsafe { CGPreflightListenEventAccess() }
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

fn request_input_monitoring() {
    if INPUT_MONITORING_PROMPTED.swap(true, Ordering::Relaxed) {
        return;
    }
    run_on_main(|_| unsafe {
        let _ = CGRequestListenEventAccess();
    });
}

#[link(name = "CoreGraphics", kind = "framework")]
extern "C" {
    fn CGPreflightListenEventAccess() -> bool;
    fn CGRequestListenEventAccess() -> bool;
}
