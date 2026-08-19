//! UI Automation: element enumeration, invoke, and value-set.

use serde_json::{json, Value};
use std::collections::HashMap;
use windows::core::BSTR;
use windows::Win32::Foundation::{HWND, POINT};
use windows::Win32::System::Com::{CoCreateInstance, CLSCTX_INPROC_SERVER};
use windows::Win32::UI::Accessibility::{
    CUIAutomation, IUIAutomation, IUIAutomationElement, IUIAutomationInvokePattern,
    IUIAutomationSelectionItemPattern, IUIAutomationTextEditPattern, IUIAutomationTextPattern,
    IUIAutomationTreeWalker, IUIAutomationValuePattern, UIA_InvokePatternId,
    UIA_SelectionItemPatternId, UIA_TextEditPatternId, UIA_TextPatternId, UIA_ValuePatternId,
};
use windows::Win32::UI::WindowsAndMessaging::IsWindow;

use super::super::state::{
    accessibility_revision, element_line, truncate_document_text, Observation, PendingAction,
    WindowInfo, ACCESSIBILITY_MAX_ELEMENTS, DOC_TEXT_MAX,
};

const ACCESSIBILITY_MAX_DEPTH: usize = 40;

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
/// Keeps a readable empty value so input effects can be verified.
fn element_text_snapshot(element: &IUIAutomationElement) -> Option<String> {
    let limit = DOC_TEXT_MAX as i32;
    let mut empty_text = None;
    if let Ok(pattern) =
        unsafe { element.GetCurrentPatternAs::<IUIAutomationTextPattern>(UIA_TextPatternId) }
    {
        if let Ok(range) = unsafe { pattern.DocumentRange() } {
            if let Ok(text) = unsafe { range.GetText(limit) } {
                let text = text.to_string();
                if !text.is_empty() {
                    return Some(text);
                }
                empty_text = Some(text);
            }
        }
    }
    let pattern =
        unsafe { element.GetCurrentPatternAs::<IUIAutomationValuePattern>(UIA_ValuePatternId) }
            .ok();
    if let Some(pattern) = pattern {
        if let Ok(value) = unsafe { pattern.CurrentValue() } {
            return Some(truncate_document_text(value.to_string()));
        }
    }
    empty_text
}

fn element_text(element: &IUIAutomationElement) -> Option<String> {
    element_text_snapshot(element).filter(|text| !text.is_empty())
}

pub(crate) struct FocusedTextInput {
    element: IUIAutomationElement,
    before: Option<String>,
}

impl FocusedTextInput {
    pub(crate) fn observed(&self, text: &str) -> bool {
        unsafe { self.element.CurrentHasKeyboardFocus() }
            .map(|focused| focused.as_bool())
            .unwrap_or(false)
            && self
                .before
                .as_deref()
                .zip(element_text_snapshot(&self.element).as_deref())
                .is_some_and(|(before, after)| text_replacement_observed(before, after, text))
    }
}

pub(crate) fn focused_text_input(
    observation: &Observation,
) -> Result<FocusedTextInput, (&'static str, String)> {
    let automation: IUIAutomation =
        unsafe { CoCreateInstance(&CUIAutomation, None, CLSCTX_INPROC_SERVER) }.map_err(|_| {
            (
                "focus_not_editable",
                "UI Automation could not read the current keyboard focus.".to_string(),
            )
        })?;
    let element = unsafe { automation.GetFocusedElement() }.map_err(|_| {
        (
            "focus_not_editable",
            "The observed window has no focused text input.".to_string(),
        )
    })?;
    if !element_belongs_to_window(&element, observation.window.hwnd) {
        return Err((
            "stale_observation",
            "Keyboard focus no longer belongs to the observed window.".to_string(),
        ));
    }
    if !observation
        .elements
        .values()
        .any(|observed| same_element(&automation, observed, &element))
    {
        return Err((
            "stale_observation",
            "Keyboard focus changed after the window was observed; observe it again before typing."
                .to_string(),
        ));
    }
    let writable_value = writable_value_pattern(&element).is_some();
    let text_edit = unsafe {
        element.GetCurrentPatternAs::<IUIAutomationTextEditPattern>(UIA_TextEditPatternId)
    }
    .is_ok();
    if !writable_value && !text_edit {
        return Err((
            "focus_not_editable",
            "The focused element does not expose text editing capabilities.".to_string(),
        ));
    }
    Ok(FocusedTextInput {
        before: element_text_snapshot(&element),
        element,
    })
}

