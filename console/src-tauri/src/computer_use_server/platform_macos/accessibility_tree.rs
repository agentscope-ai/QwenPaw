//! Accessibility inspection and element actions on macOS.
//!
//! Mirrors the Windows `uia.rs` leaf: reads the element tree the model acts
//! against, and performs the semantic actions on a named element.

use accessibility::{AXAttribute, AXUIElement};
use accessibility_sys::{
    kAXPressAction, kAXValueTypeCGPoint, kAXValueTypeCGSize, AXUIElementCopyElementAtPosition,
    AXUIElementGetPid, AXUIElementRef, AXValueGetType, AXValueGetValue, AXValueRef,
};
use core_foundation::base::{CFType, TCFType};
use core_foundation::boolean::CFBoolean;
use core_foundation::string::CFString;
use core_foundation::url::CFURL;
use core_graphics::geometry::{CGPoint, CGSize};
use serde_json::{json, Map, Value};
use std::collections::HashMap;
use std::ffi::c_void;

use super::super::state::{
    accessibility_revision, element_line, truncate_document_text, Observation, PendingAction,
    WindowInfo,
};
use super::{_AXUIElementGetWindow, target_is_frontmost, transient_surface_points};

const AX_CONFIRM_ACTION: &str = "AXConfirm";
const AX_OPEN_ACTION: &str = "AXOpen";
const AX_PICK_ACTION: &str = "AXPick";
const AX_SHOW_MENU_ACTION: &str = "AXShowMenu";

/// Native accessibility element handle for the shared observation store.
pub(crate) struct AxElement {
    element: AXUIElement,
    scope: ElementScope,
}

#[derive(Clone, Copy)]
enum ElementScope {
    Window(u32),
    AppSurface(u32),
}

pub(crate) fn element_point(
    observation: &Observation,
    params: &Map<String, Value>,
) -> Result<(f64, f64), (&'static str, String)> {
    let element_id = params
        .get("element_id")
        .and_then(Value::as_str)
        .ok_or(("invalid_request", "element_id is required.".to_string()))?;
    element_point_by_id(observation, element_id)
}

pub(crate) fn element_point_by_id(
    observation: &Observation,
    element_id: &str,
) -> Result<(f64, f64), (&'static str, String)> {
    let element = observation.elements.get(element_id).ok_or((
        "element_not_found",
        "Element is not available in this observation.".to_string(),
    ))?;
    if !element_enabled(&element.element) {
        return Err((
            "element_unavailable",
            "Element is no longer enabled.".to_string(),
        ));
    }
    let position = ax_point(&element.element, "AXPosition").ok_or((
        "element_unavailable",
        "The element does not expose an on-screen position.".to_string(),
    ))?;
    let size = ax_size(&element.element, "AXSize").ok_or((
        "element_unavailable",
        "The element does not expose an on-screen size.".to_string(),
    ))?;
    if size.width <= 0.0 || size.height <= 0.0 {
        return Err((
            "element_unavailable",
            "The element has no clickable area.".to_string(),
        ));
    }
    Ok((
        position.x + size.width / 2.0,
        position.y + size.height / 2.0,
    ))
}

/// Return the native window whose interactive accessibility element occupies
/// a screen point.
///
/// CoreGraphics includes non-interactive overlays (watermarks, HUDs and
/// recording indicators) in its visual z-order. Accessibility hit testing
/// follows the element that would actually receive input, so element clicks
/// are not rejected merely because a transparent overlay is painted above
/// them.
pub(crate) fn interactive_window_at_point(point: CGPoint) -> Option<i64> {
    let mut current = interactive_element_at_point(point)?;
    for _ in 0..64 {
        let mut window_id = 0;
        if unsafe { _AXUIElementGetWindow(current.as_concrete_TypeRef(), &mut window_id) } == 0
            && window_id != 0
        {
            return Some(i64::from(window_id));
        }
        let parent = current
            .attribute(&AXAttribute::new(&CFString::from_static_string("AXParent")))
            .ok()?;
        current = parent.downcast_into::<AXUIElement>()?;
    }
    None
}

