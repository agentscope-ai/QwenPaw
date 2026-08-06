//! UI Automation: element enumeration, invoke, and value-set.

use serde_json::{json, Value};
use std::collections::HashMap;
use windows::core::BSTR;
use windows::Win32::Foundation::{HWND, POINT};
use windows::Win32::System::Com::{CoCreateInstance, CLSCTX_INPROC_SERVER};
use windows::Win32::UI::Accessibility::{
    CUIAutomation, IUIAutomation, IUIAutomationElement, IUIAutomationInvokePattern,
    IUIAutomationSelectionItemPattern, IUIAutomationTextPattern, IUIAutomationValuePattern,
    TreeScope_Subtree, UIA_InvokePatternId, UIA_SelectionItemPatternId, UIA_TextPatternId,
    UIA_ValuePatternId,
};
use windows::Win32::UI::WindowsAndMessaging::IsWindow;

use super::super::state::{
    accessibility_revision, element_line, truncate_document_text, Observation, PendingAction,
    WindowInfo, DOC_TEXT_MAX,
};

/// Map a UI Automation control-type identifier to a human-readable role
/// name so callers can recognise actionable controls (for example an
/// editable field or a button) without memorising the numeric ids.
fn control_type_name(control_type: i32) -> &'static str {
    match control_type {
        50000 => "Button",
        50001 => "Calendar",
        50002 => "CheckBox",
        50003 => "ComboBox",
        50004 => "Edit",
        50005 => "Hyperlink",
        50006 => "Image",
        50007 => "ListItem",
        50008 => "List",
        50009 => "Menu",
        50010 => "MenuBar",
        50011 => "MenuItem",
        50012 => "ProgressBar",
        50013 => "RadioButton",
        50014 => "ScrollBar",
        50015 => "Slider",
        50016 => "Spinner",
        50017 => "StatusBar",
        50018 => "Tab",
        50019 => "TabItem",
        50020 => "Text",
        50021 => "ToolBar",
        50022 => "ToolTip",
        50023 => "Tree",
        50024 => "TreeItem",
        50025 => "Custom",
        50026 => "Group",
        50027 => "Thumb",
        50028 => "DataGrid",
        50029 => "DataItem",
        50030 => "Document",
        50031 => "SplitButton",
        50032 => "Window",
        50033 => "Pane",
        50034 => "Header",
        50035 => "HeaderItem",
        50036 => "Table",
        50037 => "TitleBar",
        50038 => "Separator",
        50039 => "SemanticZoom",
        50040 => "AppBar",
        _ => "Unknown",
    }
}

/// Read the text of an editable or document element.
///
/// Rich documents expose TextPattern, while plain edit controls (Notepad's
/// editor among them) only expose ValuePattern, so both are attempted.
/// Returns `None` when the element carries no readable text.
fn element_text(element: &IUIAutomationElement) -> Option<String> {
    let limit = DOC_TEXT_MAX as i32;
    if let Ok(pattern) =
        unsafe { element.GetCurrentPatternAs::<IUIAutomationTextPattern>(UIA_TextPatternId) }
    {
        if let Ok(range) = unsafe { pattern.DocumentRange() } {
            if let Ok(text) = unsafe { range.GetText(limit) } {
                let text = text.to_string();
                if !text.is_empty() {
                    return Some(text);
                }
            }
        }
    }
    let pattern =
        unsafe { element.GetCurrentPatternAs::<IUIAutomationValuePattern>(UIA_ValuePatternId) }
            .ok()?;
    let value = unsafe { pattern.CurrentValue() }.ok()?.to_string();
    if value.is_empty() {
        return None;
    }
    Some(truncate_document_text(value))
}

