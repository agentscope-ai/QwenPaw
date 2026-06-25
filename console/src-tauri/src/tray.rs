//! System tray integration for the desktop shell.

use std::{
    sync::{
        atomic::{AtomicU64, Ordering},
        Mutex,
    },
    time::Duration,
};

use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager,
};

use crate::backend;

const SHOW_MENU_ID: &str = "show";
const QUIT_MENU_ID: &str = "quit";
const CLOSE_FALLBACK_DELAY: Duration = Duration::from_millis(1500);

pub(crate) const CLOSE_REQUESTED_EVENT: &str = "qwenpaw-close-requested";

#[derive(Clone)]
struct TrayMenuItems {
    show: MenuItem<tauri::Wry>,
    quit: MenuItem<tauri::Wry>,
}

pub(crate) struct TrayState {
    menu_items: Mutex<Option<TrayMenuItems>>,
    close_request_id: AtomicU64,
    close_ack_id: AtomicU64,
}

impl Default for TrayState {
    fn default() -> Self {
        Self {
            menu_items: Mutex::new(None),
            close_request_id: AtomicU64::new(0),
            close_ack_id: AtomicU64::new(0),
        }
    }
}

#[derive(Clone, Copy)]
struct TrayLabels {
    show_window: &'static str,
    quit: &'static str,
}

#[derive(Clone, serde::Serialize)]
#[serde(rename_all = "camelCase")]
struct CloseRequestPayload {
    request_id: u64,
}

/// Creates the tray icon and its cross-platform menu actions.
pub(crate) fn setup(app: &mut tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    let labels = labels_for_language(&initial_language());
    let show = MenuItem::with_id(app, SHOW_MENU_ID, labels.show_window, true, None::<&str>)?;
    let quit = MenuItem::with_id(app, QUIT_MENU_ID, labels.quit, true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show, &quit])?;

    let tray_state = app.state::<TrayState>();
    let mut menu_items = tray_state
        .menu_items
        .lock()
        .map_err(|_| "failed to lock tray menu state")?;
    *menu_items = Some(TrayMenuItems {
        show: show.clone(),
        quit: quit.clone(),
    });

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

#[tauri::command]
pub(crate) fn minimize_to_tray(app: tauri::AppHandle) {
    hide_main_window(&app);
}

#[tauri::command]
pub(crate) fn quit_app(app: tauri::AppHandle) {
    exit_app(&app);
}

#[tauri::command]
pub(crate) fn ack_close_request(app: tauri::AppHandle, request_id: u64) {
    let tray_state = app.state::<TrayState>();
    tray_state
        .close_ack_id
        .fetch_max(request_id, Ordering::SeqCst);
}

#[tauri::command]
pub(crate) fn set_tray_language(app: tauri::AppHandle, language: String) -> Result<(), String> {
    let labels = labels_for_language(&language);
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
            .set_text(labels.show_window)
            .map_err(|err| err.to_string())?;
        items
            .quit
            .set_text(labels.quit)
            .map_err(|err| err.to_string())?;
    }

    Ok(())
}

pub(crate) fn request_close(window: &tauri::Window) {
    let app = window.app_handle().clone();
    let request_id = {
        let tray_state = app.state::<TrayState>();
        tray_state.close_request_id.fetch_add(1, Ordering::SeqCst) + 1
    };

    let _ = window.emit(CLOSE_REQUESTED_EVENT, CloseRequestPayload { request_id });

    std::thread::spawn(move || {
        std::thread::sleep(CLOSE_FALLBACK_DELAY);

        let tray_state = app.state::<TrayState>();
        let is_latest_request = tray_state.close_request_id.load(Ordering::SeqCst) == request_id;
        let is_unhandled = tray_state.close_ack_id.load(Ordering::SeqCst) < request_id;
        if is_latest_request && is_unhandled {
            hide_main_window(&app);
        }
    });
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

fn initial_language() -> String {
    ["QWENPAW_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"]
        .iter()
        .filter_map(|key| std::env::var(key).ok())
        .find(|value| !value.trim().is_empty())
        .unwrap_or_else(|| "en".to_string())
}

fn labels_for_language(language: &str) -> TrayLabels {
    match normalize_language(language).as_str() {
        "zh" => TrayLabels {
            show_window: "显示窗口",
            quit: "退出",
        },
        "ja" => TrayLabels {
            show_window: "ウィンドウを表示",
            quit: "終了",
        },
        "ru" => TrayLabels {
            show_window: "Показать окно",
            quit: "Выход",
        },
        "pt" => TrayLabels {
            show_window: "Mostrar janela",
            quit: "Sair",
        },
        "id" => TrayLabels {
            show_window: "Tampilkan Jendela",
            quit: "Keluar",
        },
        "vi" => TrayLabels {
            show_window: "Hiện cửa sổ",
            quit: "Thoát",
        },
        _ => TrayLabels {
            show_window: "Show Window",
            quit: "Quit",
        },
    }
}

fn normalize_language(language: &str) -> String {
    language
        .split(['-', '_', '.', ':'])
        .next()
        .unwrap_or("en")
        .to_ascii_lowercase()
}
