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
use std::sync::Mutex;

use super::app_identity::{launch_at, resolve_launch_target};
use super::approval::request_approval;
#[cfg(target_os = "macos")]
use super::platform_macos::element_is_transient_menu_item;
use super::state::{
    accessibility_revision, Observation, PendingAction, ServerState, WindowInfo,
    INPUT_GUARD_GRACE_MS,
};
use super::{
    click, close_window, desktop_locked, drag, ensure_permissions, input_sequence, invoke_element,
    last_input_age_ms, list_apps, list_windows, observe_window, press_key, resolve_window, scroll,
    set_value, type_text, validate_observation, InputStep, PROTOCOL_VERSION,
};
#[cfg(target_os = "macos")]
use super::{element_requires_frontmost, target_is_frontmost};

const MAX_SEQUENCE_STEPS: usize = 20;
const MAX_SEQUENCE_TEXT_CHARS: usize = 512;

/// How recently a person must have used the keyboard or mouse for an action to
/// be refused as racing them.
/// Every method this helper serves.
///
/// Load-bearing rather than documentation: a request naming anything outside
/// this list is refused before dispatch, so an arm added to the match below
/// without a line here is unreachable. That makes the list the one place the
/// vocabulary is stated, and the one place a cross-language contract test has
/// to read -- an array literal has a single shape, where a match has as many as
/// there are ways to write one. A test that parsed the control flow reported a
/// method as unhandled the first time two arms were grouped, which is how a
/// green suite teaches people to disbelieve it.
const SERVED_METHODS: &[&str] = &[
    "click",
    "close_window",
    "drag",
    "end_turn",
    "hello",
    "invoke_element",
    "launch_app",
    "list_apps",
    "list_windows",
    "observe_window",
    "press_key",
    "scroll",
    "sequence",
    "set_value",
    "type_text",
];

/// Held while one session disturbs the desktop.
///
/// Each connection is served on its own thread, which is right for observation
/// and for one session waiting on an approval while another works. Input is
/// different: the keyboard, the pointer and the foreground window are one
/// shared resource, and every input path here is "focus the window, then
/// inject". Two of those interleaving means one session's keystrokes arrive in
/// the window the other just brought forward -- silently, and with whatever
/// text or shortcut was being sent.
///
/// A single session cannot race itself: a connection is served one request at a
/// time, and the caller holds its own lock across the round trip. This exists
/// only for the case those cannot see, which is two sessions at once.
///
/// Serialising is not a compromise here but the only correct answer: there is
/// one system cursor and one keyboard to synthesize into. A platform offering a
/// cursor per task could schedule them in parallel instead; these APIs do not.
static DESKTOP_HELD: Mutex<bool> = Mutex::new(false);

/// A turn at the desktop, released when dropped.
#[derive(Debug)]
struct DesktopTurn;

impl Drop for DesktopTurn {
    fn drop(&mut self) {
        // Runs even if the action panicked, so a failure cannot strand the
        // desktop as permanently taken.
        *DESKTOP_HELD
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner()) = false;
    }
}

