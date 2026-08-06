//! What the platform leaves share: the shape of a window, an observation, and
//! the per-connection store that ties an action back to what was observed.
//!
//! Every `use super::super::` in a platform leaf resolves here, which is the
//! boundary this module is drawn along: nothing in it touches an OS API, and
//! everything in it has to mean the same thing on both platforms. The limits
//! that shape an observation live here for the same reason -- a screenshot
//! delivered at different sizes per platform, or document text truncated at
//! different lengths, would make the observation contract platform-dependent.

use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, Instant};

/// Native accessibility element handle stored with an observation.
/// Windows uses a UI Automation element; macOS uses an AXUIElement wrapper.
#[cfg(windows)]
pub(super) type NativeElement = windows::Win32::UI::Accessibility::IUIAutomationElement;
#[cfg(target_os = "macos")]
pub(super) type NativeElement = super::platform_macos::AxElement;

// Raw window captures are 32bpp bitmaps; re-encode them as JPEG so a
// single screenshot costs hundreds of kilobytes instead of tens of
// megabytes once it is base64-encoded into the response payload.
pub(super) const SCREENSHOT_JPEG_QUALITY: f32 = 0.8;

// Cap the longest edge of a delivered screenshot. High-resolution
// displays (for example 4K) would otherwise produce multi-megabyte
// base64 payloads that inflate the response and the model's image cost.
// Downscaling to a bounded edge keeps the payload small while leaving
// enough detail for reading on-screen text and controls.
pub(super) const SCREENSHOT_MAX_EDGE: u32 = 1600;

// Only the Windows capture path decodes raw bitmaps.
#[cfg(windows)]
pub(super) const BMP_HEADER_BYTES: usize = 54;

/// Upper bound on the document text handed back with an observation. A large
/// document would otherwise dominate the model's context, and the leading
/// portion is what identifies the current state.
pub(super) const DOC_TEXT_MAX: usize = 4000;

/// Minimum idle time after our own input before another action may run.
///
/// The input guard uses the same boundary. Keeping one value prevents a normal
/// observe-after-action cycle from mistaking the helper's synthetic event for
/// fresh user input.
pub(super) const INPUT_GUARD_GRACE_MS: u32 = 750;
// A macOS application can paint a changed view before its accessibility
// children are ready. Keep observations behind that short lag; Windows UIA
// settles inside the existing input-grace window and should not pay it.
#[cfg(target_os = "macos")]
const ACTION_SETTLE_DELAY: Duration = Duration::from_millis(1_500);
#[cfg(windows)]
const ACTION_SETTLE_DELAY: Duration = Duration::from_millis(INPUT_GUARD_GRACE_MS as u64);

static NEXT_ID: AtomicU64 = AtomicU64::new(1);

#[derive(Clone)]
pub(super) struct WindowInfo {
    pub(super) hwnd: isize,
    #[cfg(target_os = "macos")]
    pub(super) owner_pid: i32,
    pub(super) app_id: String,
    pub(super) display_name: String,
    pub(super) title: String,
    // Windows matches this against its credential-dialog guard. macOS has no
    // equivalent notion of a window class and recognises those dialogs by
    // title and owner instead.
    #[cfg_attr(target_os = "macos", allow(dead_code))]
    pub(super) class_name: String,
}

impl WindowInfo {
    pub(super) fn matches_app(&self, value: &str) -> bool {
        self.app_id == value || self.display_name.eq_ignore_ascii_case(value)
    }

    pub(super) fn to_json(&self) -> Value {
        json!({
            "app_id": self.app_id,
            "id": self.hwnd.to_string(),
            "title": self.title,
        })
    }
}

