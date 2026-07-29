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
    click, close_window, desktop_locked, drag, invoke_element, last_input_age_ms, list_apps,
    list_windows, observe_window, press_key, resolve_window, scroll, set_focus, set_value,
    type_text, PROTOCOL_VERSION,
};

/// How recently a person must have used the keyboard or mouse for an action to
/// be refused as racing them.
const USER_INTERVENTION_GRACE_MS: u32 = 750;

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

    match method {
        "end_turn" => {
            // The turn is over, so its screenshots and accessibility handles
            // can never be acted on again.
            state.snapshots.clear();
            state.accessibility.clear();
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
    // Everything that disturbs the machine passes the same guard, once, here.
    if changes_window_state(method) {
        let after_approval = params
            .get("after_approval")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        enforce_input_guard(after_approval)?;
    }
    match method {
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
    }
}

/// Refuse an action that would disturb a machine a person is using.
///
/// Two conditions, checked together because they answer the same question: the
/// desktop must not be locked, and the keyboard and mouse must have been idle
/// long enough that the action is not racing someone. `after_approval` marks
/// the request that follows an approval, whose own dismissing click would
/// otherwise read as intervention.
///
/// This runs once per request, from the one place every request passes. It used
/// to sit inside the platform leaves, repeated per action and per platform, and
/// the exemption had to travel there as connection-local state -- which Windows
/// then spent twice, resolving both ends of a drag through a shared helper, so
/// a drag right after an approval could not succeed. Deciding here needs no
/// state at all, and an exemption cannot outlive the request that carried it.
fn enforce_input_guard(after_approval: bool) -> Result<(), (&'static str, String)> {
    if desktop_locked() {
        return Err((
            "desktop_locked",
            "The desktop is locked; ask the user to unlock it before continuing.".to_string(),
        ));
    }
    if after_approval {
        return Ok(());
    }
    // An unreadable idle time is treated as idle: refusing every action because
    // the platform would not answer would strand the agent entirely.
    if last_input_age_ms().is_some_and(|age| age < USER_INTERVENTION_GRACE_MS) {
        return Err((
            "user_intervention",
            "Recent user input was detected; observe the window again before continuing."
                .to_string(),
        ));
    }
    Ok(())
}

/// Whether a method synthesizes input or otherwise changes window state.
///
/// This is the set the input guard applies to: the actions that reach out and
/// disturb the machine, as opposed to those that only look at it.
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

#[cfg(test)]
mod tests {
    use super::*;

    /// Spelled out rather than derived, so adding an action that reaches into
    /// the desktop cannot pass the guard by being forgotten: the new method has
    /// to be added here too, which is the moment to decide whether it belongs.
    #[test]
    fn every_action_that_disturbs_the_desktop_is_guarded() {
        for method in [
            "click",
            "scroll",
            "drag",
            "press_key",
            "type_text",
            "invoke_element",
            "set_value",
            "close_window",
        ] {
            assert!(changes_window_state(method), "{method} must be guarded");
        }
    }

    #[test]
    fn methods_that_only_look_are_not_guarded() {
        // Observing must keep working while someone is using the machine, and
        // must not be refused on a locked screen either.
        for method in [
            "observe_window",
            "find_window",
            "list_apps",
            "list_windows",
            "set_focus",
            "launch_app",
            "end_turn",
        ] {
            assert!(
                !changes_window_state(method),
                "{method} must not be treated as input"
            );
        }
    }

    #[test]
    fn an_approved_request_is_exempt_from_the_recency_check() {
        // The click that dismissed the approval prompt is recent user input by
        // definition, so the request it authorised has to be allowed through.
        // Nothing persists afterwards: the flag arrives with the request.
        if desktop_locked() {
            return;
        }
        assert!(enforce_input_guard(true).is_ok());
        assert!(enforce_input_guard(true).is_ok());
    }
}
