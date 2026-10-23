//! Tauri desktop entry point and plugin/command registration.

mod backend;
mod backend_download;
#[cfg(all(target_os = "macos", not(debug_assertions)))]
mod computer_use_helper;
mod computer_use_protocol;
mod computer_use_runtime;
mod external_link;
mod runtime_env;
mod tray;
mod updates;
#[cfg(windows)]
mod webview_recovery;

use tauri::{Manager, RunEvent, WebviewWindow, WindowEvent};

/// Opens the WebView DevTools. Gated by the hidden 8-click logo gesture in the
/// frontend so end users cannot open DevTools via the default context menu or
/// keyboard shortcuts in production builds.
#[tauri::command]
fn open_devtools(window: WebviewWindow) {
    window.open_devtools();
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
/// Build the desktop app, wire native plugins/commands, and attach to the shared runtime.
pub fn run() {
    let context = tauri::generate_context!();
    let registration = match updates::coordination::register_desktop(&context.config().identifier) {
        Ok(Some(registration)) => registration,
        Ok(None) => return,
        Err(error) => {
            eprintln!("[QwenPaw Desktop] Cannot register this window: {error}");
            std::process::exit(1);
        }
    };
    let build_result = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(
            tauri_plugin_updater::Builder::new()
                .default_version_comparator(updates::is_remote_update_newer)
                .build(),
        )
        .invoke_handler(tauri::generate_handler![
            open_devtools,
            backend_download::download_backend_file,
            backend::agent_host_state,
            backend::restart_backend,
            external_link::open_external_link,
            external_link::open_workspace_html,
            updates::coordination::confirm_desktop_update,
            updates::check_desktop_update,
            updates::install_desktop_update,
            updates::download_desktop_update,
            updates::install_downloaded_update,
            updates::check_cached_update,
            tray::minimize_to_tray,
            tray::quit_app,
            tray::stop_service,
            tray::set_tray_labels,
            tray::ack_close,
            tray::set_close_action,
            tray::get_close_action,
        ])
        .manage(registration)
        .manage(updates::coordination::Confirmation::default())
        .manage(backend::BackendState::default())
        .manage(computer_use_runtime::ComputerUseRuntimeState::default())
        .manage(tray::TrayState::default())
        .setup(|app| {
            updates::coordination::setup(app.handle())?;
            backend::setup(app)?;
            tray::setup(app)?;
            #[cfg(windows)]
            if let Some(window) = app.get_webview_window("main") {
                if let Err(err) = webview_recovery::install(&window) {
                    log::error!("[webview] failed to install browser-process recovery: {err}");
                }
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                tray::request_close(window.app_handle());
            }
        })
        .build(context);

    match build_result {
        Ok(app) => {
            app.run(|app_handle, event| match event {
                RunEvent::ExitRequested { api, code, .. } => {
                    #[cfg(windows)]
                    if code.is_none() && webview_recovery::is_active() {
                        api.prevent_exit();
                        return;
                    }
                    #[cfg(target_os = "macos")]
                    if code.is_none() && !tray::is_quitting(app_handle) {
                        api.prevent_exit();
                        tray::request_quit(app_handle);
                        return;
                    }
                    if !tray::shutdown_complete(app_handle) {
                        api.prevent_exit();
                        tray::exit_app(app_handle, code.unwrap_or(0));
                    }
                }
                // macOS emits this when the user clicks the Dock icon. Without
                // it, a window hidden via "minimize to tray" can only be
                // restored from the menu-bar icon, leaving a dead Dock icon.
                #[cfg(target_os = "macos")]
                RunEvent::Reopen { .. } => {
                    tray::show_main_window(app_handle);
                }
                _ => {}
            });
        }
        Err(err) => {
            eprintln!("[QwenPaw Desktop] Fatal startup error: {err}");
            std::process::exit(1);
        }
    }
}

/// Run the detached desktop supervisor without constructing a WebView.
pub fn run_agent_host() -> Result<(), String> {
    backend::daemon::run()
}
