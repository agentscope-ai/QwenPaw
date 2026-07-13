//! System tray integration for the desktop shell.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::Duration;

use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager,
};

use crate::backend;

const SHOW_MENU_ID: &str = "show";
const QUIT_MENU_ID: &str = "quit";

/// How long Rust waits for the frontend to acknowledge a close request before
/// falling back to minimize-to-tray. The frontend acks immediately (before it
/// even reads the remembered preference), so this only elapses when no listener
/// is attached (e.g. during the bootstrap-to-console navigation or a reload).
const CLOSE_ACK_TIMEOUT: Duration = Duration::from_millis(1500);

/// Emitted to the frontend when the user closes the window, asking it to honor
/// the remembered preference or show the close prompt.
pub(crate) const CLOSE_REQUESTED_EVENT: &str = "qwenpaw-close-requested";

#[derive(Clone)]
struct TrayMenuItems {
    show: MenuItem<tauri::Wry>,
    quit: MenuItem<tauri::Wry>,
}

#[derive(Default)]
pub(crate) struct TrayState {
    menu_items: Mutex<Option<TrayMenuItems>>,
    /// Bumped on every close request so a stale fallback can detect that a newer
    /// request superseded it.
    close_seq: AtomicU64,
    /// Highest close sequence the frontend has acknowledged.
    close_ack: AtomicU64,
}

/// Creates the tray icon and its cross-platform menu actions.
pub(crate) fn setup(app: &mut tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    let show = MenuItem::with_id(app, SHOW_MENU_ID, "Show Window", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, QUIT_MENU_ID, "Quit", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show, &quit])?;

    {
        let tray_state = app.state::<TrayState>();
        let mut menu_items = tray_state
            .menu_items
            .lock()
            .map_err(|_| "failed to lock tray menu state")?;
        *menu_items = Some(TrayMenuItems {
            show: show.clone(),
            quit: quit.clone(),
        });
    }

    let mut tray = TrayIconBuilder::new()
        .menu(&menu)
        .tooltip("QwenPaw Desktop")
        .on_menu_event(|app, event| match event.id().as_ref() {
            SHOW_MENU_ID => show_main_window(app),
            QUIT_MENU_ID => exit_app(app),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            let should_show = matches!(
                event,
                TrayIconEvent::Click {
                    button: MouseButton::Left,
                    button_state: MouseButtonState::Up,
                    ..
                } | TrayIconEvent::DoubleClick {
                    button: MouseButton::Left,
                    ..
                }
            );

            if should_show {
                show_main_window(tray.app_handle());
            }
        });

    if let Some(icon) = app.default_window_icon() {
        // Use the full-color app icon on every platform. The icon is a colored
        // logo, so it must NOT be flagged as a macOS template image — template
        // images are rendered as a solid monochrome silhouette, which would
        // turn the menu-bar icon into a black blob.
        tray = tray.icon(icon.clone());
    }

    tray.build(app)?;
    Ok(())
}

/// Asks the frontend to handle a window close request. The frontend honors the
/// remembered choice or shows the close prompt, then calls back into the
/// `minimize_to_tray` / `quit_app` commands.
///
/// To avoid leaving the window unclosable when no listener is attached, a
/// fallback minimizes to tray if the frontend does not `ack_close` in time.
pub(crate) fn request_close(app: &tauri::AppHandle) {
    let seq = {
        let state = app.state::<TrayState>();
        state.close_seq.fetch_add(1, Ordering::SeqCst) + 1
    };

    let _ = app.emit(CLOSE_REQUESTED_EVENT, ());

    let app = app.clone();
    std::thread::spawn(move || {
        std::thread::sleep(CLOSE_ACK_TIMEOUT);
        let state = app.state::<TrayState>();
        // A newer close request superseded this one; let its own timer decide.
        if state.close_seq.load(Ordering::SeqCst) != seq {
            return;
        }
        // The frontend acknowledged and now owns the flow (prompt or remembered
        // action), so leave it alone.
        if state.close_ack.load(Ordering::SeqCst) >= seq {
            return;
        }
        // Nobody responded: fall back to the safe, recoverable choice instead of
        // quitting, so running tasks are not lost.
        hide_main_window(&app);
    });
}

/// Acknowledges a close request so the Rust-side fallback stands down and lets
/// the frontend drive the prompt / remembered-choice flow.
#[tauri::command]
pub(crate) fn ack_close(app: tauri::AppHandle) {
    let state = app.state::<TrayState>();
    let seq = state.close_seq.load(Ordering::SeqCst);
    state.close_ack.store(seq, Ordering::SeqCst);
}

#[tauri::command]
pub(crate) fn minimize_to_tray(app: tauri::AppHandle) {
    hide_main_window(&app);
}

#[tauri::command]
pub(crate) fn quit_app(app: tauri::AppHandle) {
    exit_app(&app);
}

/// Updates the tray menu labels with frontend-provided translations.
#[tauri::command]
pub(crate) fn set_tray_labels(
    app: tauri::AppHandle,
    show_window: String,
    quit: String,
) -> Result<(), String> {
    let menu_items = {
        let tray_state = app.state::<TrayState>();
        let guard = tray_state
            .menu_items
            .lock()
            .map_err(|_| "failed to lock tray menu state".to_string())?;
        guard.clone()
    };

    if let Some(items) = menu_items {
        items
            .show
            .set_text(show_window)
            .map_err(|err| err.to_string())?;
        items.quit.set_text(quit).map_err(|err| err.to_string())?;
    }

    Ok(())
}

pub(crate) fn show_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

pub(crate) fn hide_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.hide();
    }
}

fn exit_app(app: &tauri::AppHandle) {
    backend::stop(app);
    app.exit(0);
}
