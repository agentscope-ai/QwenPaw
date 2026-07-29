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
use std::sync::{Condvar, Mutex};
use std::time::Duration;

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
    "find_window",
    "hello",
    "invoke_element",
    "launch_app",
    "list_apps",
    "list_windows",
    "observe_window",
    "press_key",
    "scroll",
    "set_focus",
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
static DESKTOP_FREED: Condvar = Condvar::new();

/// How long to wait for another session to give up the desktop.
///
/// Bounded rather than indefinite. An action can stall on an application that
/// stops answering, and an unbounded wait would turn one unresponsive window
/// into every session hanging with nothing to report. The budget covers the
/// worst path a single action can take -- a capture timing out, focus polling,
/// a close waiting on a save prompt -- with room to spare.
const DESKTOP_WAIT: Duration = Duration::from_secs(10);

/// A turn at the desktop, released when dropped.
struct DesktopTurn;

impl Drop for DesktopTurn {
    fn drop(&mut self) {
        // Runs even if the action panicked, so a failure cannot strand the
        // desktop as permanently taken.
        let mut held = DESKTOP_HELD
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        *held = false;
        DESKTOP_FREED.notify_one();
    }
}

/// Take the desktop for one action, or report that another session has it.
fn take_desktop() -> Result<DesktopTurn, (&'static str, String)> {
    let mut held = DESKTOP_HELD
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    // A poisoned lock is recovered rather than propagated: the flag is the whole
    // state, and refusing every later action because an unrelated request
    // panicked would turn one failure into an outage.
    while *held {
        let (next, timeout) = DESKTOP_FREED
            .wait_timeout(held, DESKTOP_WAIT)
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        held = next;
        if timeout.timed_out() && *held {
            return Err((
                "desktop_busy",
                "Another Computer Use session is using the desktop; observe the \
                 window again and retry."
                    .to_string(),
            ));
        }
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
    // One session at a time may disturb the desktop, and it holds that right
    // from the guard through to the end of the action. There is one keyboard,
    // one pointer and one foreground window, so two sessions interleaving here
    // would land a session's keystrokes in whatever the other one had just
    // focused. Observation is left out: it reads the screen without moving it.
    let _desktop = if changes_window_state(method) {
        let held = take_desktop()?;
        let after_approval = params
            .get("after_approval")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        // Checked under the turn, so the machine cannot become locked, or the
        // user cannot start typing, between the check and the action.
        enforce_input_guard(after_approval)?;
        Some(held)
    } else {
        None
    };
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
///
/// `set_focus` belongs here even though it reads like navigation. Raising a
/// window takes the keyboard away from whatever the person was typing into, and
/// on Windows getting past the foreground lock means synthesizing an Alt tap and
/// un-minimizing the target -- input injection and a visible change, on a
/// machine that may be locked or in someone's hands.
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
            | "set_focus"
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
            // Raising a window moves the keyboard focus, and on Windows the
            // foreground lock is escaped by synthesizing an Alt tap.
            "set_focus",
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
            "end_turn",
            // Starting an application changes what is on screen, but it
            // synthesizes no input and reads no pixels, and it already needs
            // its own approval. It is listed deliberately rather than left
            // unasserted, so the judgement is on the record.
            "launch_app",
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

    /// Taken by any test that touches the desktop turn.
    ///
    /// The turn is process-global, and the test harness runs tests on parallel
    /// threads, so two of them contending for it would make each other's timing
    /// assertions meaningless. Passing without this is luck, not isolation.
    static ONE_AT_A_TIME: Mutex<()> = Mutex::new(());

    #[test]
    fn a_second_session_waits_rather_than_acting_at_the_same_time() {
        let _serial = ONE_AT_A_TIME
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let first = take_desktop().expect("first turn");
        let (sender, receiver) = std::sync::mpsc::channel();
        let waiter = std::thread::spawn(move || {
            // Blocks until the first turn is dropped, which is the whole point:
            // two sessions must not be inside an action together.
            let turn = take_desktop();
            let _ = sender.send(turn.is_ok());
        });

        assert!(
            receiver
                .recv_timeout(std::time::Duration::from_millis(150))
                .is_err(),
            "the second session should still be waiting"
        );
        drop(first);
        assert_eq!(
            receiver.recv_timeout(std::time::Duration::from_secs(5)),
            Ok(true),
            "releasing the desktop should let the waiting session in"
        );
        waiter.join().expect("waiter finished");
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

        // If the release depended on the happy path, this would block forever.
        let (sender, receiver) = std::sync::mpsc::channel();
        std::thread::spawn(move || {
            let _ = sender.send(take_desktop().is_ok());
        });
        assert_eq!(
            receiver.recv_timeout(std::time::Duration::from_secs(5)),
            Ok(true),
            "a panicked action must not strand the desktop as taken"
        );
    }
}