/// Take the desktop for one action, or refuse at once if another session has it.
///
/// Deliberately does not wait. Waiting here would mean holding a request the
/// caller may already have abandoned: a stop closes the connection, and a thread
/// parked on a lock is not reading that connection, so it would wake later and
/// inject input the user had already asked to stop. The helper is the one
/// process with no notion of a stop, so it must never hold work that a stop
/// needs to reach. Refusing immediately leaves the waiting to the caller, where
/// a stop already takes effect.
///
/// `desktop_busy` is raised before anything is touched, so unlike a timeout it
/// carries no possibility of a half-performed action, and retrying it is safe.
fn take_desktop() -> Result<DesktopTurn, (&'static str, String)> {
    // A poisoned lock is recovered rather than propagated: the flag is the whole
    // state, and refusing every later action because an unrelated request
    // panicked would turn one failure into an outage.
    let mut held = DESKTOP_HELD
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    if *held {
        return Err((
            "desktop_busy",
            "Another Computer Use session is using the desktop; observe the \
             window again and retry."
                .to_string(),
        ));
    }
    *held = true;
    Ok(DesktopTurn)
}

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
    if !SERVED_METHODS.contains(&method) {
        return Err((
            "unsupported_operation",
            format!("{method:?} is not a Computer Use protocol method."),
        ));
    }
    let params = message
        .get("params")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    let sequence_steps = if method == "sequence" {
        Some(parse_input_steps(&params)?)
    } else {
        None
    };
    let meta = message
        .get("meta")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();

    match method {
        "end_turn" => {
            // The turn is over, so its screenshots and accessibility handles
            // can never be acted on again.
            state.clear_turn();
            return Ok(json!({}));
        }
        "list_apps" => return Ok(json!({"apps": list_apps()})),
        "list_windows" => {
            let app = params
                .get("app")
                .and_then(Value::as_str)
                .map(str::trim)
                .filter(|value| !value.is_empty());
            return Ok(json!({"windows": list_windows(app)}));
        }
        _ => {}
    }

    enforce_pending_action(state, method)?;

    // A launch names an application rather than a window. Observation creates
    // a context from a listed window. Every other action resolves the target
    // from its observation, keeping native handles out of the model contract.
    let (target, launch_path, observation_id) = if method == "launch_app" {
        let (target, path) = resolve_launch_target(&params)?;
        (target, Some(path), None)
    } else if method == "observe_window" {
        let value = params
            .get("window_id")
            .and_then(Value::as_str)
            .ok_or(("invalid_request", "window_id is required.".to_string()))?;
        (resolve_window(value)?, None, None)
    } else {
        let id = params
            .get("observation_id")
            .and_then(Value::as_str)
            .filter(|id| !id.is_empty())
            .ok_or((
                "invalid_request",
                "observation_id is required; observe the window again first.".to_string(),
            ))?;
        let observed = state.observations.get(id).ok_or((
            "stale_observation",
            "Observation is stale or already consumed; observe the window again and use its new observation_id."
                .to_string(),
        ))?;
        let current = resolve_window(&observed.window.hwnd.to_string())?;
        if current.app_id != observed.window.app_id {
            return Err((
                "stale_observation",
                "The observed window no longer belongs to the same application.".to_string(),
            ));
        }
        (current, None, Some(id))
    };
    let window = target;
    request_approval(connection, &window, &meta)?;
    ensure_permissions(method)?;
    // Mutations are serialized across agent sessions. Human input is a
    // separate concern: this lock cannot prevent it, so only operations that
    // actually require foreground input apply the recent-input guard below.
    let mut needs_user_idle = requires_user_idle(method, &window);
    #[cfg(target_os = "macos")]
    if method == "invoke_element" {
        needs_user_idle |=
            element_requires_frontmost(observation(state, observation_id)?, &params)?;
    }
    let _desktop = if changes_window_state(method) {
        let held = take_desktop()?;
        if needs_user_idle {
            enforce_input_guard(state)?;
        }
        Some(held)
    } else {
        None
    };
    if needs_user_idle {
        state.ensure_interaction_session()?;
    }
    // Approval may wait for user input, so freshness must be checked only
    // after approval and the desktop guard, immediately before the action.
    if requires_stable_observation(method) {
        validate_observation(observation(state, observation_id)?)?;
    }
    if let Some(path) = launch_path {
        launch_at(&path)?;
        state.note_global_action();
        return Ok(json!({
            "launched": true,
            "app_id": window.app_id,
            "requires_observe": true,
        }));
    }
    let previous_revision = observation_id
        .and_then(|id| state.observations.get(id))
        .and_then(|observation| observation.accessibility_revision);
    #[cfg(target_os = "macos")]
    let transient_text_candidate = requests_transient_text(method, &params)
        && element_is_transient_menu_item(observation(state, observation_id)?, &params)?;
    let mut pending_action: Option<PendingAction> = None;
    let mut completed_pending_action = false;
    let mut result = match method {
        "observe_window" => {
            state.settle_before_observe(window.hwnd);
            observe_window(state, &window)
        }
        "close_window" => close_window(&window),
        "click" => click(observation(state, observation_id)?, &params),
        "scroll" => scroll(observation(state, observation_id)?, &params),
        "drag" => drag(observation(state, observation_id)?, &params),
        "press_key" => press_key(observation(state, observation_id)?, &params),
        "sequence" => {
            let result = input_sequence(
                observation(state, observation_id)?,
                sequence_steps.as_deref().unwrap_or_default(),
            );
            if result
                .as_ref()
                .err()
                .is_some_and(|error| error.0 == "user_intervention")
            {
                state.invalidate_observations();
            }
            result
        }
        "type_text" => {
            #[cfg(target_os = "macos")]
            {
                let transient_text_ready = take_transient_text_ready(state, observation_id)?;
                type_text(
                    observation(state, observation_id)?,
                    &params,
                    transient_text_ready,
                )
            }
            #[cfg(windows)]
            {
                type_text(observation(state, observation_id)?, &params)
            }
        }
        "invoke_element" => {
            let pending = state.pending_action();
            let result = invoke_element(observation(state, observation_id)?, &params, pending);
            completed_pending_action = result.is_ok() && pending.is_some();
            result
        }
        "set_value" => {
            let (result, pending) = set_value(observation(state, observation_id)?, &params)?;
            pending_action = pending;
            Ok(result)
        }
        "perform_secondary_action" => Err((
            "unsupported_operation",
            format!("{method} is not available in this helper build."),
        )),
        _ => Err((
            "unsupported_operation",
            format!("Unsupported method: {method}"),
        )),
    }?;
    if method == "observe_window" {
        if let Some(pending) = state
            .pending_action()
            .filter(|pending| pending.hwnd == window.hwnd)
        {
            attach_pending_action(&mut result, pending);
        }
    }
    if !changes_window_state(method) {
        return Ok(result);
    }
    state.note_action(&window);
    if completed_pending_action {
        state.clear_pending_action();
    }
    if let Some(pending) = pending_action {
        state.set_pending_action(pending);
    }
    // Keep the safety boundary -- the input observation has already been
    // consumed -- but make the normal action cycle atomic for the caller. A
    // successful mutation is followed by a settled observation of the same
    // window, so the response itself carries the only identifier valid for
    // the next action. If the action removed or replaced that window, retain
    // the dispatch receipt and direct the caller to discover the new target.
    let refreshed = if method == "sequence" {
        refresh_after_sequence(state, &window)?
    } else {
        refresh_after_action(state, &window)
    };
    let has_refreshed_observation = refreshed.is_some();
    let changed = accessibility_changed(previous_revision, refreshed.as_ref());
    #[cfg(target_os = "macos")]
    let transient_text_ready = transient_text_candidate
        && changed == Some(true)
        && mark_transient_text_ready(state, refreshed.as_ref());
    let mut response = action_receipt(result, refreshed, changed);
    #[cfg(target_os = "macos")]
    if transient_text_ready {
        if let Some(object) = response.as_object_mut() {
            object.insert("transient_text_ready".to_string(), json!(true));
            object.insert("next_action".to_string(), json!("type"));
        }
    }
    if let Some(pending) = state.pending_action().filter(|pending| {
        should_attach_pending_action(has_refreshed_observation, pending.hwnd, window.hwnd)
    }) {
        attach_pending_action(&mut response, pending);
    }
    Ok(response)
}