fn interactive_element_at_point(point: CGPoint) -> Option<AXUIElement> {
    let system = AXUIElement::system_wide();
    let mut hit_ref: AXUIElementRef = std::ptr::null_mut();
    let status = unsafe {
        AXUIElementCopyElementAtPosition(
            system.as_concrete_TypeRef(),
            point.x as f32,
            point.y as f32,
            &mut hit_ref,
        )
    };
    (status == 0 && !hit_ref.is_null())
        .then(|| unsafe { AXUIElement::wrap_under_create_rule(hit_ref) })
}

/// Return the frontmost transient menu owned by the target application.
///
/// Context menus are separate application surfaces on macOS: they are not
/// descendants of the content window, and the application's menu bar also
/// exposes every closed menu command. CoreGraphics identifies the app's
/// on-screen transient windows in front-to-back order; accessibility hit
/// testing then resolves the actual menu instead of depending on the pointer
/// landing inside a menu that macOS may offset from the click point.
fn active_menu(app: &AXUIElement, expected_pid: i32, content_window: i64) -> Option<AXUIElement> {
    if focused_window_id(app) != u32::try_from(content_window).ok() {
        return None;
    }
    transient_surface_points(expected_pid, content_window)
        .into_iter()
        .find_map(|point| menu_at_point(point, expected_pid))
}

fn menu_at_point(point: CGPoint, expected_pid: i32) -> Option<AXUIElement> {
    let mut current = interactive_element_at_point(point)?;
    for _ in 0..64 {
        let mut pid = 0;
        if unsafe { AXUIElementGetPid(current.as_concrete_TypeRef(), &mut pid) } != 0
            || pid != expected_pid
        {
            return None;
        }
        let role = current
            .attribute(&AXAttribute::role())
            .map(|value| value.to_string())
            .unwrap_or_default();
        if role == "AXMenu" {
            return Some(current);
        }
        let parent = current
            .attribute(&AXAttribute::new(&CFString::from_static_string("AXParent")))
            .ok()?;
        current = parent.downcast_into::<AXUIElement>()?;
    }
    None
}

pub(crate) fn invoke_accessibility_element(
    observation: &Observation,
    params: &Map<String, Value>,
    pending: Option<&PendingAction>,
) -> Result<Value, (&'static str, String)> {
    let element = accessibility_element(observation, params)?;
    let actions = action_names(&element.element);
    // Some editable controls expose a separate semantic completion action.
    // Committing through AX is more reliable than a synthetic Return key whose
    // focus may have moved since the observation was captured.
    let action = if let Some(pending) = pending {
        if pending.hwnd != observation.window.hwnd
            || pending.element.element.as_CFType() != element.element.as_CFType()
        {
            return Err((
                "pending_action_mismatch",
                "The invoked element is not the edit awaiting completion.".to_string(),
            ));
        }
        if ax_string_allow_empty(&element.element, "AXValue").as_deref()
            != Some(pending.expected_value.as_str())
        {
            return Err((
                "pending_action_changed",
                "The pending edit changed before it could be completed.".to_string(),
            ));
        }
        if !actions.iter().any(|action| action == AX_CONFIRM_ACTION) {
            return Err((
                "pending_action_unavailable",
                "The pending edit no longer exposes its semantic completion action.".to_string(),
            ));
        }
        AX_CONFIRM_ACTION
    } else if actions.iter().any(|action| action == kAXPressAction) {
        let role = element
            .element
            .attribute(&AXAttribute::role())
            .map(|value| value.to_string())
            .unwrap_or_default();
        if matches!(role.as_str(), "AXMenuItem" | "AXMenuBarItem")
            && actions.iter().any(|action| action == AX_PICK_ACTION)
        {
            AX_PICK_ACTION
        } else {
            kAXPressAction
        }
    } else if actions.iter().any(|action| action == AX_OPEN_ACTION) {
        AX_OPEN_ACTION
    } else if actions.iter().any(|action| action == AX_CONFIRM_ACTION) {
        AX_CONFIRM_ACTION
    } else {
        return Err((
            "unsupported_operation",
            "The element does not expose a supported primary action.".to_string(),
        ));
    };
    element
        .element
        .perform_action(&CFString::from_static_string(action))
        .map_err(|error| {
            (
                "action_failed",
                format!("Accessibility {action} failed: {error:?}"),
            )
        })?;
    Ok(json!({"applied": true, "native_action": action}))
}

