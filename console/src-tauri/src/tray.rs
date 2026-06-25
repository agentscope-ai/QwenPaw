//! System tray integration for the desktop shell.

use std::sync::Mutex;

use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager,
};

use crate::backend;
use crate::settings::{self, CloseAction};

const SHOW_MENU_ID: &str = "show";
const QUIT_MENU_ID: &str = "quit";

/// Emitted to the frontend when the user closes the window and no preference
/// is remembered yet, asking it to show the close prompt.
pub(crate) const CLOSE_PROMPT_EVENT: &str = "qwenpaw-close-requested";

#[derive(Clone)]
struct TrayMenuItems {
    show: MenuItem<tauri::Wry>,
    quit: MenuItem<tauri::Wry>,
}

#[derive(Default)]
pub(crate) struct TrayState {
    menu_items: Mutex<Option<TrayMenuItems>>,
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
        tray = tray.icon(icon.clone());
        #[cfg(target_os = "macos")]
        {
            tray = tray.icon_as_template(true);
        }
    }

    tray.build(app)?;
    Ok(())
}

/// Handles a window close request. A remembered preference is honored directly
/// in Rust; otherwise the frontend is asked to prompt the user.
pub(crate) fn handle_close_requested(window: &tauri::Window) {
    let app = window.app_handle();
    match settings::remembered_close_action(app) {
        Some(CloseAction::Quit) => exit_app(app),
        Some(CloseAction::MinimizeToTray) => hide_main_window(app),
        None => {
            let _ = window.emit(CLOSE_PROMPT_EVENT, ());
        }
    }
}

/// Resolves the close prompt with the user's choice, optionally remembering it.
#[tauri::command]
pub(crate) fn resolve_close(
    app: tauri::AppHandle,
    action: CloseAction,
    remember: bool,
) -> Result<(), String> {
    if remember {
        settings::remember_close_action(&app, action)?;
    }

    match action {
        CloseAction::Quit => exit_app(&app),
        CloseAction::MinimizeToTray => hide_main_window(&app),
    }

    Ok(())
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