/// Everything an action needs from one observed window.
///
/// The identifier for this object is the only native context exposed to the
/// model. Window handles, screenshot identifiers, and accessibility handles
/// remain local so callers cannot accidentally combine state from separate
/// observations.
pub(super) struct Observation {
    pub(super) window: WindowInfo,
    /// The window's on-screen rectangle as `[left, top, width, height]`.
    /// Origin plus size is used on both platforms so the meaning of each slot
    /// is unambiguous wherever an observation is read.
    pub(super) bounds: [i32; 4],
    // Pixel size of the delivered (possibly downscaled) screenshot. Model
    // coordinates are expressed in this space and mapped back to physical
    // window pixels before input is injected.
    pub(super) display_width: u32,
    pub(super) display_height: u32,
    /// Digest of the normalized accessibility surface the model observed.
    /// Kept native-side so callers cannot copy or forge a revision token.
    pub(super) accessibility_revision: Option<[u8; 32]>,
    pub(super) elements: HashMap<String, NativeElement>,
}

/// Create a stable revision for an available accessibility surface.
pub(super) fn accessibility_revision(accessibility: &Value) -> Option<[u8; 32]> {
    if accessibility.get("available").and_then(Value::as_bool) != Some(true) {
        return None;
    }
    let encoded = serde_json::to_vec(accessibility).ok()?;
    Some(Sha256::digest(encoded).into())
}

/// A native edit that changed a control's buffer but still needs the control's
/// semantic completion action before the surrounding application owns it.
///
/// The shared runtime only knows that `invoke_element` must finish the action.
/// Element identity and the completion mechanism remain native concerns, so
/// this applies to any application exposing the same accessibility semantics
/// without naming an application or control type here.
pub(super) struct PendingAction {
    pub(super) hwnd: isize,
    pub(super) element: NativeElement,
    pub(super) expected_value: String,
}

impl PendingAction {
    pub(super) fn to_json(&self) -> Value {
        json!({
            "status": "requires_completion",
            "required_action": "invoke",
            "expected_value": self.expected_value,
        })
    }
}

#[derive(Default)]
pub(super) struct ServerState {
    pub(super) observations: HashMap<String, Observation>,
    pending_action: Option<PendingAction>,
    last_action_at: HashMap<isize, Instant>,
    global_action_at: Option<Instant>,
}

impl ServerState {
    /// A desktop mutation makes every snapshot of that window stale.
    pub(super) fn note_action(&mut self, hwnd: isize) {
        self.observations
            .retain(|_, observation| observation.window.hwnd != hwnd);
        self.last_action_at.insert(hwnd, Instant::now());
    }

    pub(super) fn note_global_action(&mut self) {
        self.observations.clear();
        self.global_action_at = Some(Instant::now());
    }

    pub(super) fn pending_action(&self) -> Option<&PendingAction> {
        self.pending_action.as_ref()
    }

    pub(super) fn set_pending_action(&mut self, action: PendingAction) {
        self.pending_action = Some(action);
    }

    pub(super) fn clear_pending_action(&mut self) {
        self.pending_action = None;
    }

    /// Wait out only the remainder of the short post-action settling window.
    pub(super) fn settle_before_observe(&mut self, hwnd: isize) {
        let started = self
            .last_action_at
            .remove(&hwnd)
            .or_else(|| self.global_action_at.take());
        let Some(started) = started else { return };
        if let Some(remaining) = ACTION_SETTLE_DELAY.checked_sub(started.elapsed()) {
            std::thread::sleep(remaining);
        }
    }

    pub(super) fn clear_turn(&mut self) {
        self.observations.clear();
        self.pending_action = None;
        self.last_action_at.clear();
        self.global_action_at = None;
    }

    /// Discard point-in-time state after input outside the current action.
    ///
    /// This is deliberately not a sticky turn stop. The refused action may
    /// have had no effect or may have raced with the user, so callers must
    /// observe again before deciding what to do next.
    pub(super) fn invalidate_observations(&mut self) {
        self.observations.clear();
        self.pending_action = None;
    }
}

/// Bound document text by character count, flagging that more remains.
///
/// Counting characters rather than bytes keeps multi-byte text intact.
pub(super) fn truncate_document_text(text: String) -> String {
    if text.chars().count() <= DOC_TEXT_MAX {
        return text;
    }
    let mut bounded: String = text.chars().take(DOC_TEXT_MAX).collect();
    bounded.push_str("… (truncated)");
    bounded
}