#[cfg(target_os = "macos")]
fn take_transient_text_ready(
    state: &mut ServerState,
    observation_id: Option<&str>,
) -> Result<bool, (&'static str, String)> {
    let observation = observation_mut(state, observation_id)?;
    Ok(std::mem::take(&mut observation.transient_text_ready))
}

#[cfg(target_os = "macos")]
fn mark_transient_text_ready(state: &mut ServerState, refreshed: Option<&Value>) -> bool {
    let Some(observation_id) = refreshed
        .and_then(|value| value.get("observation_id"))
        .and_then(Value::as_str)
    else {
        return false;
    };
    let Some(observation) = state.observations.get_mut(observation_id) else {
        return false;
    };
    observation.transient_text_ready = true;
    true
}

#[cfg(target_os = "macos")]
fn requests_transient_text(method: &str, params: &serde_json::Map<String, Value>) -> bool {
    method == "invoke_element"
        && params.get("expects_text_input").and_then(Value::as_bool) == Some(true)
}

/// Observe the action's target without turning an already-dispatched action
/// into a failure when the application replaced or closed that window.
fn refresh_after_action(state: &mut ServerState, previous: &WindowInfo) -> Option<Value> {
    let current = resolve_window(&previous.hwnd.to_string()).ok()?;
    if current.app_id != previous.app_id {
        return None;
    }
    state.settle_before_observe(current.hwnd);
    observe_window(state, &current).ok()
}

