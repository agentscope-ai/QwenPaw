//! Coordinate/keyboard input synthesis, point verification, and foreground
//! activation.

use serde_json::{json, Map, Value};
use std::thread;
use std::time::Duration;
use windows::Win32::Foundation::{HWND, POINT};
use windows::Win32::System::StationsAndDesktops::{
    CloseDesktop, OpenInputDesktop, DESKTOP_CONTROL_FLAGS, DESKTOP_READOBJECTS,
};
use windows::Win32::System::SystemInformation::GetTickCount;
use windows::Win32::System::Threading::{AttachThreadInput, GetCurrentThreadId};
use windows::Win32::UI::Input::KeyboardAndMouse::{
    mouse_event, GetLastInputInfo, SendInput, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT,
    KEYEVENTF_KEYUP, KEYEVENTF_UNICODE, LASTINPUTINFO, MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP,
    MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP, MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP,
    MOUSEEVENTF_WHEEL, VIRTUAL_KEY,
};
use windows::Win32::UI::WindowsAndMessaging::{
    BringWindowToTop, GetForegroundWindow, GetWindowThreadProcessId, IsWindow, SetCursorPos,
    SetForegroundWindow, ShowWindow, WindowFromPoint, SW_RESTORE,
};

use super::super::state::{
    map_point, screenshot_target, Observation, ScreenshotTarget, WindowInfo,
};
use super::super::InputStep;
use super::uia::{element_point, element_point_by_id, focused_text_input};
#[cfg(test)]
use super::window::window_relation_matches;
use super::window::{get_visible_window_rect, matches_observed_surface, matches_target_window};

