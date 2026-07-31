//! The Computer Use helper: a process whose only job is to serve the automation
//! protocol.
//!
//! It exists as its own executable rather than as part of the desktop shell
//! because of what the work requires. UI Automation and the accessibility APIs
//! are synchronous round trips into other applications, so an unresponsive
//! target blocks the caller -- which must not be the process drawing the
//! interface. Being a separate process also makes it killable, and dropping it
//! is how a stop takes effect on an action already under way. It keeps its own
//! COM apartment, and it keeps input synthesis out of the address space that
//! renders the window.
//!
//! Everything of substance lives in `computer_use_server`. A process boundary's
//! entry point should be thin: name the executable, take the endpoint, hand over.
//! The capability secret arrives through the environment rather than argv, where
//! any other process on the machine could read it.

// The server is attached at file scope rather than from inside a module. A
// `#[path]` inside an inline module resolves through a directory named after
// that module, and since no such directory exists, Unix cannot walk `..` out of
// it -- only Windows folds those segments away without touching the filesystem.
#[cfg(any(windows, target_os = "macos"))]
#[path = "../computer_use_protocol.rs"]
mod computer_use_protocol;

#[cfg(any(windows, target_os = "macos"))]
#[path = "../computer_use_server/mod.rs"]
mod computer_use_server;

#[cfg(not(any(windows, target_os = "macos")))]
fn main() {
    eprintln!("qwenpaw-computer-use-helper is only supported on Windows and macOS");
    std::process::exit(2);
}

#[cfg(any(windows, target_os = "macos"))]
fn main() {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    if !args.first().is_some_and(|value| value == "serve") {
        eprintln!(
            "usage: qwenpaw-computer-use-helper serve --pipe <endpoint> \
             (capability via QWENPAW_CU_CAPABILITY)",
        );
        std::process::exit(2);
    }
    #[cfg(target_os = "macos")]
    if let Err(error) = run_macos_app(args) {
        eprintln!("Computer Use helper failed: {error}");
        std::process::exit(2);
    }
    #[cfg(windows)]
    if let Err(error) = computer_use_server::run(&args[1..]) {
        eprintln!("Computer Use helper failed: {error}");
        std::process::exit(2);
    }
}

/// Make the macOS helper a real AppKit application even though it has no
/// windows or Dock icon. TCC associates Screen Recording with this application
/// identity, and AppKit keeps a main run loop available for permission prompts.
#[cfg(target_os = "macos")]
fn run_macos_app(args: Vec<String>) -> Result<(), String> {
    use objc2::MainThreadMarker;
    use objc2_app_kit::NSApplication;

    let marker = MainThreadMarker::new()
        .ok_or_else(|| "Computer Use helper must start on the main thread".to_string())?;
    let app = NSApplication::sharedApplication(marker);
    app.finishLaunching();

    let server_args = args[1..].to_vec();
    std::thread::Builder::new()
        .name("computer-use-server".to_string())
        .spawn(move || {
            if let Err(error) = computer_use_server::run(&server_args) {
                eprintln!("Computer Use helper failed: {error}");
                std::process::exit(2);
            }
        })
        .map_err(|error| format!("failed to start Computer Use server: {error}"))?;

    app.run();
    Ok(())
}
