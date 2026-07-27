//! UI Automation: element enumeration, invoke, and value-set.

use serde_json::{json, Value};
use std::collections::HashMap;
use windows::core::BSTR;
use windows::Win32::Foundation::HWND;
use windows::Win32::System::Com::{CoCreateInstance, CLSCTX_INPROC_SERVER};
use windows::Win32::UI::Accessibility::{
    CUIAutomation, IUIAutomation, IUIAutomationElement, IUIAutomationInvokePattern,
    IUIAutomationTextPattern, IUIAutomationValuePattern, TreeScope_Subtree,
    UIA_InvokePatternId, UIA_TextPatternId, UIA_ValuePatternId,
};
use windows::Win32::UI::WindowsAndMessaging::IsWindow;

use super::{next_id, reject_recent_user_intervention, ServerState, WindowInfo};

/// Upper bound on the document text handed back with an observation. A
/// large document would otherwise dominate the model's context, and the
/// leading portion is what identifies the current state.
const DOC_TEXT_MAX: i32 = 4000;

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

/// Render one element the same way the tool adapter renders the listing, so
/// a summary line and a listing line are directly comparable.
fn element_line(element_id: &str, control_type_name: &str, name: &str) -> String {
    format!("{element_id} {control_type_name} \"{name}\"")
}

/// Read the text of an editable or document element.
///
/// Rich documents expose TextPattern, while plain edit controls (Notepad's
/// editor among them) only expose ValuePattern, so both are attempted.
/// Returns `None` when the element carries no readable text.
fn element_text(element: &IUIAutomationElement) -> Option<String> {
    if let Ok(pattern) =
        unsafe { element.GetCurrentPatternAs::<IUIAutomationTextPattern>(UIA_TextPatternId) }
    {
        if let Ok(range) = unsafe { pattern.DocumentRange() } {
            if let Ok(text) = unsafe { range.GetText(DOC_TEXT_MAX) } {
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

/// Bound the text by character count, flagging that more remains.
fn truncate_document_text(text: String) -> String {
    let limit = DOC_TEXT_MAX as usize;
    if text.chars().count() <= limit {
        return text;
    }
    let mut bounded: String = text.chars().take(limit).collect();
    bounded.push_str("… (truncated)");
    bounded
}

/// Read the selected text of an element, when it exposes a selection.
fn element_selected_text(element: &IUIAutomationElement) -> Option<String> {
    let pattern =
        unsafe { element.GetCurrentPatternAs::<IUIAutomationTextPattern>(UIA_TextPatternId) }
            .ok()?;
    let ranges = unsafe { pattern.GetSelection() }.ok()?;
    let range = unsafe { ranges.GetElement(0) }.ok()?;
    let text = unsafe { range.GetText(DOC_TEXT_MAX) }.ok()?.to_string();
    if text.is_empty() {
        return None;
    }
    Some(truncate_document_text(text))
}

pub(super) fn collect_accessibility(
    window: &WindowInfo,
) -> Result<(String, Value, HashMap<String, IUIAutomationElement>), String> {
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
    let revision = next_id("accessibility");
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
        let element_id = format!("uia-{index}");
        let control_type =
            unsafe { element.CurrentControlType() }.map(|value| value.0).unwrap_or_default();
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
            "bounds": [bounds.left, bounds.top, bounds.right, bounds.bottom],
        }));
        elements.insert(element_id, element);
    }
    // Summary fields are best-effort: a missing one is simply omitted so an
    // observation never fails because a control withheld its text.
    let mut accessibility = serde_json::Map::new();
    accessibility.insert("available".to_string(), json!(true));
    accessibility.insert("revision".to_string(), json!(revision));
    if let Some((line, element)) = focused.as_ref() {
        accessibility.insert("focused_element".to_string(), json!(line));
        if let Some(text) = element_text(element) {
            accessibility.insert("document_text".to_string(), json!(text));
        }
        if let Some(text) = element_selected_text(element) {
            accessibility.insert("selected_text".to_string(), json!(text));
        }
    }
    accessibility.insert("elements".to_string(), json!(descriptions));
    Ok((revision, Value::Object(accessibility), elements))
}

