use std::path::PathBuf;
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager,
};

fn get_working_dir(app: &tauri::AppHandle) -> PathBuf {
    if let Some(explicit) = std::env::var_os("QWENPAW_WORKING_DIR") {
        PathBuf::from(explicit)
    } else if let Some(explicit) = std::env::var_os("COPAW_WORKING_DIR") {
        PathBuf::from(explicit)
    } else {
        let home = app.path().home_dir().unwrap_or_else(|_| PathBuf::from("."));
        let legacy = home.join(".copaw");
        if legacy.exists() {
            legacy
        } else {
            home.join(".qwenpaw")
        }
    }
}

pub(crate) fn get_language(app: &tauri::AppHandle) -> String {
    let settings_file = get_working_dir(app).join("settings.json");
    if settings_file.is_file() {
        if let Ok(content) = std::fs::read_to_string(settings_file) {
            if let Ok(val) = serde_json::from_str::<serde_json::Value>(&content) {
                if let Some(lang) = val.get("language").and_then(|v| v.as_str()) {
                    return lang.to_string();
                }
            }
        }
    }
    "en".to_string()
}

pub(crate) fn get_close_behavior(app: &tauri::AppHandle) -> String {
    let settings_file = get_working_dir(app).join("settings.json");
    if settings_file.is_file() {
        if let Ok(content) = std::fs::read_to_string(settings_file) {
            if let Ok(val) = serde_json::from_str::<serde_json::Value>(&content) {
                if let Some(behavior) = val.get("close_behavior").and_then(|v| v.as_str()) {
                    return behavior.to_string();
                }
            }
        }
    }
    // Default depends on platform
    if cfg!(target_os = "macos") {
        "minimize".to_string()
    } else {
        "quit".to_string()
    }
}

struct TrayTranslations {
    show_window: &'static str,
    quit: &'static str,
    tooltip: &'static str,
}

fn get_translations(lang: &str) -> TrayTranslations {
    match lang {
        "zh" => TrayTranslations {
            show_window: "显示窗口",
            quit: "退出",
            tooltip: "QwenPaw 桌面端",
        },
        "ja" => TrayTranslations {
            show_window: "ウィンドウを表示",
            quit: "終了",
            tooltip: "QwenPaw デスクトップ",
        },
        "ru" => TrayTranslations {
            show_window: "Показать окно",
            quit: "Выйти",
            tooltip: "QwenPaw Desktop",
        },
        "pt-BR" => TrayTranslations {
            show_window: "Mostrar Janela",
            quit: "Sair",
            tooltip: "QwenPaw Desktop",
        },
        "id" => TrayTranslations {
            show_window: "Tampilkan Jendela",
            quit: "Keluar",
            tooltip: "QwenPaw Desktop",
        },
        "vi" => TrayTranslations {
            show_window: "Hiển thị cửa sổ",
            quit: "Thoát",
            tooltip: "QwenPaw Desktop",
        },
        _ => TrayTranslations {
            show_window: "Show Window",
            quit: "Quit",
            tooltip: "QwenPaw Desktop",
        },
    }
}

/// Setup system tray icon and menu events.
pub fn setup(app: &mut tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    let app_handle = app.handle().clone();
    let lang = get_language(&app_handle);
    let translations = get_translations(&lang);

    let show_i = MenuItem::with_id(&app_handle, "show", translations.show_window, true, None::<&str>)?;
    let quit_i = MenuItem::with_id(&app_handle, "quit", translations.quit, true, None::<&str>)?;
    let menu = Menu::with_items(&app_handle, &[&show_i, &quit_i])?;

    let icon = app_handle
        .default_window_icon()
        .cloned()
        .ok_or("Failed to get default window icon")?;

    #[cfg(target_os = "macos")]
    let show_menu_on_left_click = true;
    #[cfg(not(target_os = "macos"))]
    let show_menu_on_left_click = false;

    let tray = TrayIconBuilder::new()
        .id("main_tray")
        .icon(icon)
        .menu(&menu)
        .show_menu_on_left_click(show_menu_on_left_click)
        .tooltip(translations.tooltip)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "show" => {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            }
            "quit" => {
                crate::backend::stop(app);
                app.exit(0);
            }
            _ => {}
        });

    #[cfg(not(target_os = "macos"))]
    let tray = tray.on_tray_icon_event(|tray, event| {
        if let TrayIconEvent::Click {
            button: MouseButton::Left,
            button_state: MouseButtonState::Up,
            ..
        } = event
        {
            let app = tray.app_handle();
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }
    });

    tray.build(app)?;

    Ok(())
}

#[tauri::command]
pub fn update_tray_menu(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(tray) = app.tray_by_id("main_tray") {
        let lang = get_language(&app);
        let translations = get_translations(&lang);

        let show_i = MenuItem::with_id(&app, "show", translations.show_window, true, None::<&str>).map_err(|e| e.to_string())?;
        let quit_i = MenuItem::with_id(&app, "quit", translations.quit, true, None::<&str>).map_err(|e| e.to_string())?;
        let menu = Menu::with_items(&app, &[&show_i, &quit_i]).map_err(|e| e.to_string())?;

        let _ = tray.set_menu(Some(menu));
        let _ = tray.set_tooltip(Some(translations.tooltip));
    }
    Ok(())
}
