//! Environment the desktop shell hands to the Python backend sidecar.
//!
//! The backend is spawned by [`backend::command`], which owns the generic
//! launch: the executable, the working directory, `PATH`, the bundled runtimes.
//! Some desktop features also need the backend to know a value only the shell
//! has at runtime -- a loopback port, a one-shot token, a resource path. This
//! module is where those features contribute that, so the launch code stays
//! ignorant of any one feature.
//!
//! The dependency points one way: a feature module exposes a plain
//! `Vec<(String, String)>`, and [`collect`] gathers them. The launch path
//! depends on this aggregator, never on a feature module directly, so adding
//! the next contributor is a line here rather than an edit to `command.rs`.

/// Gather every feature's backend environment into one set of variables.
///
/// Ordering follows the extend calls; a later contributor that repeats a key
/// would win, so keep the keys disjoint (they are today).
pub(crate) fn collect(app: &tauri::AppHandle) -> Vec<(String, String)> {
    let mut environment = Vec::new();
    environment.extend(crate::computer_use_runtime::backend_environment(app));
    environment
}
