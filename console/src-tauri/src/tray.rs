//! System tray integration for the desktop shell.

use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::Duration;

use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager,
};

use crate::backend;
use serde::{Deserialize, Serialize};

const SHOW_MENU_ID: &str = "show";
const QUIT_MENU_ID: &str = "quit";

/// How long Rust waits for the frontend to acknowledge a close request before
/// falling back to minimize-to-tray. The frontend acks immediately (before it
/// renders the prompt), so this only elapses when no listener is attached
/// (e.g. during a document reload).
const CLOSE_ACK_TIMEOUT: Duration = Duration::from_millis(1500);

/// Emitted to the frontend when the user closes the window, asking it to honor
/// the remembered preference or show the close prompt.
pub(crate) const CLOSE_REQUESTED_EVENT: &str = "qwenpaw-close-requested";

#[derive(Clone)]
struct TrayMenuItems {
    show: MenuItem<tauri::Wry>,
    quit: MenuItem<tauri::Wry>,
    stop_blocked: String,
}

#[derive(Clone, Copy, Deserialize, Serialize)]
#[serde(rename_all = "kebab-case")]
pub(crate) enum CloseAction {
    MinimizeToTray,
    Quit,
    StopService,
}

#[derive(Default)]
pub(crate) struct TrayState {
    menu_items: Mutex<Option<TrayMenuItems>>,
    /// Bumped on every close request so a stale fallback can detect that a newer
    /// request superseded it.
    close_seq: AtomicU64,
    /// Highest close sequence the frontend has acknowledged.
    close_ack: AtomicU64,
    close_action: Mutex<Option<CloseAction>>,
    preference_write: tokio::sync::Mutex<()>,
    quitting: AtomicBool,
    shutdown_complete: AtomicBool,
}

/// Creates the tray icon and its cross-platform menu actions.
pub(crate) fn setup(app: &mut tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    let path = app.path().app_config_dir()?.join("close-action.json");
    let preference = std::fs::read(path)
        .ok()
        .and_then(|bytes| serde_json::from_slice::<CloseAction>(&bytes).ok());
    *app.state::<TrayState>()
        .close_action
        .lock()
        .expect("tray state poisoned") = preference;
    let show = MenuItem::with_id(app, SHOW_MENU_ID, "Show Window", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, QUIT_MENU_ID, "Quit App", true, None::<&str>)?;
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
            stop_blocked:
                "QwenPaw is still in use in other windows or apps. Close them before quitting completely."
                    .into(),
        });
    }

    let mut tray = TrayIconBuilder::new()
        .menu(&menu)
        .tooltip("QwenPaw Desktop")
        .on_menu_event(|app, event| match event.id().as_ref() {
            SHOW_MENU_ID => show_main_window(app),
            QUIT_MENU_ID => request_quit(app),
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

/// Window close honors the saved choice; explicit quit always offers the
/// last client a choice between background tasks and quitting completely.
pub(crate) fn request_close(app: &tauri::AppHandle) {
    request_exit(app, true);
}

pub(crate) fn request_quit(app: &tauri::AppHandle) {
    request_exit(app, false);
}

fn request_exit(app: &tauri::AppHandle, honor_preference: bool) {
    let seq = app
        .state::<TrayState>()
        .close_seq
        .fetch_add(1, Ordering::SeqCst)
        + 1;
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        let others = backend::other_clients(&app).await;
        if app.state::<TrayState>().close_seq.load(Ordering::SeqCst) != seq || is_quitting(&app) {
            return;
        }
        if matches!(others, Ok(count) if count > 0) {
            exit_app(&app, 0);
            return;
        }
        // If the runtime is unavailable, keep both choices accessible.
        let action = if honor_preference {
            *app.state::<TrayState>()
                .close_action
                .lock()
                .expect("tray state poisoned")
        } else {
            None
        };
        match action {
            Some(CloseAction::MinimizeToTray) => hide_main_window(&app),
            Some(CloseAction::Quit) => exit_app(&app, 0),
            Some(CloseAction::StopService) => {
                if stop_service(app.clone()).await.is_ok() {
                    exit_app(&app, 0);
                } else {
                    show_close_prompt(&app, seq);
                }
            }
            None => show_close_prompt(&app, seq),
        }
    });
}

