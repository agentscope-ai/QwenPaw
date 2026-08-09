//! Asking the desktop host whether the agent may touch an application.
//!
//! This is the one place the helper talks back to the host mid-request: it
//! writes an approval request on the same connection and blocks reading the
//! reply, so the decision -- including a person taking their time over it, or
//! the host denying to unblock a stop -- is what ends the wait.

use serde_json::{json, Map, Value};
use std::io::{Read, Write};

use super::framing::{read_message, write_message};
use super::state::{next_id, WindowInfo};
use super::{is_forbidden, PROTOCOL_VERSION};

pub(super) fn request_approval(
    connection: &mut (impl Read + Write),
    window: &WindowInfo,
    meta: &Map<String, Value>,
) -> Result<(), (&'static str, String)> {
    if is_forbidden(window) {
        return Err((
            "app_forbidden",
            "Computer Use cannot control this application.".to_string(),
        ));
    }
    let request_id = next_id("approval");
    let mut evidence = Map::new();
    // Identifiers are path-backed on both platforms, under the prefix that
    // names the platform's unit of installation.
    if let Some(path) = window
        .app_id
        .strip_prefix("process:")
        .or_else(|| window.app_id.strip_prefix("app:"))
    {
        evidence.insert("path".to_string(), Value::String(path.to_string()));
    }
    let request = json!({
        "request_id": request_id,
        "method": "request_app_approval",
        "params": {
            "canonical_app_id": window.app_id,
            "display_name": window.display_name,
            "identity_evidence": evidence,
            "risk": "low",
            "warning": "",
        },
        "meta": meta,
        "protocol_version": PROTOCOL_VERSION,
    });
    write_message(connection, &request).map_err(|error| ("runtime_disconnected", error))?;
    let reply = read_message(connection).map_err(|error| ("runtime_disconnected", error))?;
    let allowed = reply
        .get("request_id")
        .and_then(Value::as_str)
        .is_some_and(|value| value == request_id)
        && reply
            .get("result")
            .and_then(Value::as_object)
            .and_then(|result| result.get("decision"))
            .and_then(Value::as_str)
            == Some("allow");
    if allowed {
        Ok(())
    } else {
        Err((
            "app_denied",
            "Application access was not approved.".to_string(),
        ))
    }
}
