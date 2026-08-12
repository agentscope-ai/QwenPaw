//! Windows Computer Use leaves.
//!
//! The RPC server, framing, transport, session/turn lifecycle, and app approval
//! are shared with macOS (see the parent `mod.rs`). Only the OS-touching leaves
//! below are platform specific: window discovery over EnumWindows, capture
//! through Windows Graphics Capture, accessibility over UI Automation, and
//! input over SendInput.

mod capture;
mod input;
mod uia;
mod wgc;
mod window;

pub(super) use capture::observe_window;
pub(super) use input::{
    click, desktop_locked, drag, input_sequence, last_input_age_ms, press_key, scroll, type_text,
};
pub(super) use uia::{invoke_element, set_value, validate_observation};
pub(super) use window::{close_window, is_forbidden, list_apps, list_windows, resolve_window};

pub(super) fn ensure_permissions(_method: &str) -> Result<(), (&'static str, String)> {
    Ok(())
}