pub(crate) fn collect_accessibility(
    window: &WindowInfo,
) -> Result<(Value, HashMap<String, IUIAutomationElement>), String> {
    let automation: IUIAutomation = unsafe {
        CoCreateInstance(&CUIAutomation, None, CLSCTX_INPROC_SERVER)
            .map_err(|error| format!("UI Automation is unavailable: {error}"))?
    };
    let root = unsafe { automation.ElementFromHandle(HWND(window.hwnd as _)) }
        .map_err(|error| format!("UI Automation could not inspect the window: {error}"))?;
    let condition = unsafe { automation.CreateTrueCondition() }
        .map_err(|error| format!("UI Automation condition failed: {error}"))?;
    let items = unsafe { root.FindAll(TreeScope_Subtree, &condition) }
        .map_err(|error| format!("UI Automation enumeration failed: {error}"))?;
    let count = unsafe { items.Length() }
        .map_err(|error| format!("UI Automation item count failed: {error}"))?
        .clamp(0, 300);
    let mut elements = HashMap::new();
    let mut descriptions = Vec::new();
    // The focused element is picked out of this window's own subtree, so it
    // can never describe another application's UI.
    let mut focused: Option<(String, IUIAutomationElement)> = None;
    for index in 0..count {
        let element = match unsafe { items.GetElement(index) } {
            Ok(element) => element,
            Err(_) => continue,
        };
        let name = unsafe { element.CurrentName() }
            .map(|value| value.to_string())
            .unwrap_or_default();
        let automation_id = unsafe { element.CurrentAutomationId() }
            .map(|value| value.to_string())
            .unwrap_or_default();
        if name.is_empty() && automation_id.is_empty() {
            continue;
        }
        let bounds = unsafe { element.CurrentBoundingRectangle() }.unwrap_or_default();
        let selected = unsafe {
            element
                .GetCurrentPatternAs::<IUIAutomationSelectionItemPattern>(
                    UIA_SelectionItemPatternId,
                )
                .and_then(|pattern| pattern.CurrentIsSelected())
                .map(|value| value.as_bool())
                .unwrap_or(false)
        };
        let element_id = format!("uia-{index}");
        let control_type = unsafe { element.CurrentControlType() }
            .map(|value| value.0)
            .unwrap_or_default();
        if focused.is_none()
            && unsafe { element.CurrentHasKeyboardFocus() }
                .map(|value| value.as_bool())
                .unwrap_or(false)
        {
            focused = Some((
                element_line(&element_id, control_type_name(control_type), &name),
                element.clone(),
            ));
        }
        descriptions.push(json!({
            "id": element_id,
            "name": name,
            "automation_id": automation_id,
            "control_type": control_type,
            "control_type_name": control_type_name(control_type),
            "enabled": unsafe { element.CurrentIsEnabled() }.map(|value| value.as_bool()).unwrap_or(false),
            "offscreen": unsafe { element.CurrentIsOffscreen() }.map(|value| value.as_bool()).unwrap_or(true),
            "selected": selected,
            "bounds": [bounds.left, bounds.top, bounds.right, bounds.bottom],
        }));
        elements.insert(element_id, element);
    }
    // Summary fields are best-effort: a missing one is simply omitted so an
    // observation never fails because a control withheld its text.
    let mut accessibility = serde_json::Map::new();
    accessibility.insert("available".to_string(), json!(true));
    if let Some((line, element)) = focused.as_ref() {
        accessibility.insert("focused_element".to_string(), json!(line));
        if let Some(text) = element_text(element) {
            accessibility.insert("document_text".to_string(), json!(text));
        }
    }
    accessibility.insert("elements".to_string(), json!(descriptions));
    Ok((Value::Object(accessibility), elements))
}

pub(crate) fn element_point(
    observation: &Observation,
    params: &serde_json::Map<String, Value>,
) -> Result<POINT, (&'static str, String)> {
    let element_id = params
        .get("element_id")
        .and_then(Value::as_str)
        .ok_or(("invalid_request", "element_id is required.".to_string()))?;
    element_point_by_id(observation, element_id)
}

pub(crate) fn element_point_by_id(
    observation: &Observation,
    element_id: &str,
) -> Result<POINT, (&'static str, String)> {
    let element = observation.elements.get(element_id).ok_or((
        "element_not_found",
        "Element is not available in this observation.".to_string(),
    ))?;
    if !unsafe { element.CurrentIsEnabled() }
        .map(|value| value.as_bool())
        .unwrap_or(false)
    {
        return Err((
            "element_unavailable",
            "Element is no longer enabled.".to_string(),
        ));
    }
    if unsafe { element.CurrentIsOffscreen() }
        .map(|value| value.as_bool())
        .unwrap_or(true)
    {
        return Err((
            "element_unavailable",
            "Element is offscreen; scroll it into view before acting on it.".to_string(),
        ));
    }
    let mut point = POINT::default();
    if unsafe { element.GetClickablePoint(&mut point) }
        .map(|available| available.as_bool())
        .unwrap_or(false)
    {
        return Ok(point);
    }
    let bounds = unsafe { element.CurrentBoundingRectangle() }.map_err(|_| {
        (
            "element_unavailable",
            "The element does not expose a clickable point.".to_string(),
        )
    })?;
    if bounds.right <= bounds.left || bounds.bottom <= bounds.top {
        return Err((
            "element_unavailable",
            "The element has no clickable area.".to_string(),
        ));
    }
    Ok(POINT {
        x: bounds.left + (bounds.right - bounds.left) / 2,
        y: bounds.top + (bounds.bottom - bounds.top) / 2,
    })
}

