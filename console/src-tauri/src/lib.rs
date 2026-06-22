//! Tauri desktop entry point and plugin/command registration.

mod backend;
mod backend_download;
mod external_link;
mod tray;

use tauri::{Manager, RunEvent, WindowEvent};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
/// Build the desktop app, wire native plugins/commands, and stop the backend on exit.
pub fn run() {
    let build_result = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            backend_download::download_backend_file,
            backend::backend_port,
            backend::backend_startup_error,
            backend::restart_backend,
            external_link::open_external_link,
            tray::update_tray_menu,
        ])
        .manage(backend::BackendState::default())
        .setup(|app| {
            backend::setup(app)?;
            tray::setup(app)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                let behavior = tray::get_close_behavior(window.app_handle());
                if behavior == "minimize" {
                    let _ = window.hide();
                    api.prevent_close();
                } else {
                    backend::stop(window.app_handle());
                }
            }
        })
        .build(tauri::generate_context!());

    match build_result {
        Ok(app) => {
            app.run(|app_handle, event| {
                match event {
                    RunEvent::ExitRequested { .. } => {
                        backend::stop(app_handle);
                    }
                    RunEvent::Reopen { has_visible_windows, .. } => {
                        if !has_visible_windows {
                            if let Some(window) = app_handle.get_webview_window("main") {
                                let _ = window.show();
                                let _ = window.set_focus();
                            }
                        }
                    }
                    _ => {}
                }
            });
        }
        Err(err) => {
            eprintln!("[QwenPaw Desktop] Fatal startup error: {err}");
            std::process::exit(1);
        }
    }
}
