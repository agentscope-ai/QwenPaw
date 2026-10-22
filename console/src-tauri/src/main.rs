// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    if std::env::args_os().nth(1).as_deref() == Some(std::ffi::OsStr::new("--agent-host")) {
        if let Err(err) = app_lib::run_agent_host() {
            eprintln!("[agent-host] {err}");
            std::process::exit(1);
        }
        return;
    }
    app_lib::run();
}