fn refresh_after_sequence(
    state: &mut ServerState,
    previous: &WindowInfo,
) -> Result<Option<Value>, (&'static str, String)> {
    let Ok(current) = resolve_window(&previous.hwnd.to_string()) else {
        return Ok(None);
    };
    if current.app_id != previous.app_id {
        return Ok(None);
    }
    state.settle_before_observe(current.hwnd);
    enforce_input_guard(state)?;
    Ok(observe_window(state, &current).ok())
}

fn parse_input_steps(
    params: &serde_json::Map<String, Value>,
) -> Result<Vec<InputStep>, (&'static str, String)> {
    let steps = params
        .get("steps")
        .and_then(Value::as_array)
        .filter(|steps| !steps.is_empty() && steps.len() <= MAX_SEQUENCE_STEPS)
        .ok_or((
            "invalid_request",
            "steps must contain 1 to 20 input steps.".to_string(),
        ))?;
    let mut parsed = Vec::with_capacity(steps.len());
    let mut text_chars = 0;
    for (index, step) in steps.iter().enumerate() {
        let step = step.as_object().ok_or((
            "invalid_request",
            format!("steps[{index}] must be an object."),
        ))?;
        let action = step.get("action").and_then(Value::as_str).unwrap_or("");
        let (field, value) = match action {
            "type" => ("text", step.get("text").and_then(Value::as_str)),
            "press_key" => ("key", step.get("key").and_then(Value::as_str)),
            _ => {
                return Err((
                    "invalid_request",
                    format!("steps[{index}] must use type or press_key."),
                ))
            }
        };
        let value = value
            .filter(|value| !value.is_empty() && (action == "type" || !value.trim().is_empty()))
            .ok_or((
                "invalid_request",
                format!("steps[{index}] requires non-empty {field}."),
            ))?;
        if step.len() != 2 {
            return Err((
                "invalid_request",
                format!("steps[{index}] accepts only action and {field}."),
            ));
        }
        if action == "type" {
            text_chars += value.chars().count();
            if text_chars > MAX_SEQUENCE_TEXT_CHARS {
                return Err((
                    "invalid_request",
                    "Sequence text is limited to 512 characters.".to_string(),
                ));
            }
            parsed.push(InputStep::Type(value.to_string()));
        } else {
            parsed.push(InputStep::PressKey(value.to_string()));
        }
    }
    Ok(parsed)
}

