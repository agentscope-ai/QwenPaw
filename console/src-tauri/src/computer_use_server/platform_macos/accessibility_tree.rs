//! Accessibility inspection and element actions on macOS.
//!
//! Mirrors the Windows `uia.rs` leaf: reads the element tree the model acts
//! against, and performs the semantic actions on a named element.

use accessibility::{AXAttribute, AXUIElement};
use accessibility_sys::kAXPressAction;
use core_foundation::base::{CFType, TCFType};
use core_foundation::string::CFString;
use serde_json::{json, Map, Value};
use std::collections::HashMap;

use super::super::state::{element_line, truncate_document_text, Observation, WindowInfo};
use super::{_AXUIElementGetWindow, window_owner_pid};

/// Native accessibility element handle for the shared observation store.
pub(crate) struct AxElement {
    element: AXUIElement,
}

pub(crate) fn invoke_element(
    observation: &Observation,
    params: &Map<String, Value>,
) -> Result<Value, (&'static str, String)> {
    let element = accessibility_element(observation, params)?;
    element
        .element
        .perform_action(&CFString::from_static_string(kAXPressAction))
        .map_err(|error| {
            (
                "action_failed",
                format!("Accessibility press failed: {error:?}"),
            )
        })?;
    Ok(json!({"applied": true}))
}

pub(crate) fn set_value(
    observation: &Observation,
    params: &Map<String, Value>,
) -> Result<Value, (&'static str, String)> {
    let value = params
        .get("value")
        .and_then(Value::as_str)
        .ok_or(("invalid_request", "value is required.".to_string()))?;
    let element = accessibility_element(observation, params)?;
    element
        .element
        .set_attribute(&AXAttribute::value(), CFString::new(value).as_CFType())
        .map_err(|error| {
            (
                "action_failed",
                format!("Accessibility value update failed: {error:?}"),
            )
        })?;
    Ok(json!({"applied": true}))
}

fn accessibility_element<'a>(
    observation: &'a Observation,
    params: &Map<String, Value>,
) -> Result<&'a AxElement, (&'static str, String)> {
    let element_id = params
        .get("element_id")
        .and_then(Value::as_str)
        .ok_or(("invalid_request", "element_id is required.".to_string()))?;
    observation.elements.get(element_id).ok_or((
        "element_not_found",
        "Element is not available in this observation.".to_string(),
    ))
}

pub(super) fn collect_accessibility(
    window: &WindowInfo,
) -> Result<(Value, HashMap<String, AxElement>), String> {
    let pid = window_owner_pid(window.hwnd as i64)
        .ok_or_else(|| "Could not resolve the window's process.".to_string())?;
    let app = AXUIElement::application(pid);
    let _ = app.set_messaging_timeout(super::AX_MESSAGING_TIMEOUT_SECONDS);
    let root = find_ax_window(&app, window.hwnd as u32)
        .ok_or_else(|| "Accessibility could not locate the window.".to_string())?;
    let mut elements = HashMap::new();
    let mut descriptions = Vec::new();
    // The focused element is picked out of this window's own subtree, so it
    // can never describe another application's UI.
    let mut focused: Option<(String, AXUIElement)> = None;
    walk_accessibility(&root, 0, &mut elements, &mut descriptions, &mut focused);
    // Summary fields are best-effort: a missing one is simply omitted so an
    // observation never fails because a control withheld its text.
    let mut accessibility = serde_json::Map::new();
    accessibility.insert("available".to_string(), json!(true));
    if let Some((line, element)) = focused.as_ref() {
        accessibility.insert("focused_element".to_string(), json!(line));
        if let Some(text) = ax_string(element, "AXValue") {
            accessibility.insert(
                "document_text".to_string(),
                json!(truncate_document_text(text)),
            );
        }
    }
    accessibility.insert("elements".to_string(), json!(descriptions));
    Ok((Value::Object(accessibility), elements))
}

