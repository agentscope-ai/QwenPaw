//! Global-hotkey quick-input floating window.
//!
//! A borderless, always-on-top window summoned by a global hotkey (default
//! `alt+space`, i.e. Option+Space on macOS) so the user can ask the agent a
//! quick question without opening the full console. The window loads the
//! backend-hosted SPA at `/console/quick-input?desktop=1`. See issue #6568.

use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

use crate::backend::BackendState;

/// Label of the quick-input window (also used for capability scoping).
pub(crate) const QUICK_INPUT_WINDOW_LABEL: &str = "quick-input";

/// Tauri accelerator. On macOS `Alt` is the Option key, so this matches the
/// requested Option+Space. Kept as a single const so it is trivially
/// changeable; a settings UI for re-binding is deferred.
pub(crate) const QUICK_INPUT_HOTKEY: &str = "alt+space";

/// Show, hide, or first-create the quick-input window.
pub(crate) fn toggle_quick_input(app: &tauri::AppHandle) {
    // Window already exists: toggle visibility (re-center on show).
    if let Some(window) = app.get_webview_window(QUICK_INPUT_WINDOW_LABEL) {
        if window.is_visible().unwrap_or(false) {
            let _ = window.hide();
        } else {
            let _ = window.show();
            let _ = window.center();
            let _ = window.set_focus();
        }
        return;
    }

    // First invocation: create the window. The hotkey only fires while the
    // app is running, by which point backend::setup has resolved the port.
    let Some(port) = app.state::<BackendState>().port() else {
        log::warn!("[quick-input] backend port unknown; ignoring hotkey");
        return;
    };
    let url_string = format!("http://127.0.0.1:{port}/console/quick-input?desktop=1");
    let url = match reqwest::Url::parse(&url_string) {
        Ok(url) => url,
        Err(err) => {
            log::warn!("[quick-input] invalid url {url_string}: {err}");
            return;
        }
    };

    // Opaque borderless for MVP: transparent(true) has Windows WebView2
    // quirks (black background / broken hit-testing); transparency, blur and
    // rounded corners are deferred polish (and .transparent() is omitted —
    // the default is opaque).
    let result = WebviewWindowBuilder::new(
        app,
        QUICK_INPUT_WINDOW_LABEL,
        WebviewUrl::External(url),
    )
    .title("QwenPaw Quick Input")
    .inner_size(480.0, 640.0)
    .resizable(false)
    .decorations(false)
    .always_on_top(true)
    .center()
    .visible(true)
    .build();

    if let Err(err) = result {
        log::warn!("[quick-input] failed to build window: {err}");
    }
}

/// Register the global hotkey. Failures (e.g. the key is already claimed by
/// another app or an IME) are logged and swallowed — never block startup.
pub(crate) fn register_hotkey(app: &tauri::AppHandle) {
    use tauri_plugin_global_shortcut::GlobalShortcutExt;
    if let Err(err) = app.global_shortcut().register(QUICK_INPUT_HOTKEY) {
        log::warn!(
            "[quick-input] failed to register hotkey {QUICK_INPUT_HOTKEY:?}: {err}"
        );
    }
}
