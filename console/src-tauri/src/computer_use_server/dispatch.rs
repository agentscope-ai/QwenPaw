//! Routing one request to a platform action, and the guards it passes first.
//!
//! Every action arrives here, which is what makes this the right place for the
//! checks that must hold for all of them: the protocol version, the turn not
//! having been stopped, the window still resolving, the application being
//! approved, and the machine not being in a state where synthesizing input
//! would be unsafe. A platform leaf implements the OS action and nothing else,
//! so a guard cannot end up applied on one platform and forgotten on the other.

use serde_json::{json, Value};
use std::io::{Read, Write};

use super::app_identity::launch_app;
use super::approval::request_approval;
use super::state::ServerState;
use super::{
    click, close_window, desktop_locked, drag, invoke_element, list_apps, list_windows,
    observe_window, press_key, resolve_window, scroll, set_focus, set_intervention_bypass_once,
    set_value, type_text, PROTOCOL_VERSION,
};

pub(super) fn dispatch_request(
    connection: &mut (impl Read + Write),
    state: &mut ServerState,
    message: &Value,
) -> Result<Value, (&'static str, String)> {
    if message.get("protocol_version").and_then(Value::as_u64) != Some(PROTOCOL_VERSION) {
        return Err((
            "protocol_mismatch",
            "Unsupported protocol version.".to_string(),
        ));
    }
    let method = message
        .get("method")
        .and_then(Value::as_str)
        .ok_or(("invalid_request", "Request method is missing.".to_string()))?;
    let params = message
        .get("params")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    let meta = message
        .get("meta")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    let turn_id = meta
        .get("turn_id")
        .and_then(Value::as_str)
        .unwrap_or_default();

    if state.stopped_turn.as_deref() == Some(turn_id) && method != "close" {
        return Err((
            "turn_stopped",
            "Computer Use was stopped for this turn.".to_string(),
        ));
    }
    match method {
        "close" => return Ok(json!({})),
        "end_turn" => {
            state.snapshots.clear();
            state.accessibility.clear();
            return Ok(json!({}));
        }
        "stop_turn" => {
            state.snapshots.clear();
            state.accessibility.clear();
            state.stopped_turn = Some(turn_id.to_string());
            return Ok(json!({}));
        }
        "list_apps" => return Ok(json!({"apps": list_apps()})),
        "list_windows" => return Ok(json!({"windows": list_windows()})),
        _ => {}
    }

    let window = if method == "launch_app" {
        None
    } else {
        let value = params
            .get("window_id")
            .and_then(Value::as_str)
            .ok_or(("invalid_request", "window_id is required.".to_string()))?;
        Some(resolve_window(value)?)
    };
    if method == "find_window" {
        return Ok(json!({"window": window.expect("window exists").to_json()}));
    }
    if method == "launch_app" {
        return launch_app(connection, &params, &meta);
    }
    let window = window.expect("window exists");
    request_approval(connection, &window, &meta)?;
    // Actions that synthesize input or change window state must not run
    // against the secure lock screen. This list is the helper's own policy
    // about what is unsafe there, decided where the input is synthesized.
    if changes_window_state(method) && desktop_locked() {
        return Err((
            "desktop_locked",
            "The desktop is locked; ask the user to unlock it before continuing."
                .to_string(),
        ));
    }
    // The recency guard is exempted once right after the user resolves an
    // approval prompt in QwenPaw. The caller marks the request that follows an
    // approval; honouring that flag on its own -- rather than gating it behind
    // a second list of method names that has to stay in step with the caller's
    // -- means the two sides cannot drift out of agreement.
    let after_approval = params
        .get("after_approval")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    set_intervention_bypass_once(after_approval);
    let outcome = match method {
        "set_focus" => {
            set_focus(&window)?;
            Ok(json!({"window": window.to_json()}))
        }
        "observe_window" => observe_window(state, &window),
        "close_window" => {
            let result = close_window(&window)?;
            if result.get("closed").and_then(Value::as_bool) == Some(true) {
                // Observations of a closed window can never be acted on
                // again; drop them so a later action fails fast as stale
                // instead of pointing at a dead handle.
                let hwnd = window.hwnd;
                state
                    .snapshots
                    .retain(|_, snapshot| snapshot.window.hwnd != hwnd);
                state
                    .accessibility
                    .retain(|_, snapshot| snapshot.window_hwnd != hwnd);
            }
            Ok(result)
        }
        "click" => click(state, &window, &params),
        "scroll" => scroll(state, &window, &params),
        "drag" => drag(state, &window, &params),
        "press_key" => press_key(&window, &params),
        "type_text" => type_text(&window, &params),
        "invoke_element" => invoke_element(state, &window, &params),
        "set_value" => set_value(state, &window, &params),
        "perform_secondary_action" => Err((
            "unsupported_operation",
            format!("{method} is not available in this helper build."),
        )),
        _ => Err((
            "unsupported_operation",
            format!("Unsupported method: {method}"),
        )),
    };
    // An exemption the action never consumed must not outlive the request that
    // carried it, or the next action would silently skip the recency guard.
    set_intervention_bypass_once(false);
    outcome
}

/// Whether a method synthesizes input or otherwise changes window state.
///
/// Used to refuse those actions on the secure lock screen. It deliberately
/// governs nothing else, so it stays a local policy rather than a contract the
/// caller has to mirror.
fn changes_window_state(method: &str) -> bool {
    matches!(
        method,
        "click"
            | "scroll"
            | "drag"
            | "press_key"
            | "type_text"
            | "invoke_element"
            | "set_value"
            | "close_window"
    )
}
