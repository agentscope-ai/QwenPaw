//! Process-scoped credentials for native requests to the bundled backend.

use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use rand::{rngs::OsRng, TryRngCore};
use serde::Deserialize;
use tauri::{ipc::CommandScope, Manager};

use super::BackendState;

pub(crate) const DESKTOP_SESSION_HEADER: &str = "x-desktop-session";

// Intentionally not Debug: a session contains a bearer credential.
#[derive(Clone)]
pub(crate) struct BackendSession {
    pub(crate) origin: String,
    pub(crate) token: String,
    pub(crate) generation: String,
}

#[derive(Debug, Deserialize)]
pub(crate) struct BackendScope {
    origin: String,
    generation: String,
}

pub(super) fn new_token() -> Result<String, String> {
    let mut bytes = [0u8; 32];
    OsRng
        .try_fill_bytes(&mut bytes)
        .map_err(|_| "failed to generate desktop session credentials".to_string())?;
    Ok(URL_SAFE_NO_PAD.encode(bytes))
}

fn capability(port: u16, generation: u64) -> String {
    let origin = format!("http://127.0.0.1:{port}");
    let scope = serde_json::json!({"origin": origin, "generation": generation.to_string()});
    serde_json::json!({
        "identifier": format!("backend-html-{generation}"),
        "local": false,
        "webviews": ["main"],
        "remote": {"urls": [format!("{origin}/*")]},
        "permissions": [
            {"identifier": "backend-html", "allow": [scope.clone()]},
            {"identifier": "backend-download", "allow": [scope]}
        ]
    })
    .to_string()
}

/// Add the frame-origin permission before making the backend visible to bootstrap.
/// Tauri retains older capabilities. Commands must also check their generation.
pub(super) fn ready(app: &tauri::AppHandle, generation: u64, port: u16) -> Result<(), String> {
    let state = app.state::<BackendState>();
    if !state.is_current(generation) {
        return Ok(());
    }
    app.add_capability(capability(port, generation).as_str())
        .map_err(|err| format!("failed to authorize backend console: {err}"))?;
    state.set_port_if_current(generation, port);
    Ok(())
}

impl BackendState {
    pub(super) fn session(&self) -> Result<BackendSession, String> {
        self.with_inner(|inner| {
            if inner.stopping
                || inner.error.is_some()
                || inner.terminated.as_ref().map_or(true, |rx| *rx.borrow())
            {
                return Err("backend session is not ready".into());
            }
            match (&inner.session_token, inner.port) {
                (Some(token), Some(port)) => Ok(BackendSession {
                    origin: format!("http://127.0.0.1:{port}"),
                    token: token.clone(),
                    generation: self
                        .generation
                        .load(std::sync::atomic::Ordering::SeqCst)
                        .to_string(),
                }),
                _ => Err("backend session is not ready".into()),
            }
        })
    }

    pub(crate) fn authorized_session(
        &self,
        webview: &tauri::Webview,
        scope: &CommandScope<BackendScope>,
    ) -> Result<BackendSession, String> {
        let session = self.session()?;
        // CommandScope is resolved by Tauri from the invoking frame's URL, not
        // the top-level window URL or caller-controlled JSON. An empty scope
        // must fail closed even if another capability later allows the command.
        if !scope.denies().is_empty()
            || !allows_session(
                &session,
                webview.label(),
                scope.allows().iter().map(|s| s.as_ref()),
            )
        {
            return Err("backend session is not available to this caller".into());
        }
        Ok(session)
    }
}