/// Render one accessibility element as a single line.
///
/// The format is part of the observation contract the skill documents, so it
/// lives here rather than in either platform leaf.
pub(super) fn element_line(element_id: &str, control_type_name: &str, name: &str) -> String {
    format!("{element_id} {control_type_name} \"{name}\"")
}

/// An application discovered on disk but not currently showing a window.
pub(super) struct InstalledApp {
    pub(super) app_id: String,
    pub(super) display_name: String,
}

/// Build the `list_apps` payload from installed applications and open windows.
///
/// An application that owns a window is reported as running and carries those
/// windows; one found only on disk is reported with no windows. Both platforms
/// share this so `is_running` can never mean different things on each.
pub(super) fn merge_app_list(installed: Vec<InstalledApp>, windows: Vec<WindowInfo>) -> Vec<Value> {
    let mut order: Vec<String> = Vec::new();
    let mut entries: HashMap<String, (String, bool, Vec<Value>)> = HashMap::new();
    for app in installed {
        if !entries.contains_key(&app.app_id) {
            order.push(app.app_id.clone());
        }
        entries
            .entry(app.app_id)
            .or_insert((app.display_name, false, Vec::new()));
    }
    for window in windows {
        let entry = entries.entry(window.app_id.clone()).or_insert_with(|| {
            order.push(window.app_id.clone());
            (window.display_name.clone(), false, Vec::new())
        });
        // A window proves the application is running, and its own display name
        // is the one the user currently sees.
        entry.0 = window.display_name.clone();
        entry.1 = true;
        entry.2.push(window.to_json());
    }
    order
        .into_iter()
        .filter_map(|app_id| {
            let (display_name, is_running, windows) = entries.remove(&app_id)?;
            Some(json!({
                "id": app_id,
                "display_name": display_name,
                "is_running": is_running,
                "windows": windows,
            }))
        })
        .collect()
}

/// Map a coordinate expressed in screenshot space onto the window.
///
/// Returns the offset from the window's origin in physical pixels. Both
/// platforms share the bounds check so a coordinate outside the delivered
/// screenshot can never be extrapolated onto another application's window.
pub(super) fn map_point(
    observation: &Observation,
    x: i64,
    y: i64,
) -> Result<(f64, f64), (&'static str, String)> {
    if observation.display_width == 0 || observation.display_height == 0 {
        return Err((
            "visual_unavailable",
            "Coordinate input requires a window screenshot; use an accessibility element instead."
                .to_string(),
        ));
    }
    let display_width = i64::from(observation.display_width.max(1));
    let display_height = i64::from(observation.display_height.max(1));
    if x < 0 || y < 0 || x >= display_width || y >= display_height {
        return Err((
            "point_outside_viewport",
            "Point is outside the captured viewport.".to_string(),
        ));
    }
    // The screenshot may have been downscaled, so scale back to the window's
    // own pixels. With no downscaling these ratios are 1:1.
    let width = f64::from(observation.bounds[2]);
    let height = f64::from(observation.bounds[3]);
    Ok((
        x as f64 * width / display_width as f64,
        y as f64 * height / display_height as f64,
    ))
}