/// Open an element's native context menu when the application exposes one.
///
/// This keeps semantic right-clicks attached to the observed element even
/// when a non-interactive overlay is painted above the target application.
pub(crate) fn show_accessibility_menu(
    observation: &Observation,
    params: &Map<String, Value>,
) -> Result<Option<Value>, (&'static str, String)> {
    let element = accessibility_element(observation, params)?;
    if let Err(error) = element
        .element
        .perform_action(&CFString::from_static_string(AX_SHOW_MENU_ACTION))
    {
        log::debug!(
            "[computer-use] {AX_SHOW_MENU_ACTION} unavailable; using verified pointer fallback: {error:?}"
        );
        return Ok(None);
    }
    Ok(Some(
        json!({"applied": true, "native_action": AX_SHOW_MENU_ACTION}),
    ))
}

pub(crate) fn set_value(
    observation: &Observation,
    params: &Map<String, Value>,
) -> Result<(Value, Option<PendingAction>), (&'static str, String)> {
    let value = params
        .get("value")
        .and_then(Value::as_str)
        .ok_or(("invalid_request", "value is required.".to_string()))?;
    let element = accessibility_element(observation, params)?;
    let attribute = AXAttribute::value();
    let actions = action_names(&element.element);
    // A resource URL means this value is a label for an object owned by the
    // application, not an independent edit buffer. Setting that label can
    // repaint it without changing the resource. Require the application's
    // own edit command to enter a real editor first; active inline editors no
    // longer carry the backing URL.
    if ax_url(&element.element).is_some()
        && actions.iter().any(|action| action == AX_CONFIRM_ACTION)
    {
        return Err((
            "semantic_edit_required",
            "This resource-backed label must be edited through the application's edit command, not set_value."
                .to_string(),
        ));
    }
    if !element.element.is_settable(&attribute).unwrap_or(false) {
        return Err((
            "unsupported_operation",
            "The element does not support setting its value.".to_string(),
        ));
    }
    element
        .element
        .set_attribute(&attribute, CFString::new(value).as_CFType())
        .map_err(|error| {
            (
                "action_failed",
                format!("Accessibility value update failed: {error:?}"),
            )
        })?;
    let actual = ax_string_allow_empty(&element.element, "AXValue").ok_or((
        "postcondition_failed",
        "The element no longer exposes a readable value.".to_string(),
    ))?;
    if actual != value {
        return Err((
            "postcondition_failed",
            "The element did not retain the requested value.".to_string(),
        ));
    }
    let confirmation_required = actions.iter().any(|action| action == AX_CONFIRM_ACTION);
    let pending = confirmation_required.then(|| PendingAction {
        hwnd: observation.window.hwnd,
        element: AxElement {
            element: element.element.clone(),
            scope: element.scope,
        },
        expected_value: actual.clone(),
    });
    Ok((
        json!({
            "applied": true,
            "value": actual,
            "confirmation_required": confirmation_required,
            "next_action": if confirmation_required {
                "observe_window_then_invoke"
            } else {
                "observe_window"
            },
        }),
        pending,
    ))
}

fn accessibility_element<'a>(
    observation: &'a Observation,
    params: &Map<String, Value>,
) -> Result<&'a AxElement, (&'static str, String)> {
    let element_id = params
        .get("element_id")
        .and_then(Value::as_str)
        .ok_or(("invalid_request", "element_id is required.".to_string()))?;
    let element = observation.elements.get(element_id).ok_or((
        "element_not_found",
        "Element is not available in this observation.".to_string(),
    ))?;
    let target_window = u32::try_from(observation.window.hwnd).map_err(|_| {
        (
            "stale_observation",
            "The observed window is no longer valid; observe it again.".to_string(),
        )
    })?;
    let in_scope = match element.scope {
        ElementScope::Window(window_id) => {
            window_id == target_window && owning_window_id(&element.element) == Some(target_window)
        }
        ElementScope::AppSurface(window_id) => {
            window_id == target_window
                && target_is_frontmost(&observation.window)
                && focused_window_id(&AXUIElement::application(observation.window.owner_pid))
                    == Some(target_window)
        }
    };
    if !in_scope {
        return Err((
            "stale_observation",
            "The element is no longer part of the observed window; observe it again.".to_string(),
        ));
    }
    if !element_enabled(&element.element) {
        return Err((
            "element_unavailable",
            "Element is no longer enabled.".to_string(),
        ));
    }
    Ok(element)
}

