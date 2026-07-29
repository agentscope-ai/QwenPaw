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
    environment.extend(plugin_catalog());
    environment.extend(crate::computer_use_runtime::backend_environment(app));
    environment
}

/// The plugin catalog host this build belongs to, if it was given one.
///
/// Fixed at compile time rather than read from the environment when the backend
/// starts: an application launched from the desktop inherits no shell, so a
/// value exported in a terminal would never reach it. This is how the updater
/// endpoints are already handled -- a repository variable, resolved during the
/// build -- and it matters for the same reason: a fork publishes plugins to its
/// own bucket, and the catalog its builds read has to be the one it published.
///
/// Contributes nothing when unset, leaving the backend's own default in place,
/// so an ordinary build is unaffected.
fn plugin_catalog() -> Vec<(String, String)> {
    match option_env!("QWENPAW_PLUGIN_CDN").map(str::trim) {
        Some(host) if !host.is_empty() => {
            vec![("QWENPAW_PLUGIN_CDN".to_string(), host.to_string())]
        }
        _ => Vec::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_unset_catalog_host_contributes_nothing() {
        // The default build must not override the backend's own default, and
        // must not pass an empty value that would read as "no host".
        for (key, value) in plugin_catalog() {
            assert_eq!(key, "QWENPAW_PLUGIN_CDN");
            assert!(!value.is_empty(), "an empty host must not be passed on");
        }
    }
}