/// Keep an incomplete native edit from being crossed with another mutation.
///
/// Observation remains available so the caller can locate the fresh element.
/// Only the semantic completion action may mutate the desktop until the native
/// adapter confirms that it targeted the same element and value.
fn enforce_pending_action(state: &ServerState, method: &str) -> Result<(), (&'static str, String)> {
    if state.pending_action().is_some()
        && changes_window_state(method)
        && method != "invoke_element"
    {
        return Err((
            "pending_action",
            "The previous edit still requires semantic completion. Observe its window and use the invoke action on the matching element before starting another desktop-changing action."
                .to_string(),
        ));
    }
    Ok(())
}

fn attach_pending_action(result: &mut Value, pending: &PendingAction) {
    if let Some(object) = result.as_object_mut() {
        object.insert("pending_action".to_string(), pending.to_json());
        object.insert("next_action".to_string(), json!("invoke"));
    }
}

fn should_attach_pending_action(
    has_refreshed_observation: bool,
    pending_hwnd: isize,
    window_hwnd: isize,
) -> bool {
    has_refreshed_observation && pending_hwnd == window_hwnd
}

/// Combine the dispatch result with the post-action observation when the
/// original window remains available. The old observation is never restored:
/// only the new identifier in this response can authorize the next action.
fn accessibility_changed(previous: Option<[u8; 32]>, refreshed: Option<&Value>) -> Option<bool> {
    let current = refreshed?
        .get("accessibility")
        .and_then(accessibility_revision)?;
    Some(previous? != current)
}

fn action_receipt(
    mut result: Value,
    refreshed: Option<Value>,
    accessibility_changed: Option<bool>,
) -> Value {
    let Some(mut observation) = refreshed else {
        if let Some(object) = result.as_object_mut() {
            if object.remove("applied").is_some() {
                object.insert("dispatched".to_string(), json!(true));
            }
            object.insert("requires_observe".to_string(), json!(true));
            object.insert("next_action".to_string(), json!("list_windows"));
        }
        return result;
    };

    let Some(action) = result.as_object_mut() else {
        return observation;
    };
    if action.remove("applied").is_some() {
        action.insert("dispatched".to_string(), json!(true));
    }
    // Native actions used to point to an explicit observe call. The fresh
    // observation above has already completed that step; a pending semantic
    // completion, if any, is attached by the caller afterwards.
    action.remove("next_action");
    if let Some(response) = observation.as_object_mut() {
        response.extend(std::mem::take(action));
        if let Some(changed) = accessibility_changed {
            response.insert("accessibility_changed".to_string(), json!(changed));
        }
    }
    observation
}

fn observation<'a>(
    state: &'a ServerState,
    id: Option<&str>,
) -> Result<&'a Observation, (&'static str, String)> {
    let id = id.ok_or(("invalid_request", "observation_id is required.".to_string()))?;
    state.observations.get(id).ok_or((
        "stale_observation",
        "Observation is stale or already consumed; observe the window again and use its new observation_id."
            .to_string(),
    ))
}

#[cfg(target_os = "macos")]
fn observation_mut<'a>(
    state: &'a mut ServerState,
    id: Option<&str>,
) -> Result<&'a mut Observation, (&'static str, String)> {
    let id = id.ok_or(("invalid_request", "observation_id is required.".to_string()))?;
    state.observations.get_mut(id).ok_or((
        "stale_observation",
        "Observation is stale or already consumed; observe the window again and use its new observation_id."
            .to_string(),
    ))
}

/// Refuse an action that would disturb a machine a person is using.
///
/// Two conditions, checked together because they answer the same question: the
/// desktop must not be locked, and the keyboard and mouse must have been idle
/// long enough that the action is not racing someone.
///
/// There is deliberately no post-approval exemption. The host lets a newly
/// approved request settle before replying, but the guard remains authoritative
/// here: any input still inside the grace window is refused rather than waved
/// through by client-held state.
fn enforce_input_guard(state: &mut ServerState) -> Result<(), (&'static str, String)> {
    enforce_input_guard_with_measurements(state, desktop_locked(), last_input_age_ms())
}