pub(crate) fn click(
    observation: &Observation,
    params: &Map<String, Value>,
) -> Result<Value, (&'static str, String)> {
    let point = if params.contains_key("element_id") {
        verify_element_point(observation, params)?
    } else {
        verify_point(observation, params)?
    };
    let button = params
        .get("button")
        .and_then(Value::as_str)
        .unwrap_or("left");
    let count = params
        .get("count")
        .and_then(Value::as_u64)
        .unwrap_or(1)
        .clamp(1, 3);
    let (down, up) = match button {
        "left" => (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
        "right" => (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
        "middle" => (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
        _ => return Err(("invalid_request", "Unsupported mouse button.".to_string())),
    };
    unsafe {
        SetCursorPos(point.x, point.y).map_err(|error| ("input_failed", error.to_string()))?;
        for _ in 0..count {
            mouse_event(down, 0, 0, 0, 0);
            mouse_event(up, 0, 0, 0, 0);
        }
    }
    Ok(json!({"applied": true}))
}

pub(crate) fn scroll(
    observation: &Observation,
    params: &Map<String, Value>,
) -> Result<Value, (&'static str, String)> {
    let point = verify_point(observation, params)?;
    let delta = params
        .get("delta_y")
        .and_then(Value::as_i64)
        .unwrap_or(0)
        .clamp(-1200, 1200);
    unsafe {
        SetCursorPos(point.x, point.y).map_err(|error| ("input_failed", error.to_string()))?;
        mouse_event(MOUSEEVENTF_WHEEL, 0, 0, delta as i32, 0);
    }
    Ok(json!({"applied": true}))
}

pub(crate) fn drag(
    observation: &Observation,
    params: &Map<String, Value>,
) -> Result<Value, (&'static str, String)> {
    let (start, end) = drag_points(observation, params)?;
    unsafe {
        SetCursorPos(start.x, start.y).map_err(|error| ("input_failed", error.to_string()))?;
        mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0);
        thread::sleep(Duration::from_millis(80));
        for step in 1..=12 {
            let x = start.x + (end.x - start.x) * step / 12;
            let y = start.y + (end.y - start.y) * step / 12;
            SetCursorPos(x, y).map_err(|error| ("input_failed", error.to_string()))?;
            thread::sleep(Duration::from_millis(16));
        }
        thread::sleep(Duration::from_millis(80));
        mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0);
    }
    Ok(json!({"applied": true}))
}

fn drag_points(
    observation: &Observation,
    params: &Map<String, Value>,
) -> Result<(POINT, POINT), (&'static str, String)> {
    let source_id = params.get("source_element_id").and_then(Value::as_str);
    let target_id = params.get("target_element_id").and_then(Value::as_str);
    match (source_id, target_id) {
        (Some(source_id), Some(target_id)) => {
            ensure_observed_geometry(observation)?;
            set_focus(&observation.window)?;
            ensure_observed_geometry(observation)?;
            Ok((
                validate_target_point(
                    observation.input_hwnd,
                    element_point_by_id(observation, source_id)?,
                )?,
                validate_target_point(
                    observation.input_hwnd,
                    element_point_by_id(observation, target_id)?,
                )?,
            ))
        }
        (None, None) => Ok((
            verify_point_with_prefix(observation, params, "start_")?,
            verify_point_with_prefix(observation, params, "end_")?,
        )),
        _ => Err((
            "invalid_request",
            "Both source_element_id and target_element_id are required for an element drag."
                .to_string(),
        )),
    }
}

pub(crate) fn type_text(
    observation: &Observation,
    params: &Map<String, Value>,
) -> Result<Value, (&'static str, String)> {
    let text = params
        .get("text")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .ok_or(("invalid_request", "text is required.".to_string()))?;
    set_focus(&observation.window)?;
    let focused = focused_text_input(observation)?;
    let mut inputs = Vec::with_capacity(text.encode_utf16().count() * 2);
    append_text_inputs(&mut inputs, text);
    send_inputs(&inputs)?;
    let mut observed = focused.observed(text);
    for _ in 0..3 {
        if observed {
            break;
        }
        thread::sleep(Duration::from_millis(25));
        observed = focused.observed(text);
    }
    Ok(json!({
        "applied": true,
        "effect": if observed { "observed" } else { "unverified" },
        "text_length": text.chars().count(),
    }))
}

pub(crate) fn press_key(
    observation: &Observation,
    params: &Map<String, Value>,
) -> Result<Value, (&'static str, String)> {
    let key = params
        .get("key")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or(("invalid_request", "key is required.".to_string()))?;
    let keys = parse_key_sequence(key)?;
    set_focus(&observation.window)?;
    let mut inputs = Vec::with_capacity(keys.len() * 2);
    append_key_inputs(&mut inputs, &keys);
    send_inputs(&inputs)?;
    Ok(json!({"applied": true, "key": key}))
}

pub(crate) fn input_sequence(
    observation: &Observation,
    steps: &[InputStep],
) -> Result<Value, (&'static str, String)> {
    let (inputs, ends) = build_sequence_inputs(steps)?;
    set_focus(&observation.window)?;
    let applied = send_inputs_count(&inputs);
    if applied == inputs.len() {
        return Ok(json!({"applied": true, "completed_steps": steps.len()}));
    }
    let completed = completed_steps(&ends, applied);
    Ok(json!({
        "completed_steps": completed,
        "error": {
            "code": "input_failed",
            "message": "Windows rejected part of the input sequence.",
            "step_index": completed,
            "outcome": "unknown",
        },
    }))
}

fn build_sequence_inputs(
    steps: &[InputStep],
) -> Result<(Vec<INPUT>, Vec<usize>), (&'static str, String)> {
    let mut inputs = Vec::new();
    let mut ends = Vec::with_capacity(steps.len());
    for step in steps {
        match step {
            InputStep::Type(text) => append_text_inputs(&mut inputs, text),
            InputStep::PressKey(key) => {
                let keys = parse_key_sequence(key)?;
                append_key_inputs(&mut inputs, &keys);
            }
        }
        ends.push(inputs.len());
    }
    Ok((inputs, ends))
}

fn append_text_inputs(inputs: &mut Vec<INPUT>, text: &str) {
    for unit in text.encode_utf16() {
        inputs.push(unicode_input(unit, KEYEVENTF_UNICODE));
        inputs.push(unicode_input(unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP));
    }
}

fn append_key_inputs(inputs: &mut Vec<INPUT>, keys: &[VIRTUAL_KEY]) {
    for value in keys {
        inputs.push(virtual_key_input(*value, Default::default()));
    }
    for value in keys.iter().rev() {
        inputs.push(virtual_key_input(*value, KEYEVENTF_KEYUP));
    }
}

fn parse_key_sequence(value: &str) -> Result<Vec<VIRTUAL_KEY>, (&'static str, String)> {
    let values = value
        .split('+')
        .map(str::trim)
        .filter(|part| !part.is_empty())
        .map(virtual_key)
        .collect::<Result<Vec<_>, _>>()?;
    if values.is_empty() || values.len() > 4 {
        return Err((
            "invalid_request",
            "key must contain one to four key names.".to_string(),
        ));
    }
    Ok(values)
}

fn virtual_key(value: &str) -> Result<VIRTUAL_KEY, (&'static str, String)> {
    let name = value.to_ascii_uppercase();
    let code = match name.as_str() {
        "CTRL" | "CONTROL" => 0x11,
        "ALT" => 0x12,
        "SHIFT" => 0x10,
        "WIN" | "SUPER" | "META" | "LWIN" => 0x5b,
        "RWIN" => 0x5c,
        "ENTER" | "RETURN" => 0x0d,
        "TAB" => 0x09,
        "ESC" | "ESCAPE" => 0x1b,
        "SPACE" => 0x20,
        "BACKSPACE" => 0x08,
        "DELETE" | "DEL" => 0x2e,
        "INSERT" | "INS" => 0x2d,
        "UP" => 0x26,
        "DOWN" => 0x28,
        "LEFT" => 0x25,
        "RIGHT" => 0x27,
        "HOME" => 0x24,
        "END" => 0x23,
        "PAGEUP" | "PGUP" => 0x21,
        "PAGEDOWN" | "PGDN" => 0x22,
        "CAPSLOCK" => 0x14,
        "NUMLOCK" => 0x90,
        "SCROLLLOCK" => 0x91,
        "PRINTSCREEN" | "PRTSC" => 0x2c,
        "PAUSE" | "BREAK" => 0x13,
        "APPS" | "MENU" | "CONTEXTMENU" => 0x5d,
        "MULTIPLY" => 0x6a,
        "ADD" => 0x6b,
        "SUBTRACT" => 0x6d,
        "DECIMAL" => 0x6e,
        "DIVIDE" => 0x6f,
        // Function keys F1-F24 map to VK 0x70-0x87.
        _ if is_function_key(&name) => function_key_code(&name),
        // Numeric keypad digits NUMPAD0-NUMPAD9 map to VK 0x60-0x69.
        _ if is_numpad_digit(&name) => 0x60 + (name.as_bytes()[6] - b'0') as u16,
        _ if name.len() == 1 && name.as_bytes()[0].is_ascii_alphanumeric() => {
            name.as_bytes()[0] as u16
        }
        _ => return Err(("invalid_request", format!("Unsupported key: {value}."))),
    };
    Ok(VIRTUAL_KEY(code))
}

fn is_function_key(name: &str) -> bool {
    function_key_number(name).is_some()
}

fn function_key_number(name: &str) -> Option<u16> {
    let digits = name.strip_prefix('F')?;
    if digits.is_empty() || !digits.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    let number: u16 = digits.parse().ok()?;
    (1..=24).contains(&number).then_some(number)
}

fn function_key_code(name: &str) -> u16 {
    // Safe because callers gate on `is_function_key`, which validates 1..=24.
    0x70 + function_key_number(name).unwrap_or(1) - 1
}

fn is_numpad_digit(name: &str) -> bool {
    name.len() == 7 && name.starts_with("NUMPAD") && name.as_bytes()[6].is_ascii_digit()
}

fn unicode_input(
    unit: u16,
    flags: windows::Win32::UI::Input::KeyboardAndMouse::KEYBD_EVENT_FLAGS,
) -> INPUT {
    INPUT {
        r#type: INPUT_KEYBOARD,
        Anonymous: INPUT_0 {
            ki: KEYBDINPUT {
                wVk: VIRTUAL_KEY(0),
                wScan: unit,
                dwFlags: flags,
                time: 0,
                dwExtraInfo: 0,
            },
        },
    }
}

fn virtual_key_input(
    key: VIRTUAL_KEY,
    flags: windows::Win32::UI::Input::KeyboardAndMouse::KEYBD_EVENT_FLAGS,
) -> INPUT {
    INPUT {
        r#type: INPUT_KEYBOARD,
        Anonymous: INPUT_0 {
            ki: KEYBDINPUT {
                wVk: key,
                wScan: 0,
                dwFlags: flags,
                time: 0,
                dwExtraInfo: 0,
            },
        },
    }
}

fn send_inputs(inputs: &[INPUT]) -> Result<(), (&'static str, String)> {
    if send_inputs_count(inputs) != inputs.len() {
        return Err((
            "input_failed",
            "Windows rejected keyboard input.".to_string(),
        ));
    }
    Ok(())
}

fn send_inputs_count(inputs: &[INPUT]) -> usize {
    unsafe { SendInput(inputs, std::mem::size_of::<INPUT>() as i32) as usize }
}

fn completed_steps(ends: &[usize], applied: usize) -> usize {
    ends.iter().take_while(|end| **end <= applied).count()
}

fn verify_point(
    observation: &Observation,
    params: &Map<String, Value>,
) -> Result<POINT, (&'static str, String)> {
    verify_point_with_prefix(observation, params, "")
}

fn verify_element_point(
    observation: &Observation,
    params: &Map<String, Value>,
) -> Result<POINT, (&'static str, String)> {
    ensure_observed_geometry(observation)?;
    set_focus(&observation.window)?;
    ensure_observed_geometry(observation)?;
    validate_target_point(observation.input_hwnd, element_point(observation, params)?)
}

fn verify_point_with_prefix(
    observation: &Observation,
    params: &Map<String, Value>,
    prefix: &str,
) -> Result<POINT, (&'static str, String)> {
    let screenshot = screenshot_target(observation, params)?;
    ensure_screenshot_geometry(screenshot)?;
    set_focus(&observation.window)?;
    ensure_screenshot_geometry(screenshot)?;
    let x = integer_param(params, &format!("{prefix}x"))?;
    let y = integer_param(params, &format!("{prefix}y"))?;
    let (x_offset, y_offset) = map_point(screenshot, i64::from(x), i64::from(y))?;
    let point = POINT {
        x: screenshot.bounds[0] + x_offset as i32,
        y: screenshot.bounds[1] + y_offset as i32,
    };
    validate_target_point(screenshot.hwnd, point)
}

fn ensure_observed_geometry(observation: &Observation) -> Result<(), (&'static str, String)> {
    let current = get_visible_window_rect(HWND(observation.window.hwnd as _))
        .map_err(|error| ("stale_window", error))?;
    let current_bounds = [
        current.left,
        current.top,
        current.right - current.left,
        current.bottom - current.top,
    ];
    if current_bounds != observation.window_bounds {
        return Err((
            "stale_observation",
            "Window geometry changed; observe it again.".to_string(),
        ));
    }
    Ok(())
}

fn ensure_screenshot_geometry(screenshot: &ScreenshotTarget) -> Result<(), (&'static str, String)> {
    let current = get_visible_window_rect(HWND(screenshot.hwnd as _))
        .map_err(|error| ("stale_window", error))?;
    let current_bounds = [
        current.left,
        current.top,
        current.right - current.left,
        current.bottom - current.top,
    ];
    if current_bounds != screenshot.bounds {
        return Err((
            "stale_observation",
            "Screenshot geometry changed; observe the window again.".to_string(),
        ));
    }
    Ok(())
}

fn validate_target_point(surface: isize, point: POINT) -> Result<POINT, (&'static str, String)> {
    let hit = unsafe { WindowFromPoint(point) };
    if !matches_observed_surface(HWND(surface as _), hit) {
        return Err((
            "target_not_at_point",
            "The observed surface is no longer at this point.".to_string(),
        ));
    }
    Ok(point)
}

pub(crate) fn set_focus(window: &WindowInfo) -> Result<(), (&'static str, String)> {
    let hwnd = HWND(window.hwnd as _);
    if !unsafe { IsWindow(Some(hwnd)).as_bool() } {
        return Err((
            "window_not_found",
            "Target window no longer exists.".to_string(),
        ));
    }
    if foreground_matches(hwnd) {
        return Ok(());
    }
    unsafe {
        let _ = ShowWindow(hwnd, SW_RESTORE);
    }
    // Foreground transitions are asynchronous and the foreground lock can
    // reject a single attempt, so retry the standard strategies briefly
    // before giving up. Modal dialogs and owned popups are handled by the
    // root check inside `try_set_foreground`.
    for attempt in 0..3 {
        if try_set_foreground(hwnd)
            || attach_input_and_set_foreground(hwnd)
            || alt_tap_and_set_foreground(hwnd)
        {
            return Ok(());
        }
        if attempt < 2 {
            thread::sleep(Duration::from_millis(80));
        }
    }
    Err((
        "focus_failed",
        "Could not activate the target window.".to_string(),
    ))
}

fn try_set_foreground(hwnd: HWND) -> bool {
    unsafe {
        let _ = SetForegroundWindow(hwnd);
        foreground_matches(hwnd)
    }
}

/// Accept activation when the target or one of its related surfaces currently
/// holds the foreground.
fn foreground_matches(hwnd: HWND) -> bool {
    matches_target_window(hwnd, unsafe { GetForegroundWindow() })
}

/// The foreground lock rejects background processes, so temporarily join
/// the foreground thread's input queue (the standard automation approach)
/// and always detach again afterwards.
fn attach_input_and_set_foreground(hwnd: HWND) -> bool {
    unsafe {
        let foreground = GetForegroundWindow();
        if foreground.0.is_null() || foreground == hwnd {
            return try_set_foreground(hwnd);
        }
        let foreground_thread = GetWindowThreadProcessId(foreground, None);
        let current_thread = GetCurrentThreadId();
        if foreground_thread == 0 || foreground_thread == current_thread {
            return false;
        }
        if !AttachThreadInput(current_thread, foreground_thread, true).as_bool() {
            return false;
        }
        let _ = BringWindowToTop(hwnd);
        let activated = try_set_foreground(hwnd);
        let _ = AttachThreadInput(current_thread, foreground_thread, false);
        activated
    }
}

/// Last resort: a synthesized ALT tap marks this process as the most
/// recent input sender, which the foreground-lock rules accept.
fn alt_tap_and_set_foreground(hwnd: HWND) -> bool {
    const VK_MENU: VIRTUAL_KEY = VIRTUAL_KEY(0x12);
    let inputs = [
        virtual_key_input(VK_MENU, Default::default()),
        virtual_key_input(VK_MENU, KEYEVENTF_KEYUP),
    ];
    if send_inputs(&inputs).is_err() {
        return false;
    }
    try_set_foreground(hwnd)
}

/// Milliseconds since the last keyboard or mouse event anywhere on the desktop.
///
/// `None` when the system will not report it. The decision about what age is
/// too recent, and the exemption that follows an approval, belong to the shared
/// input guard; this reports the measurement and nothing else.
pub(crate) fn last_input_age_ms() -> Option<u32> {
    let mut input = LASTINPUTINFO {
        cbSize: std::mem::size_of::<LASTINPUTINFO>() as u32,
        ..Default::default()
    };
    if !unsafe { GetLastInputInfo(&mut input) }.as_bool() {
        return None;
    }
    Some(unsafe { GetTickCount() }.wrapping_sub(input.dwTime))
}

/// Report whether the interactive workstation is currently locked.
///
/// When the session is locked the input desktop switches to the secure
/// Winlogon desktop, which a normal user-session process cannot open;
/// `OpenInputDesktop` then fails, which we treat as "locked". A successful
/// open (the ordinary Default desktop) means the session is usable.
pub(crate) fn desktop_locked() -> bool {
    unsafe {
        match OpenInputDesktop(DESKTOP_CONTROL_FLAGS(0), false, DESKTOP_READOBJECTS) {
            Ok(desktop) => {
                let _ = CloseDesktop(desktop);
                false
            }
            Err(_) => true,
        }
    }
}

fn integer_param(params: &Map<String, Value>, name: &str) -> Result<i32, (&'static str, String)> {
    params
        .get(name)
        .and_then(Value::as_i64)
        .and_then(|value| i32::try_from(value).ok())
        .ok_or(("invalid_request", format!("{name} is required.")))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hwnd(value: isize) -> HWND {
        HWND(value as *mut std::ffi::c_void)
    }

    #[test]
    fn function_and_keypad_keys_map_to_expected_codes() {
        assert_eq!(virtual_key("F1").unwrap(), VIRTUAL_KEY(0x70));
        assert_eq!(virtual_key("f12").unwrap(), VIRTUAL_KEY(0x7b));
        assert_eq!(virtual_key("F24").unwrap(), VIRTUAL_KEY(0x87));
        assert_eq!(virtual_key("NUMPAD0").unwrap(), VIRTUAL_KEY(0x60));
        assert_eq!(virtual_key("numpad9").unwrap(), VIRTUAL_KEY(0x69));
        assert_eq!(virtual_key("INSERT").unwrap(), VIRTUAL_KEY(0x2d));
        assert_eq!(virtual_key("WIN").unwrap(), VIRTUAL_KEY(0x5b));
    }

    #[test]
    fn common_named_and_alphanumeric_keys_still_map() {
        assert_eq!(virtual_key("CTRL").unwrap(), VIRTUAL_KEY(0x11));
        assert_eq!(virtual_key("enter").unwrap(), VIRTUAL_KEY(0x0d));
        assert_eq!(virtual_key("A").unwrap(), VIRTUAL_KEY(b'A' as u16));
        assert_eq!(virtual_key("7").unwrap(), VIRTUAL_KEY(b'7' as u16));
    }

    #[test]
    fn unknown_or_out_of_range_keys_are_rejected() {
        assert!(virtual_key("F25").is_err());
        assert!(virtual_key("F0").is_err());
        assert!(virtual_key("NUMPAD").is_err());
        assert!(virtual_key("HYPERKEY").is_err());
    }

    #[test]
    fn chords_parse_up_to_four_keys() {
        assert!(parse_key_sequence("CTRL+SHIFT+F5").is_ok());
        assert!(parse_key_sequence("A+B+C+D+E").is_err());
        assert!(parse_key_sequence("").is_err());
    }

    #[test]
    fn sequence_inputs_keep_step_boundaries() {
        let steps = vec![
            InputStep::Type("A".to_string()),
            InputStep::PressKey("TAB".to_string()),
            InputStep::Type("🙂".to_string()),
        ];

        let (inputs, ends) = build_sequence_inputs(&steps).unwrap();

        assert_eq!(ends, vec![2, 4, 8]);
        assert_eq!(inputs.len(), 8);
        assert_eq!(completed_steps(&ends, 3), 1);
        assert_eq!(completed_steps(&ends, 4), 2);
    }

    #[test]
    fn sequence_keys_are_validated_before_input_is_built() {
        let steps = vec![
            InputStep::Type("already valid".to_string()),
            InputStep::PressKey("NO_SUCH_KEY".to_string()),
        ];

        assert!(build_sequence_inputs(&steps).is_err());
    }

    #[test]
    fn input_target_relationships_are_scoped() {
        let owner = hwnd(1);
        let modal = hwnd(2);
        let sibling = hwnd(3);
        assert!(window_relation_matches(owner, owner, owner, owner));
        assert!(window_relation_matches(owner, modal, owner, owner));
        assert!(!window_relation_matches(modal, owner, owner, owner));
        assert!(!window_relation_matches(modal, sibling, owner, owner));
    }
}