/// Re-read the normalized AX surface before a semantic mutation.
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

pub(super) fn collect_accessibility(
    window: &WindowInfo,
) -> Result<(Value, HashMap<String, AxElement>), String> {
    let target_window = u32::try_from(window.hwnd)
        .map_err(|_| "Accessibility window identifier is invalid.".to_string())?;
    let pid = (window.owner_pid > 0)
        .then_some(window.owner_pid)
        .ok_or_else(|| "Could not resolve the window's process.".to_string())?;
    let app = AXUIElement::application(pid);
    let _ = app.set_messaging_timeout(super::AX_MESSAGING_TIMEOUT_SECONDS);
    let root = find_ax_window(&app, window.hwnd as u32)
        .ok_or_else(|| "Accessibility could not locate the window.".to_string())?;
    // Descendants may retain AXFocused while a nested editor owns the keyboard.
    // The application-level focus value is the authoritative typing target.
    let focused_target = app
        .attribute(&AXAttribute::new(&CFString::from_static_string(
            "AXFocusedUIElement",
        )))
        .ok()
        .and_then(|value: CFType| value.downcast_into::<AXUIElement>());
    let mut elements = HashMap::new();
    let mut descriptions = Vec::new();
    // The focused element is picked out of this window's own subtree, so it
    // can never describe another application's UI.
    let mut focused: Option<(String, AXUIElement)> = None;
    let mut visited = Vec::new();
    if let Some(menu) = active_menu(&app, pid, window.hwnd as i64) {
        // Match the application surface a person is acting on: while a context
        // menu is open, its commands are the complete actionable state. The
        // underlying window and closed menu-bar descendants would only add
        // stale or ambiguous targets.
        walk_accessibility(
            &menu,
            0,
            40,
            &mut elements,
            &mut descriptions,
            &mut focused,
            focused_target.as_ref(),
            &mut visited,
            ElementScope::AppSurface(target_window),
        );
    } else {
        walk_accessibility(
            &root,
            0,
            40,
            &mut elements,
            &mut descriptions,
            &mut focused,
            focused_target.as_ref(),
            &mut visited,
            ElementScope::Window(target_window),
        );
        // The menu bar belongs to the application rather than the content
        // window. Publish only its first level while it is closed; descendants
        // become actionable only when their menu is the active surface above.
        if focused_window_id(&app) == Some(target_window) {
            if let Some(menu_bar) = ax_element(&app, "AXMenuBar") {
                walk_accessibility(
                    &menu_bar,
                    0,
                    1,
                    &mut elements,
                    &mut descriptions,
                    &mut focused,
                    focused_target.as_ref(),
                    &mut visited,
                    ElementScope::AppSurface(target_window),
                );
            }
        }
        // Sheets, popovers and inline editors may move keyboard focus to an
        // application-owned branch outside the observed window. Merge only
        // that active branch; walking the whole application would duplicate
        // every window and exhaust the observation limit.
        if let Some(target) = focused_target.as_ref() {
            if !visited
                .iter()
                .any(|seen| seen.as_CFType() == target.as_CFType())
            {
                if owning_window_id(target) == Some(target_window) {
                    let branch = top_level_branch(&app, target);
                    walk_accessibility(
                        &branch,
                        0,
                        40,
                        &mut elements,
                        &mut descriptions,
                        &mut focused,
                        focused_target.as_ref(),
                        &mut visited,
                        ElementScope::Window(target_window),
                    );
                }
            }
        }
    }
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
    ax_string_allow_empty(element, attribute).filter(|text| !text.is_empty())
}