fn enforce_input_guard_with_measurements(
    state: &mut ServerState,
    is_locked: bool,
    last_input_age: Option<u32>,
) -> Result<(), (&'static str, String)> {
    if is_locked {
        return Err((
            "desktop_locked",
            "The desktop is locked; ask the user to unlock it before continuing.".to_string(),
        ));
    }
    // An unreadable idle time is treated as idle: refusing every action because
    // the platform would not answer would strand the agent entirely.
    if last_input_age.is_some_and(|age| age < INPUT_GUARD_GRACE_MS) {
        // Human input makes every point-in-time observation on this
        // connection unsafe. Drop them before reporting the soft refusal so
        // recovery must create a fresh observation rather than replaying an
        // action whose outcome is unknown.
        state.invalidate_observations();
        return Err((
            "user_intervention",
            "Recent user input was detected; observe again before continuing.".to_string(),
        ));
    }
    Ok(())
}

/// Whether a method disturbs the desktop rather than only looking at it.
///
/// This is the set that takes a turn at the desktop and meets the input guard.
/// The question is not "does it synthesize input" but "does it change what the
/// machine does next". Launching and input both take focus away from whatever
/// the person was using, so both are guarded.
///
/// `launch_app` belongs here because starting an application brings
/// it to the front, and on macOS `open` activates one that is already running,
/// so a launch during another session's action moves the focus its keystrokes
/// were bound for.
fn changes_window_state(method: &str) -> bool {
    matches!(
        method,
        "click"
            | "scroll"
            | "drag"
            | "press_key"
            | "sequence"
            | "type_text"
            | "invoke_element"
            | "set_value"
            | "close_window"
            | "launch_app"
    )
}

/// Semantic AX/UIA mutations can run without pointer input, but only while the
/// exact accessibility surface the model observed is still current.
fn requires_stable_observation(method: &str) -> bool {
    matches!(method, "invoke_element" | "set_value" | "close_window")
}

/// Whether this platform must take foreground input for the method.
///
/// macOS accessibility actions can address a specific element without moving
/// the pointer or keyboard focus, so unrelated user activity does not block
/// `invoke_element` or `set_value`. Windows keeps the conservative active-
/// desktop guard for every mutation; this is an internal safety boundary, not
/// a product-facing platform promise.
fn requires_user_idle(method: &str, window: &WindowInfo) -> bool {
    #[cfg(windows)]
    {
        let _ = window;
        changes_window_state(method)
    }
    #[cfg(target_os = "macos")]
    {
        requires_user_idle_on_mac(method, target_is_frontmost(window))
    }
}

#[cfg(target_os = "macos")]
fn requires_user_idle_on_mac(method: &str, target_is_frontmost: bool) -> bool {
    matches!(
        method,
        "click" | "scroll" | "drag" | "press_key" | "sequence" | "type_text" | "launch_app"
    ) || (matches!(method, "invoke_element" | "set_value" | "close_window") && target_is_frontmost)
}

#[cfg(test)]
mod tests {
    use super::super::state::WindowInfo;
    use super::*;