fn text_replacement_observed(before: &str, after: &str, text: &str) -> bool {
    if before == after || text.is_empty() {
        return false;
    }
    let before: Vec<char> = before.chars().collect();
    let after: Vec<char> = after.chars().collect();
    let inserted: Vec<char> = text.chars().collect();
    if inserted.len() > after.len() {
        return false;
    }
    (0..=after.len() - inserted.len()).any(|start| {
        let suffix = after.len() - start - inserted.len();
        after[start..start + inserted.len()] == inserted
            && before.len() >= start + suffix
            && before[..start] == after[..start]
            && before[before.len() - suffix..] == after[start + inserted.len()..]
    })
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
    let walker = unsafe { automation.ControlViewWalker() }
        .map_err(|error| format!("UI Automation tree is unavailable: {error}"))?;
    let raw_walker = unsafe { automation.RawViewWalker() }
        .map_err(|error| format!("UI Automation raw tree is unavailable: {error}"))?;
    let focused_target = unsafe { automation.GetFocusedElement() }
        .ok()
        .filter(|element| element_belongs_to_window_with(&raw_walker, element, window.hwnd));
    let mut collector = AccessibilityCollector::new(&automation, &walker, focused_target.clone());
    collector.collect(root, 0);
    if collector.focused.is_none() {
        if let Some(element) = focused_target {
            let depth = element_depth_with(&raw_walker, &element, window.hwnd);
            collector.publish(element, depth, true);
        }
    }
    // Summary fields are best-effort: a missing one is simply omitted so an
    // observation never fails because a control withheld its text.
    let mut accessibility = serde_json::Map::new();
    accessibility.insert("available".to_string(), json!(true));
    if let Some((line, element)) = collector.focused.as_ref() {
        accessibility.insert("focused_element".to_string(), json!(line));
        if let Some(text) = element_text(element) {
            accessibility.insert("document_text".to_string(), json!(text));
        }
    }
    accessibility.insert("elements".to_string(), json!(collector.descriptions));
    Ok((Value::Object(accessibility), collector.elements))
}

struct AccessibilityCollector<'a> {
    automation: &'a IUIAutomation,
    walker: &'a IUIAutomationTreeWalker,
    focused_target: Option<IUIAutomationElement>,
    elements: HashMap<String, IUIAutomationElement>,
    descriptions: Vec<Value>,
    focused: Option<(String, IUIAutomationElement)>,
}

impl<'a> AccessibilityCollector<'a> {
    fn new(
        automation: &'a IUIAutomation,
        walker: &'a IUIAutomationTreeWalker,
        focused_target: Option<IUIAutomationElement>,
    ) -> Self {
        Self {
            automation,
            walker,
            focused_target,
            elements: HashMap::new(),
            descriptions: Vec::new(),
            focused: None,
        }
    }

    fn collect(&mut self, element: IUIAutomationElement, depth: usize) {
        if depth > ACCESSIBILITY_MAX_DEPTH || self.descriptions.len() >= ACCESSIBILITY_MAX_ELEMENTS
        {
            return;
        }
        self.publish(element.clone(), depth, false);
        if depth == ACCESSIBILITY_MAX_DEPTH {
            return;
        }
        let Ok(mut child) = (unsafe { self.walker.GetFirstChildElement(&element) }) else {
            return;
        };
        loop {
            self.collect(child.clone(), depth + 1);
            if self.descriptions.len() >= ACCESSIBILITY_MAX_ELEMENTS {
                return;
            }
            let Ok(next) = (unsafe { self.walker.GetNextSiblingElement(&child) }) else {
                return;
            };
            if same_element(self.automation, &child, &next) {
                return;
            }
            child = next;
        }
    }