pub(super) fn next_id(prefix: &str) -> String {
    format!("{prefix}-{}", NEXT_ID.fetch_add(1, Ordering::Relaxed))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn observation(bounds: [i32; 4], display: (u32, u32)) -> Observation {
        Observation {
            window: WindowInfo {
                hwnd: 1,
                #[cfg(target_os = "macos")]
                owner_pid: 1,
                app_id: "app:test".to_string(),
                display_name: "Test".to_string(),
                title: String::new(),
                class_name: String::new(),
            },
            bounds,
            display_width: display.0,
            display_height: display.1,
            accessibility_revision: None,
            elements: HashMap::new(),
        }
    }

    fn window(app_id: &str, display_name: &str, hwnd: isize) -> WindowInfo {
        WindowInfo {
            hwnd,
            #[cfg(target_os = "macos")]
            owner_pid: 1,
            app_id: app_id.to_string(),
            display_name: display_name.to_string(),
            title: String::new(),
            class_name: String::new(),
        }
    }

    #[test]
    fn short_document_text_is_returned_unchanged() {
        let text = "hello world".to_string();
        assert_eq!(truncate_document_text(text.clone()), text);
    }

    #[test]
    fn long_document_text_is_bounded_and_flagged() {
        let bounded = truncate_document_text("x".repeat(DOC_TEXT_MAX + 500));
        assert!(bounded.ends_with("… (truncated)"));
        assert_eq!(
            bounded.chars().filter(|value| *value == 'x').count(),
            DOC_TEXT_MAX
        );
    }

    #[test]
    fn truncation_counts_characters_not_bytes() {
        // Multi-byte text must not be cut mid-character.
        let bounded = truncate_document_text("字".repeat(DOC_TEXT_MAX + 10));
        assert_eq!(
            bounded.chars().filter(|value| *value == '字').count(),
            DOC_TEXT_MAX
        );
    }

    #[test]
    fn element_line_matches_the_listing_format() {
        assert_eq!(
            element_line("uia-1", "Edit", "text editor"),
            "uia-1 Edit \"text editor\""
        );
    }

    #[test]
    fn a_point_inside_the_viewport_maps_by_proportion() {
        // A 200x100 window delivered as a 100x50 screenshot is a 2:1 scale.
        let snap = observation([10, 20, 200, 100], (100, 50));
        let (x, y) = map_point(&snap, 50, 25).unwrap();
        assert_eq!((x as i32, y as i32), (100, 50));
    }

    #[test]
    fn an_unscaled_screenshot_maps_one_to_one() {
        let snap = observation([0, 0, 100, 100], (100, 100));
        let (x, y) = map_point(&snap, 30, 40).unwrap();
        assert_eq!((x as i32, y as i32), (30, 40));
    }

    #[test]
    fn points_outside_the_viewport_are_refused() {
        let snap = observation([0, 0, 100, 100], (100, 100));
        for (x, y) in [(-1, 0), (0, -1), (100, 0), (0, 100)] {
            let error = map_point(&snap, x, y).expect_err("must be refused");
            assert_eq!(error.0, "point_outside_viewport");
        }
    }

    #[test]
    fn a_running_application_reports_its_windows() {
        let apps = merge_app_list(
            Vec::new(),
            vec![
                window("app:editor", "Editor", 1),
                window("app:editor", "Editor", 2),
            ],
        );
        assert_eq!(apps.len(), 1);
        assert_eq!(apps[0]["is_running"], serde_json::json!(true));
        assert_eq!(apps[0]["windows"].as_array().unwrap().len(), 2);
    }

    #[test]
    fn an_installed_application_reports_no_windows() {
        let installed = vec![InstalledApp {
            app_id: "app:/applications/notes.app".to_string(),
            display_name: "Notes".to_string(),
        }];
        let apps = merge_app_list(installed, Vec::new());
        assert_eq!(apps.len(), 1);
        assert_eq!(apps[0]["is_running"], serde_json::json!(false));
        assert!(apps[0]["windows"].as_array().unwrap().is_empty());
    }

    #[test]
    fn a_running_application_is_not_duplicated_by_its_installed_entry() {
        let installed = vec![InstalledApp {
            app_id: "app:/applications/editor.app".to_string(),
            // A stale on-disk name must not win over the live window's name.
            display_name: "Editor 1.0".to_string(),
        }];
        let apps = merge_app_list(
            installed,
            vec![window("app:/applications/editor.app", "Editor", 1)],
        );
        assert_eq!(apps.len(), 1);
        assert_eq!(apps[0]["is_running"], serde_json::json!(true));
        assert_eq!(apps[0]["display_name"], serde_json::json!("Editor"));
        assert_eq!(apps[0]["windows"].as_array().unwrap().len(), 1);
    }
}
