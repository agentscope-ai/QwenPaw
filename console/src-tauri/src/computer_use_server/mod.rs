//! The native Computer Use helper's RPC server.
//!
//! Layered so that platform-specific code stays at the leaves: `connection`
//! accepts a host connection and serves requests in order, `dispatch` routes
//! one request through the shared guards, `approval` asks the host about an
//! application, `app_identity` names and starts one, and `state` holds what an
//! observation means. Each platform's OS calls live in its own leaf directory,
//! exposing the same function surface under a different implementation, so the
//! layers above never name a platform type.

mod app_identity;
mod approval;
mod connection;
mod dispatch;
mod framing;
mod state;

pub(super) use connection::run;

/// Version of the request/response contract this helper speaks. The host
/// refuses a helper that does not match, so a stale binary cannot half-work.
pub(crate) use crate::computer_use_protocol::VERSION as PROTOCOL_VERSION;
const MAX_FRAME_BYTES: usize = 64 * 1024 * 1024;

// Platform leaves expose the same function surface (window discovery, capture,
// UI automation, input); only the implementation differs. The shared layers
// above never name a platform-specific type directly. Each platform keeps its
// leaves in its own directory so the two never mix.
#[cfg(windows)]
mod platform_windows;
#[cfg(windows)]
use platform_windows::{
    click, close_window, desktop_locked, drag, ensure_permissions, invoke_element, is_forbidden,
    last_input_age_ms, list_apps, list_windows, observe_window, press_key, resolve_window, scroll,
    set_value, type_text, validate_observation,
};

#[cfg(target_os = "macos")]
mod platform_macos;
#[cfg(target_os = "macos")]
use platform_macos::{
    app_id_from_bundle_path, click, close_window, desktop_locked, drag, ensure_permissions,
    invoke_element, is_forbidden, last_input_age_ms, list_apps, list_windows, observe_window,
    press_key, resolve_window, scroll, set_value, target_is_frontmost, type_text,
    validate_observation,
};