fn show_close_prompt(app: &tauri::AppHandle, seq: u64) {
    show_main_window(app);
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
    exit_app(&app, 0);
}

#[tauri::command]
pub(crate) async fn stop_service(app: tauri::AppHandle) -> Result<(), String> {
    backend::stop_and_wait(&app).await.map_err(|error| {
        if error == backend::OTHER_CLIENTS_ERROR {
            app.state::<TrayState>()
                .menu_items
                .lock()
                .expect("tray state poisoned")
                .as_ref()
                .map(|items| items.stop_blocked.clone())
                .unwrap_or(error)
        } else {
            error
        }
    })
}

/// Updates the tray menu labels with frontend-provided translations.
#[tauri::command]
pub(crate) fn set_tray_labels(
    app: tauri::AppHandle,
    show_window: String,
    quit: String,
    stop_blocked: String,
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
        if let Some(stored) = app
            .state::<TrayState>()
            .menu_items
            .lock()
            .expect("tray state poisoned")
            .as_mut()
        {
            stored.stop_blocked = stop_blocked;
        }
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

pub(crate) fn is_quitting(app: &tauri::AppHandle) -> bool {
    app.state::<TrayState>().quitting.load(Ordering::SeqCst)
}

pub(crate) fn shutdown_complete(app: &tauri::AppHandle) -> bool {
    app.state::<TrayState>()
        .shutdown_complete
        .load(Ordering::SeqCst)
}

#[tauri::command]
pub(crate) fn get_close_action(app: tauri::AppHandle) -> Option<CloseAction> {
    *app.state::<TrayState>()
        .close_action
        .lock()
        .expect("tray state poisoned")
}

#[tauri::command]
pub(crate) async fn set_close_action(
    app: tauri::AppHandle,
    action: Option<CloseAction>,
) -> Result<(), String> {
    let state = app.state::<TrayState>();
    let _write = state.preference_write.lock().await;
    let path = app
        .path()
        .app_config_dir()
        .map_err(|err| err.to_string())?
        .join("close-action.json");
    tauri::async_runtime::spawn_blocking(move || -> Result<(), String> {
        let parent = path.parent().ok_or("Missing preference directory")?;
        std::fs::create_dir_all(parent).map_err(|err| err.to_string())?;
        let bytes = serde_json::to_vec(&action).map_err(|err| err.to_string())?;
        let temporary = path.with_extension("tmp");
        std::fs::write(&temporary, bytes).map_err(|err| err.to_string())?;
        std::fs::rename(temporary, path).map_err(|err| err.to_string())
    })
    .await
    .map_err(|err| err.to_string())??;
    *app.state::<TrayState>()
        .close_action
        .lock()
        .expect("tray state poisoned") = action;
    Ok(())
}

pub(crate) fn exit_app(app: &tauri::AppHandle, code: i32) {
    if app
        .state::<TrayState>()
        .quitting
        .swap(true, Ordering::SeqCst)
    {
        return;
    }
    // Destroy the document and release this client without stopping shared work.
    if let Some(window) = app.get_webview_window("main") {
        if let Err(err) = window.destroy() {
            log::warn!("[desktop] failed to destroy window: {err}");
            let _ = window.hide();
        }
    }
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        backend::detach(&app);
        let handle = app.clone();
        let _ = tauri::async_runtime::spawn_blocking(move || {
            if let Err(error) = crate::computer_use_runtime::stop(&handle) {
                log::warn!("[computer-use] failed to stop helper: {error}");
            }
        })
        .await;
        app.state::<TrayState>()
            .shutdown_complete
            .store(true, Ordering::SeqCst);
        app.exit(code);
    });
}