fn ax_string_allow_empty(element: &AXUIElement, attribute: &'static str) -> Option<String> {
    let value: CFType = element
        .attribute(&AXAttribute::new(&CFString::from_static_string(attribute)))
        .ok()?;
    Some(value.downcast::<CFString>()?.to_string())
}

fn ax_url(element: &AXUIElement) -> Option<String> {
    let value: CFType = element
        .attribute(&AXAttribute::new(&CFString::from_static_string("AXURL")))
        .ok()?;
    Some(value.downcast::<CFURL>()?.get_string().to_string())
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

fn focused_window_id(app: &AXUIElement) -> Option<u32> {
    let focused = ax_element(app, "AXFocusedWindow")?;
    owning_window_id(&focused)
}

fn owning_window_id(element: &AXUIElement) -> Option<u32> {
    let mut current = element.clone();
    for _ in 0..64 {
        let mut id = 0;
        if unsafe { _AXUIElementGetWindow(current.as_concrete_TypeRef(), &mut id) } == 0 && id != 0
        {
            return Some(id);
        }
        let parent = current.attribute(&AXAttribute::parent()).ok()?;
        if parent.as_CFType() == current.as_CFType() {
            return None;
        }
        current = parent;
    }
    None
}

fn walk_accessibility(
    element: &AXUIElement,
    depth: usize,
    max_depth: usize,
    elements: &mut HashMap<String, AxElement>,
    descriptions: &mut Vec<Value>,
    focused: &mut Option<(String, AXUIElement)>,
    focused_target: Option<&AXUIElement>,
    visited: &mut Vec<AXUIElement>,
    scope: ElementScope,
) {
    if depth > max_depth || descriptions.len() >= 300 {
        return;
    }
    // AXChildren and AXVisibleChildren can return distinct references for one
    // logical control. CF equality identifies the native object; pointer
    // identity produced duplicate, unstable element IDs.
    if visited
        .iter()
        .any(|seen| seen.as_CFType() == element.as_CFType())
    {
        return;
    }
    visited.push(element.clone());
    let role = element
        .attribute(&AXAttribute::role())
        .map(|value| value.to_string())
        .unwrap_or_default();
    let title = element
        .attribute(&AXAttribute::title())
        .map(|value| value.to_string())
        .unwrap_or_default();
    let description = element
        .attribute(&AXAttribute::description())
        .map(|value| value.to_string())
        .unwrap_or_default();
    let identifier = element
        .attribute(&AXAttribute::identifier())
        .map(|value| value.to_string())
        .unwrap_or_default();
    let help = element
        .attribute(&AXAttribute::help())
        .map(|value| value.to_string())
        .unwrap_or_default();
    let value = element
        .attribute(&AXAttribute::value())
        .ok()
        .and_then(|value: CFType| value.downcast::<CFString>().map(|text| text.to_string()))
        .unwrap_or_default();
    let name = [&title, &description, &identifier]
        .into_iter()
        .find(|candidate| !candidate.is_empty())
        .cloned()
        .unwrap_or_default();
    let enabled = element_enabled(element);
    let selected = ax_bool(element, "AXSelected").unwrap_or(false);
    let actions = action_names(element);
    let resource_backed = ax_url(element).is_some();
    let settable = element.is_settable(&AXAttribute::value()).unwrap_or(false)
        && !(resource_backed && actions.iter().any(|action| action == "AXConfirm"));
    // Native collection views commonly expose a disabled, actionless group
    // and an enabled image with the same label. The group is layout metadata,
    // not a second target; its children still carry the useful content.
    let inert_group = role == "AXGroup" && !enabled && !settable && actions.is_empty();
    if !inert_group
        && !role.is_empty()
        && (!name.is_empty()
            || !value.is_empty()
            || is_actionable_role(&role)
            || settable
            || !actions.is_empty())
    {
        let element_id = format!("ax-{}", descriptions.len());
        let control_type_name = role_to_control_type_name(&role);
        if focused.is_none()
            && focused_target.is_some_and(|target| element.as_CFType() == target.as_CFType())
        {
            *focused = Some((
                element_line(&element_id, control_type_name, &name),
                element.clone(),
            ));
        }
        descriptions.push(json!({
            "id": element_id,
            "name": name,
            "value": value,
            "role": role,
            "control_type_name": control_type_name,
            "identifier": identifier,
            "help": help,
            "enabled": enabled,
            "selected": selected,
            "settable": settable,
            "resource_backed": resource_backed,
            "actions": actions,
        }));
        elements.insert(
            element_id,
            AxElement {
                element: element.clone(),
                scope,
            },
        );
    }
    if let Ok(children) = element.attribute(&AXAttribute::children()) {
        for child in children.iter() {
            walk_accessibility(
                &child,
                depth + 1,
                max_depth,
                elements,
                descriptions,
                focused,
                focused_target,
                visited,
                scope,
            );
        }
    }
    if let Ok(children) = element.attribute(&AXAttribute::visible_children()) {
        for child in children.iter() {
            walk_accessibility(
                &child,
                depth + 1,
                max_depth,
                elements,
                descriptions,
                focused,
                focused_target,
                visited,
                scope,
            );
        }
    }
}

fn element_enabled(element: &AXUIElement) -> bool {
    element
        .attribute(&AXAttribute::enabled())
        .map(bool::from)
        .unwrap_or(true)
}

fn ax_element(element: &AXUIElement, attribute: &'static str) -> Option<AXUIElement> {
    let value: CFType = element
        .attribute(&AXAttribute::new(&CFString::from_static_string(attribute)))
        .ok()?;
    value.downcast_into::<AXUIElement>()
}

fn ax_bool(element: &AXUIElement, attribute: &'static str) -> Option<bool> {
    let value: CFType = element
        .attribute(&AXAttribute::new(&CFString::from_static_string(attribute)))
        .ok()?;
    value.downcast::<CFBoolean>().map(bool::from)
}

fn ax_point(element: &AXUIElement, attribute: &'static str) -> Option<CGPoint> {
    let value: CFType = element
        .attribute(&AXAttribute::new(&CFString::from_static_string(attribute)))
        .ok()?;
    let value = value.as_concrete_TypeRef() as AXValueRef;
    if unsafe { AXValueGetType(value) } != kAXValueTypeCGPoint {
        return None;
    }
    let mut point = CGPoint { x: 0.0, y: 0.0 };
    unsafe {
        AXValueGetValue(
            value,
            kAXValueTypeCGPoint,
            &mut point as *mut CGPoint as *mut c_void,
        )
    }
    .then_some(point)
}

fn ax_size(element: &AXUIElement, attribute: &'static str) -> Option<CGSize> {
    let value: CFType = element
        .attribute(&AXAttribute::new(&CFString::from_static_string(attribute)))
        .ok()?;
    let value = value.as_concrete_TypeRef() as AXValueRef;
    if unsafe { AXValueGetType(value) } != kAXValueTypeCGSize {
        return None;
    }
    let mut size = CGSize {
        width: 0.0,
        height: 0.0,
    };
    unsafe {
        AXValueGetValue(
            value,
            kAXValueTypeCGSize,
            &mut size as *mut CGSize as *mut c_void,
        )
    }
    .then_some(size)
}

fn top_level_branch(app: &AXUIElement, target: &AXUIElement) -> AXUIElement {
    let mut current = target.clone();
    for _ in 0..20 {
        let Ok(parent) = current.attribute(&AXAttribute::parent()) else {
            break;
        };
        if parent.as_CFType() == app.as_CFType() {
            break;
        }
        if parent.as_CFType() == current.as_CFType() {
            break;
        }
        current = parent;
    }
    current
}

fn action_names(element: &AXUIElement) -> Vec<String> {
    element
        .action_names()
        .map(|actions| actions.iter().map(|action| action.to_string()).collect())
        .unwrap_or_default()
}

fn is_actionable_role(role: &str) -> bool {
    matches!(
        role,
        "AXButton"
            | "AXMenuButton"
            | "AXTextField"
            | "AXTextArea"
            | "AXSearchField"
            | "AXCheckBox"
            | "AXRadioButton"
            | "AXPopUpButton"
            | "AXComboBox"
            | "AXMenuItem"
            | "AXLink"
            | "AXSlider"
    )
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
        "AXMenu" | "AXMenuBar" => "Menu",
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