    fn observation(hwnd: isize) -> Observation {
        Observation {
            window: WindowInfo {
                hwnd,
                #[cfg(target_os = "macos")]
                owner_pid: 1,
                app_id: "app:test".to_string(),
                display_name: "Test".to_string(),
                title: String::new(),
                class_name: String::new(),
            },
            bounds: [0, 0, 100, 100],
            display_width: 100,
            display_height: 100,
            accessibility_revision: None,
            #[cfg(target_os = "macos")]
            transient_text_ready: false,
            elements: Default::default(),
        }
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn transient_text_capability_is_observation_bound_and_one_shot() {
        let mut state = ServerState::default();
        let mut observed = observation(1);
        observed.transient_text_ready = true;
        state.observations.insert("observed".to_string(), observed);
        state
            .observations
            .insert("other".to_string(), observation(1));

        assert!(!take_transient_text_ready(&mut state, Some("other")).unwrap());
        assert!(take_transient_text_ready(&mut state, Some("observed")).unwrap());
        assert!(!take_transient_text_ready(&mut state, Some("observed")).unwrap());
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn only_explicit_text_edit_invocation_requests_transient_input() {
        let ordinary = json!({"element_id": "ax-1"});
        let text_edit = json!({
            "element_id": "ax-1",
            "expects_text_input": true,
        });

        assert!(!requests_transient_text(
            "invoke_element",
            ordinary.as_object().unwrap(),
        ));
        assert!(!requests_transient_text(
            "click",
            text_edit.as_object().unwrap(),
        ));
        assert!(requests_transient_text(
            "invoke_element",
            text_edit.as_object().unwrap(),
        ));
    }

    #[test]
    fn input_sequence_contract_is_bounded_and_keyboard_only() {
        let value = json!({
            "steps": [
                {"action": "type", "text": "INV-001"},
                {"action": "press_key", "key": "TAB"},
            ]
        });
        let steps = parse_input_steps(value.as_object().unwrap()).unwrap();

        assert_eq!(
            steps,
            vec![
                InputStep::Type("INV-001".to_string()),
                InputStep::PressKey("TAB".to_string()),
            ]
        );

        for invalid in [
            json!({"steps": []}),
            json!({"steps": [{"action": "click", "x": 1, "y": 1}]}),
            json!({"steps": [{"action": "type", "text": "x", "extra": true}]}),
            json!({"steps": [{"action": "type", "text": "x".repeat(513)}]}),
        ] {
            assert!(parse_input_steps(invalid.as_object().unwrap()).is_err());
        }
    }

    #[test]
    fn an_action_without_a_refresh_requires_window_discovery() {
        let result = action_receipt(json!({"applied": true}), None, None);

        assert_eq!(result.get("dispatched"), Some(&json!(true)));
        assert_eq!(result.get("requires_observe"), Some(&json!(true)));
        assert_eq!(result.get("next_action"), Some(&json!("list_windows")));
    }

    #[test]
    fn refreshed_actions_report_accessibility_changes() {
        let before = accessibility_revision(&json!({
            "available": true,
            "elements": ["before"],
        }));
        let refreshed = json!({
            "accessibility": {
                "available": true,
                "elements": ["after"],
            },
        });

        assert_eq!(accessibility_changed(before, Some(&refreshed)), Some(true));
        assert_eq!(
            accessibility_changed(
                accessibility_revision(&refreshed["accessibility"]),
                Some(&refreshed),
            ),
            Some(false),
        );
    }

    #[test]
    fn unavailable_accessibility_has_no_change_claim() {
        let before = accessibility_revision(&json!({
            "available": true,
            "elements": ["before"],
        }));
        let refreshed = json!({
            "accessibility": {
                "available": false,
                "elements": [],
            },
        });

        assert_eq!(accessibility_changed(before, Some(&refreshed)), None);
    }

    #[test]
    fn pending_action_requires_a_refreshed_observation_of_its_window() {
        assert!(!should_attach_pending_action(false, 7, 7));
        assert!(!should_attach_pending_action(true, 7, 8));
        assert!(should_attach_pending_action(true, 7, 7));
    }

    #[test]
    fn user_intervention_invalidates_every_observation() {
        let mut state = ServerState::default();
        state
            .observations
            .insert("observation-1".to_string(), observation(1));
        state
            .observations
            .insert("observation-2".to_string(), observation(2));

        let error = enforce_input_guard_with_measurements(&mut state, false, Some(0))
            .expect_err("recent input must be refused");

        assert_eq!(error.0, "user_intervention");
        assert!(state.observations.is_empty());
    }

    #[test]
    fn an_idle_desktop_preserves_observations() {
        let mut state = ServerState::default();
        state
            .observations
            .insert("observation-1".to_string(), observation(1));

        enforce_input_guard_with_measurements(&mut state, false, Some(INPUT_GUARD_GRACE_MS))
            .expect("input at the grace boundary is idle");

        assert_eq!(state.observations.len(), 1);
    }

    #[test]
    fn user_intervention_refuses_only_the_current_action() {
        let mut state = ServerState::default();
        enforce_input_guard_with_measurements(&mut state, false, Some(0))
            .expect_err("recent input must refuse the action");

        enforce_input_guard_with_measurements(&mut state, false, Some(INPUT_GUARD_GRACE_MS))
            .expect("a later action may proceed after a fresh observation");
    }

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
            "sequence",
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
        for method in ["observe_window", "list_apps", "list_windows", "end_turn"] {
            assert!(
                !changes_window_state(method),
                "{method} must not be treated as input"
            );
        }
    }

    #[test]
    fn starting_an_application_counts_as_disturbing_the_desktop() {
        // This assertion used to read the other way, arguing that a launch
        // synthesizes no input. That is true and beside the point: it brings an
        // application to the front, and on macOS `open` activates one already
        // running, so it can take the focus another session's keystrokes were
        // aimed at -- and it can do it to a person who is mid-sentence.
        assert!(changes_window_state("launch_app"));
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn semantic_actions_are_guarded_only_when_the_target_is_frontmost() {
        for method in ["invoke_element", "set_value", "close_window"] {
            assert!(changes_window_state(method));
            assert!(
                !requires_user_idle_on_mac(method, false),
                "{method} should remain addressable while the user works elsewhere"
            );
            assert!(
                requires_user_idle_on_mac(method, true),
                "{method} must not race a user in the target app"
            );
        }
        for method in [
            "click",
            "drag",
            "type_text",
            "press_key",
            "sequence",
            "launch_app",
        ] {
            assert!(
                requires_user_idle_on_mac(method, false),
                "{method} must guard its foreground input"
            );
        }
    }

    /// Taken by any test that touches the desktop turn.
    ///
    /// The turn is process-global, and the test harness runs tests on parallel
    /// threads, so two of them contending for it would make each other's timing
    /// assertions meaningless. Passing without this is luck, not isolation.
    static ONE_AT_A_TIME: Mutex<()> = Mutex::new(());

    #[test]
    fn a_second_session_is_refused_rather_than_queued() {
        let _serial = ONE_AT_A_TIME
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let first = take_desktop().expect("first turn");

        let (code, _message) = take_desktop().expect_err("the second must be refused");
        assert_eq!(code, "desktop_busy");

        drop(first);
        assert!(
            take_desktop().is_ok(),
            "the desktop should be available once the first turn ends"
        );
    }

    #[test]
    fn being_refused_does_not_park_the_thread() {
        // The refusal has to be immediate, not a wait that gives up. A thread
        // parked here is not reading its connection, so a stop could not reach
        // it, and it would wake up later to inject input the user had already
        // asked to stop -- the helper knows nothing of stops, so it must not
        // hold work that a stop needs to cancel.
        let _serial = ONE_AT_A_TIME
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let _first = take_desktop().expect("first turn");

        let started = std::time::Instant::now();
        assert!(take_desktop().is_err());
        assert!(
            started.elapsed() < std::time::Duration::from_millis(100),
            "refusal took {:?}, which means it waited",
            started.elapsed()
        );
    }

    #[test]
    fn the_desktop_is_released_even_if_an_action_panics() {
        let _serial = ONE_AT_A_TIME
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let panicked = std::thread::spawn(|| {
            let _turn = take_desktop().expect("turn");
            panic!("an action failed");
        })
        .join();
        assert!(panicked.is_err(), "the thread should have panicked");

        // If the release depended on the happy path, the desktop would stay
        // taken and every later action would be refused.
        assert!(
            take_desktop().is_ok(),
            "a panicked action must not strand the desktop as taken"
        );
    }
}