pub(crate) fn invoke_element(
    observation: &Observation,
    params: &serde_json::Map<String, Value>,
    pending: Option<&PendingAction>,
) -> Result<Value, (&'static str, String)> {
    if pending.is_some() {
        return Err((
            "pending_action_unavailable",
            "This platform cannot complete the pending native edit.".to_string(),
        ));
    }
    let element = accessibility_element(observation, params)?;
    let pattern: IUIAutomationInvokePattern =
        unsafe { element.GetCurrentPatternAs(UIA_InvokePatternId) }.map_err(|_| {
            (
                "unsupported_operation",
                "The element does not support Invoke.".to_string(),
            )
        })?;
    unsafe { pattern.Invoke() }.map_err(|error| {
        (
            "action_failed",
            format!("UI Automation invoke failed: {error}"),
        )
    })?;
    Ok(json!({"applied": true}))
}

pub(crate) fn set_value(
    observation: &Observation,
    params: &serde_json::Map<String, Value>,
) -> Result<(Value, Option<PendingAction>), (&'static str, String)> {
    let value = params
        .get("value")
        .and_then(Value::as_str)
        .ok_or(("invalid_request", "value is required.".to_string()))?;
    let element = accessibility_element(observation, params)?;
    let pattern: IUIAutomationValuePattern =
        unsafe { element.GetCurrentPatternAs(UIA_ValuePatternId) }.map_err(|_| {
            (
                "unsupported_operation",
                "The element does not support Value.".to_string(),
            )
        })?;
    unsafe { pattern.SetValue(&BSTR::from(value)) }.map_err(|error| {
        (
            "action_failed",
            format!("UI Automation value update failed: {error}"),
        )
    })?;
    let actual = unsafe { pattern.CurrentValue() }.map_err(|error| {
        (
            "postcondition_failed",
            format!("UI Automation could not read the updated value: {error}"),
        )
    })?;
    let actual = actual.to_string();
    if actual != value {
        return Err((
            "postcondition_failed",
            "The control did not retain the requested value.".to_string(),
        ));
    }
    Ok((json!({"applied": true, "value": actual}), None))
}

fn accessibility_element<'a>(
    observation: &'a Observation,
    params: &serde_json::Map<String, Value>,
) -> Result<&'a IUIAutomationElement, (&'static str, String)> {
    let element_id = params
        .get("element_id")
        .and_then(Value::as_str)
        .ok_or(("invalid_request", "element_id is required.".to_string()))?;
    if !unsafe { IsWindow(Some(HWND(observation.window.hwnd as _))).as_bool() } {
        return Err((
            "window_not_found",
            "Target window no longer exists.".to_string(),
        ));
    }
    let element = observation.elements.get(element_id).ok_or((
        "element_not_found",
        "Element is not available in this observation.".to_string(),
    ))?;
    if !element_belongs_to_window(element, observation.window.hwnd) {
        return Err((
            "stale_observation",
            "The element is no longer part of the observed window; observe it again.".to_string(),
        ));
    }
    if !unsafe { element.CurrentIsEnabled() }
        .map(|value| value.as_bool())
        .unwrap_or(false)
    {
        return Err((
            "element_unavailable",
            "Element is no longer enabled.".to_string(),
        ));
    }
    Ok(element)
}

/// Re-read the normalized UIA surface before a semantic mutation.
pub(crate) fn validate_observation(
    observation: &Observation,
) -> Result<(), (&'static str, String)> {
    let expected = observation.accessibility_revision.ok_or((
        "stale_observation",
        "The observation had no accessibility revision; observe the window again.".to_string(),
    ))?;
    let (current, _) = collect_accessibility(&observation.window).map_err(|error| {
        (
            "stale_observation",
            format!("The observed accessibility surface is unavailable: {error}"),
        )
    })?;
    if accessibility_revision(&current) != Some(expected) {
        return Err((
            "stale_observation",
            "The observed window changed; observe it again before acting.".to_string(),
        ));
    }
    Ok(())
}

fn element_belongs_to_window(element: &IUIAutomationElement, hwnd: isize) -> bool {
    let automation: IUIAutomation =
        match unsafe { CoCreateInstance(&CUIAutomation, None, CLSCTX_INPROC_SERVER) } {
            Ok(automation) => automation,
            Err(_) => return false,
        };
    let walker = match unsafe { automation.RawViewWalker() } {
        Ok(walker) => walker,
        Err(_) => return false,
    };
    let expected = HWND(hwnd as _);
    let mut current = element.clone();
    for _ in 0..64 {
        if unsafe { current.CurrentNativeWindowHandle() }.ok() == Some(expected) {
            return true;
        }
        let Ok(parent) = (unsafe { walker.GetParentElement(&current) }) else {
            return false;
        };
        current = parent;
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn control_type_names_cover_the_actionable_roles() {
        assert_eq!(control_type_name(50000), "Button");
        assert_eq!(control_type_name(50004), "Edit");
        assert_eq!(control_type_name(50007), "ListItem");
        assert_eq!(control_type_name(1), "Unknown");
    }
}