pub(super) fn invoke_element(
    state: &ServerState,
    window: &WindowInfo,
    params: &serde_json::Map<String, Value>,
) -> Result<Value, (&'static str, String)> {
    let element = accessibility_element(state, window, params)?;
    reject_recent_user_intervention()?;
    let pattern: IUIAutomationInvokePattern =
        unsafe { element.GetCurrentPatternAs(UIA_InvokePatternId) }.map_err(|_| {
            (
                "uia_pattern_unavailable",
                "The element does not support Invoke.".to_string(),
            )
        })?;
    unsafe { pattern.Invoke() }.map_err(|error| {
        (
            "uia_action_failed",
            format!("UI Automation invoke failed: {error}"),
        )
    })?;
    Ok(json!({"applied": true}))
}

pub(super) fn set_value(
    state: &ServerState,
    window: &WindowInfo,
    params: &serde_json::Map<String, Value>,
) -> Result<Value, (&'static str, String)> {
    let value = params
        .get("value")
        .and_then(Value::as_str)
        .ok_or(("invalid_request", "value is required.".to_string()))?;
    let element = accessibility_element(state, window, params)?;
    reject_recent_user_intervention()?;
    let pattern: IUIAutomationValuePattern =
        unsafe { element.GetCurrentPatternAs(UIA_ValuePatternId) }.map_err(|_| {
            (
                "uia_pattern_unavailable",
                "The element does not support Value.".to_string(),
            )
        })?;
    unsafe { pattern.SetValue(&BSTR::from(value)) }.map_err(|error| {
        (
            "uia_action_failed",
            format!("UI Automation value update failed: {error}"),
        )
    })?;
    Ok(json!({"applied": true}))
}

fn accessibility_element<'a>(
    state: &'a ServerState,
    window: &WindowInfo,
    params: &serde_json::Map<String, Value>,
) -> Result<&'a IUIAutomationElement, (&'static str, String)> {
    let revision = params
        .get("accessibility_revision")
        .and_then(Value::as_str)
        .ok_or((
            "stale_accessibility",
            "accessibility_revision is required.".to_string(),
        ))?;
    let element_id = params
        .get("element_id")
        .and_then(Value::as_str)
        .ok_or(("invalid_request", "element_id is required.".to_string()))?;
    let snapshot = state.accessibility.get(revision).ok_or((
        "stale_accessibility",
        "Accessibility state is no longer available; observe the window again.".to_string(),
    ))?;
    if snapshot.window_hwnd != window.hwnd {
        return Err((
            "stale_accessibility",
            "Element does not belong to this window.".to_string(),
        ));
    }
    if !unsafe { IsWindow(Some(HWND(window.hwnd as _))).as_bool() } {
        return Err((
            "window_not_found",
            "Target window no longer exists.".to_string(),
        ));
    }
    let element = snapshot.elements.get(element_id).ok_or((
        "element_not_found",
        "Element is not available in this accessibility revision.".to_string(),
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
    Ok(element)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn short_document_text_is_returned_unchanged() {
        let text = "hello world".to_string();
        assert_eq!(truncate_document_text(text.clone()), text);
    }

    #[test]
    fn long_document_text_is_bounded_and_flagged() {
        let text: String = "x".repeat(DOC_TEXT_MAX as usize + 500);
        let bounded = truncate_document_text(text);
        assert!(bounded.ends_with("… (truncated)"));
        assert_eq!(
            bounded.chars().filter(|value| *value == 'x').count(),
            DOC_TEXT_MAX as usize
        );
    }

    #[test]
    fn truncation_counts_characters_not_bytes() {
        // Multi-byte text must not be cut mid-character.
        let text: String = "字".repeat(DOC_TEXT_MAX as usize + 10);
        let bounded = truncate_document_text(text);
        assert_eq!(
            bounded.chars().filter(|value| *value == '字').count(),
            DOC_TEXT_MAX as usize
        );
    }

    #[test]
    fn element_line_matches_the_listing_format() {
        assert_eq!(
            element_line("uia-1", "Edit", "text editor"),
            "uia-1 Edit \"text editor\""
        );
    }
}
