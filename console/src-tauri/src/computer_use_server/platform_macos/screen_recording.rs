//! Screen Recording authorization for the macOS Computer Use helper.
//!
//! TCC presents this permission for an AppKit application. The helper's RPC
//! workers perform capture, so they synchronously hand the interactive request
//! to the helper's main AppKit run loop instead of attempting to present it
//! from a socket worker.

use core_graphics::access::ScreenCaptureAccess;
use dispatch2::run_on_main;

pub(crate) fn screen_recording_authorized() -> bool {
    ScreenCaptureAccess::default().preflight()
}

pub(crate) fn request_screen_recording_access() {
    run_on_main(|_| {
        let access = ScreenCaptureAccess::default();
        if !access.preflight() {
            let _ = access.request();
        }
    });
}