/// Read a string-valued accessibility attribute, if the element exposes one.
fn ax_string(element: &AXUIElement, attribute: &'static str) -> Option<String> {
    let value: CFType = element
        .attribute(&AXAttribute::new(&CFString::from_static_string(attribute)))
        .ok()?;
    let text = value.downcast::<CFString>()?.to_string();
    if text.is_empty() {
        return None;
    }
    Some(text)
}

pub(super) fn find_ax_window(app: &AXUIElement, target: u32) -> Option<AXUIElement> {
    find_ax_window_in(app, target, 0)
}

/// Sheets are nested below their owning window in many macOS applications,
/// while ordinary windows are immediate application children. Search both
/// shapes so a standard save/open sheet can be observed and acted on directly.
fn find_ax_window_in(element: &AXUIElement, target: u32, depth: usize) -> Option<AXUIElement> {
    if depth > 12 {
        return None;
    }
    let mut id: u32 = 0;
    let status = unsafe { _AXUIElementGetWindow(element.as_concrete_TypeRef(), &mut id) };
    if status == 0 && id == target {
        return Some(element.clone());
    }
    let children = element.attribute(&AXAttribute::children()).ok()?;
    children
        .iter()
        .find_map(|child| find_ax_window_in(&child, target, depth + 1))
}

fn walk_accessibility(
    element: &AXUIElement,
    depth: usize,
    elements: &mut HashMap<String, AxElement>,
    descriptions: &mut Vec<Value>,
    focused: &mut Option<(String, AXUIElement)>,
) {
    if depth > 40 || descriptions.len() >= 300 {
        return;
    }
    let role = element
        .attribute(&AXAttribute::role())
        .map(|value| value.to_string())
        .unwrap_or_default();
    let title = element
        .attribute(&AXAttribute::title())
        .map(|value| value.to_string())
        .unwrap_or_default();
    let value = element
        .attribute(&AXAttribute::value())
        .ok()
        .and_then(|value: CFType| value.downcast::<CFString>().map(|text| text.to_string()))
        .unwrap_or_default();
    if !role.is_empty() && (!title.is_empty() || !value.is_empty()) {
        let element_id = format!("ax-{}", descriptions.len());
        let control_type_name = role_to_control_type_name(&role);
        if focused.is_none()
            && element
                .attribute(&AXAttribute::focused())
                .map(bool::from)
                .unwrap_or(false)
        {
            *focused = Some((
                element_line(&element_id, control_type_name, &title),
                element.clone(),
            ));
        }
        descriptions.push(json!({
            "id": element_id,
            "name": title,
            "value": value,
            "role": role,
            "control_type_name": control_type_name,
        }));
        elements.insert(
            element_id,
            AxElement {
                element: element.clone(),
            },
        );
    }
    if let Ok(children) = element.attribute(&AXAttribute::children()) {
        for child in children.iter() {
            walk_accessibility(&child, depth + 1, elements, descriptions, focused);
        }
    }
}

/// Map an AX role to the same human-readable control-type vocabulary the
/// Windows leaf uses, so the cross-platform SKILL guidance applies uniformly.
fn role_to_control_type_name(role: &str) -> &'static str {
    match role {
        "AXButton" | "AXMenuButton" => "Button",
        "AXTextField" | "AXTextArea" | "AXSearchField" => "Edit",
        "AXStaticText" => "Text",
        "AXCheckBox" => "CheckBox",
        "AXRadioButton" => "RadioButton",
        "AXPopUpButton" | "AXComboBox" => "ComboBox",
        "AXMenuItem" | "AXMenuBarItem" => "MenuItem",
        "AXLink" => "Hyperlink",
        "AXImage" => "Image",
        "AXList" | "AXTable" | "AXOutline" => "List",
        "AXRow" | "AXCell" => "ListItem",
        "AXTabGroup" => "Tab",
        "AXSlider" => "Slider",
        "AXWindow" => "Window",
        "AXGroup" => "Group",
        _ => "Unknown",
    }
}
