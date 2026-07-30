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
use super::state::{Observation, ServerState};
use super::{
    click, close_window, desktop_locked, drag, invoke_element, last_input_age_ms, list_apps,
    list_windows, observe_window, press_key, resolve_window, scroll, set_value, type_text,
    PROTOCOL_VERSION,
};

/// How recently a person must have used the keyboard or mouse for an action to
/// be refused as racing them.
const USER_INTERVENTION_GRACE_MS: u32 = 750;

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
    let meta = message
        .get("meta")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();

    match method {
        "end_turn" => {
            // The turn is over, so its screenshots and accessibility handles
            // can never be acted on again.
            state.observations.clear();
            return Ok(json!({}));
        }
        "list_apps" => return Ok(json!({"apps": list_apps()})),
        "list_windows" => return Ok(json!({"windows": list_windows()})),
        _ => {}
    }

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
            "Observation is no longer available; observe the window again.".to_string(),
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
    // One session at a time may disturb the desktop, and it holds that right
    // from the guard through to the end of the action. There is one keyboard,
    // one pointer and one foreground window, so two sessions interleaving here
    // would land a session's keystrokes in whatever the other one had just
    // focused. Observation is left out: it reads the screen without moving it.
    let _desktop = if changes_window_state(method) {
        let held = take_desktop()?;
        // Checked under the turn, so the machine cannot become locked, or the
        // user cannot start typing, between the check and the action.
        enforce_input_guard()?;
        Some(held)
    } else {
        None
    };
    if let Some(path) = launch_path {
        launch_at(&path)?;
        return Ok(json!({"launched": true, "app_id": window.app_id}));
    }
    match method {
        "observe_window" => observe_window(state, &window),
        "close_window" => {
            let result = close_window(&window)?;
            if result.get("closed").and_then(Value::as_bool) == Some(true) {
                // Observations of a closed window can never be acted on
                // again; drop them so a later action fails fast as stale
                // instead of pointing at a dead handle.
                state
                    .observations
                    .retain(|_, observation| observation.window.hwnd != window.hwnd);
            }
            Ok(result)
        }
        "click" => click(observation(state, observation_id)?, &params),
        "scroll" => scroll(observation(state, observation_id)?, &params),
        "drag" => drag(observation(state, observation_id)?, &params),
        "press_key" => press_key(observation(state, observation_id)?, &params),
        "type_text" => type_text(observation(state, observation_id)?, &params),
        "invoke_element" => invoke_element(observation(state, observation_id)?, &params),
        "set_value" => set_value(observation(state, observation_id)?, &params),
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

fn observation<'a>(
    state: &'a ServerState,
    id: Option<&str>,
) -> Result<&'a Observation, (&'static str, String)> {
    let id = id.ok_or(("invalid_request", "observation_id is required.".to_string()))?;
    state.observations.get(id).ok_or((
        "stale_observation",
        "Observation is no longer available; observe the window again.".to_string(),
    ))
}

/// Refuse an action that would disturb a machine a person is using.
///
/// Two conditions, checked together because they answer the same question: the
/// desktop must not be locked, and the keyboard and mouse must have been idle
/// long enough that the action is not racing someone.
///
/// There is deliberately no post-approval exemption. The click that answers an
/// approval prompt is itself recent input, so an action issued right on its
/// heels is refused here as `user_intervention` -- a retryable outcome the
/// caller recovers from by observing again and reissuing, by which point the
/// grace has passed. An exemption would have to distinguish that approving
/// click from a person genuinely taking over, which the OS idle timer cannot,
/// so it could only be a flag that also waved real input through. Refusing and
/// letting the caller retry keeps the guard honest and holds no state.
fn enforce_input_guard() -> Result<(), (&'static str, String)> {
    if desktop_locked() {
        return Err((
            "desktop_locked",
            "The desktop is locked; ask the user to unlock it before continuing.".to_string(),
        ));
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
            | "type_text"
            | "invoke_element"
            | "set_value"
            | "close_window"
            | "launch_app"
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