fn allows_session<'a>(
    session: &BackendSession,
    webview: &str,
    mut scopes: impl Iterator<Item = &'a BackendScope>,
) -> bool {
    webview == "main"
        && scopes
            .any(|scope| scope.origin == session.origin && scope.generation == session.generation)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn session() -> BackendSession {
        BackendSession {
            origin: "http://127.0.0.1:54377".into(),
            generation: "3".into(),
            token: "test-only".into(),
        }
    }

    #[test]
    fn session_scope_requires_current_generation_origin_and_main_webview() {
        let current = session();
        let allowed = BackendScope {
            origin: current.origin.clone(),
            generation: "3".into(),
        };
        let stale = BackendScope {
            origin: current.origin.clone(),
            generation: "1".into(),
        };
        let other_port = BackendScope {
            origin: "http://127.0.0.1:54378".into(),
            generation: "3".into(),
        };
        assert!(allows_session(&current, "main", [&allowed].into_iter()));
        assert!(!allows_session(&current, "main", [].into_iter()));
        assert!(!allows_session(&current, "main", [&stale].into_iter()));
        assert!(!allows_session(&current, "main", [&other_port].into_iter()));
        assert!(!allows_session(&current, "other", [&allowed].into_iter()));
        assert!(allows_session(
            &current,
            "main",
            [&stale, &allowed].into_iter()
        ));
    }

    #[test]
    fn session_is_unavailable_before_ready_during_stop_and_after_exit() {
        let state = BackendState::default();
        assert!(state.session().is_err());
        let (sender, receiver) = tokio::sync::watch::channel(false);
        state.next_generation();
        state.with_inner(|inner| {
            inner.port = Some(54377);
            inner.session_token = Some("test-only".into());
            inner.terminated = Some(receiver);
        });
        assert!(state.session().is_ok());
        state.with_inner(|inner| inner.stopping = true);
        assert!(state.session().is_err());
        state.with_inner(|inner| inner.stopping = false);
        sender.send_replace(true);
        assert!(state.session().is_err());
        state.clear_child_if_current(1);
        assert!(state.session().is_err());
        assert_eq!(state.port(), None);
    }

    #[test]
    fn fresh_tokens_are_32_random_bytes_encoded_without_padding() {
        let first = new_token().unwrap();
        let second = new_token().unwrap();
        assert_ne!(first, second);
        assert_eq!(first.len(), 43);
        assert_eq!(URL_SAFE_NO_PAD.decode(first).unwrap().len(), 32);
    }

    #[test]
    fn capability_does_not_grant_local_or_wildcard_loopback_access() {
        let value: serde_json::Value = serde_json::from_str(&capability(54377, 3)).unwrap();
        assert_eq!(value["local"], false);
        assert_eq!(value["webviews"], serde_json::json!(["main"]));
        assert_eq!(
            value["remote"]["urls"],
            serde_json::json!(["http://127.0.0.1:54377/*"])
        );
        assert_eq!(value["permissions"][0]["allow"][0]["generation"], "3");
        let defaults: serde_json::Value =
            serde_json::from_str(include_str!("../../capabilities/default.json")).unwrap();
        assert!(!defaults["permissions"]
            .as_array()
            .unwrap()
            .iter()
            .any(|permission| {
                permission == "backend-html" || permission == "backend-download"
            }));
    }

    #[test]
    fn tauri_frame_acl_rejects_foreign_opaque_and_stale_origins() {
        use std::collections::BTreeMap;
        use tauri::ipc::{Origin, RuntimeAuthority};
        use tauri::utils::acl::{manifest::Manifest, resolved::Resolved, APP_ACL_KEY};

        let permissions = [
            ("backend-html", "open_workspace_html"),
            ("backend-download", "download_backend_file"),
        ]
        .into_iter()
        .map(|(identifier, command)| {
            (
                identifier.into(),
                serde_json::from_value(serde_json::json!({
                    "identifier": identifier, "commands": {"allow": [command]}
                }))
                .unwrap(),
            )
        })
        .collect();
        let manifests = BTreeMap::from([(
            APP_ACL_KEY.into(),
            Manifest {
                permissions,
                ..Default::default()
            },
        )]);
        let capabilities = BTreeMap::from([
            (
                "old".into(),
                serde_json::from_str(&capability(54376, 1)).unwrap(),
            ),
            (
                "current".into(),
                serde_json::from_str(&capability(54377, 3)).unwrap(),
            ),
        ]);
        let resolved = Resolved::resolve(
            &manifests,
            capabilities,
            tauri::utils::platform::Target::current(),
        )
        .unwrap();
        let scopes = resolved.command_scope.clone();
        let authority = RuntimeAuthority::new(manifests, resolved);
        for command in ["open_workspace_html", "download_backend_file"] {
            let allowed = authority
                .resolve_access(
                    command,
                    "main",
                    "main",
                    &Origin::Remote {
                        url: "http://127.0.0.1:54377/console/#/chat".parse().unwrap(),
                    },
                )
                .unwrap();
            let matched: Vec<BackendScope> = allowed
                .iter()
                .flat_map(|entry| {
                    scopes[&entry.scope_id.unwrap()].allow.iter().map(|value| {
                        serde_json::from_value(serde_json::to_value(value).unwrap()).unwrap()
                    })
                })
                .collect();
            assert!(allows_session(&session(), "main", matched.iter()));
            for url in [
                "http://127.0.0.1:54378/console/",
                "http://localhost:54377/console/",
                "https://example.com/",
                "about:blank",
                "data:text/html,hello",
            ] {
                assert!(
                    authority
                        .resolve_access(
                            command,
                            "main",
                            "main",
                            &Origin::Remote {
                                url: url.parse().unwrap(),
                            }
                        )
                        .is_none(),
                    "allowed foreign frame {url}"
                );
            }
            assert!(authority
                .resolve_access(command, "main", "main", &Origin::Local)
                .is_none());
            assert!(authority
                .resolve_access(
                    command,
                    "other",
                    "other",
                    &Origin::Remote {
                        url: "http://127.0.0.1:54377/console/".parse().unwrap(),
                    }
                )
                .is_none());

            // An accumulated old capability can still match a frame URL. Its
            // actual resolved scope must not release this generation's token.
            let stale = authority
                .resolve_access(
                    command,
                    "main",
                    "main",
                    &Origin::Remote {
                        url: "http://127.0.0.1:54376/console/".parse().unwrap(),
                    },
                )
                .unwrap();
            let stale_scopes: Vec<BackendScope> = stale
                .iter()
                .flat_map(|entry| {
                    scopes[&entry.scope_id.unwrap()].allow.iter().map(|value| {
                        serde_json::from_value(serde_json::to_value(value).unwrap()).unwrap()
                    })
                })
                .collect();
            assert!(!allows_session(&session(), "main", stale_scopes.iter()));
        }
    }
}