    fn publish(&mut self, element: IUIAutomationElement, depth: usize, reserve_focus: bool) {
        let focused = self
            .focused_target
            .as_ref()
            .is_some_and(|target| same_element(self.automation, target, &element));
        let name = unsafe { element.CurrentName() }
            .map(|value| value.to_string())
            .unwrap_or_default();
        let automation_id = unsafe { element.CurrentAutomationId() }
            .map(|value| value.to_string())
            .unwrap_or_default();
        let settable = writable_value_pattern(&element).is_some();
        let actions = if unsafe {
            element.GetCurrentPatternAs::<IUIAutomationInvokePattern>(UIA_InvokePatternId)
        }
        .is_ok()
        {
            vec!["Invoke"]
        } else {
            Vec::new()
        };
        if name.is_empty()
            && automation_id.is_empty()
            && !focused
            && !settable
            && actions.is_empty()
        {
            return;
        }
        if self.descriptions.len() >= ACCESSIBILITY_MAX_ELEMENTS {
            if !reserve_focus {
                return;
            }
            let removed = format!("uia-{}", ACCESSIBILITY_MAX_ELEMENTS - 1);
            self.descriptions.pop();
            self.elements.remove(&removed);
        }
        let element_id = format!("uia-{}", self.descriptions.len());
        let control_type = unsafe { element.CurrentControlType() }
            .map(|value| value.0)
            .unwrap_or_default();
        let control_type_name = control_type_name(control_type);
        if focused {
            self.focused = Some((
                element_line(&element_id, control_type_name, &name),
                element.clone(),
            ));
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
        self.descriptions.push(json!({
            "id": element_id,
            "name": name,
            "automation_id": automation_id,
            "control_type": control_type,
            "control_type_name": control_type_name,
            "depth": depth,
            "enabled": unsafe { element.CurrentIsEnabled() }.map(|value| value.as_bool()).unwrap_or(false),
            "offscreen": unsafe { element.CurrentIsOffscreen() }.map(|value| value.as_bool()).unwrap_or(true),
            "selected": selected,
            "settable": settable,
            "focused": focused,
            "actions": actions,
            "bounds": [bounds.left, bounds.top, bounds.right, bounds.bottom],
        }));
        self.elements.insert(element_id, element);
    }
}

fn writable_value_pattern(element: &IUIAutomationElement) -> Option<IUIAutomationValuePattern> {
    let pattern =
        unsafe { element.GetCurrentPatternAs::<IUIAutomationValuePattern>(UIA_ValuePatternId) }
            .ok()?;
    unsafe { pattern.CurrentIsReadOnly() }
        .ok()
        .is_some_and(|value| !value.as_bool())
        .then_some(pattern)
}

fn same_element(
    automation: &IUIAutomation,
    first: &IUIAutomationElement,
    second: &IUIAutomationElement,
) -> bool {
    unsafe { automation.CompareElements(first, second) }
        .map(|value| value.as_bool())
        .unwrap_or(false)
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
    element_belongs_to_window_with(&walker, element, hwnd)
}

fn element_belongs_to_window_with(
    walker: &IUIAutomationTreeWalker,
    element: &IUIAutomationElement,
    hwnd: isize,
) -> bool {
    element_depth_with(walker, element, hwnd) < 64
}

fn element_depth_with(
    walker: &IUIAutomationTreeWalker,
    element: &IUIAutomationElement,
    hwnd: isize,
) -> usize {
    let expected = HWND(hwnd as _);
    let mut current = element.clone();
    for depth in 0..64 {
        if unsafe { current.CurrentNativeWindowHandle() }.ok() == Some(expected) {
            return depth;
        }
        let Ok(parent) = (unsafe { walker.GetParentElement(&current) }) else {
            break;
        };
        current = parent;
    }
    64
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

    #[test]
    fn text_effect_requires_the_exact_inserted_delta() {
        assert!(text_replacement_observed("", "hello", "hello"));
        assert!(text_replacement_observed("abc", "abc🙂", "🙂"));
        assert!(text_replacement_observed("256", "36", "36"));
        assert!(text_replacement_observed("abc", "axc", "x"));
        assert!(!text_replacement_observed("36", "36", "36"));
        assert!(!text_replacement_observed("", "36 pt", "36"));
    }
}
