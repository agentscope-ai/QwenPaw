//! Window capture and observation on macOS.
//!
//! Mirrors the Windows `capture.rs` leaf: produces the screenshot plus the
//! snapshot that binds later input to what the model actually saw.

use base64::Engine;
use core_graphics::geometry::{CGPoint, CGRect, CGSize};
use core_graphics::window::{
    create_image, kCGWindowImageBoundsIgnoreFraming, kCGWindowListOptionIncludingWindow, CGWindowID,
};
use jpeg_encoder::{ColorType, Encoder};
use serde_json::{json, Map, Value};

use super::super::state::{
    next_id, AccessibilitySnapshot, ServerState, Snapshot, WindowInfo, SCREENSHOT_JPEG_QUALITY,
    SCREENSHOT_MAX_EDGE,
};
use super::accessibility_tree::collect_accessibility;
use super::window_bounds;

pub(crate) fn observe_window(
    state: &mut ServerState,
    window: &WindowInfo,
) -> Result<Value, (&'static str, String)> {
    // Dev-tier capture uses the synchronous CGWindowListCreateImage. A null
    // screen rect with kCGWindowListOptionIncludingWindow captures just this
    // window at its own bounds. Migrate to ScreenCaptureKit for the shippable
    // (background-capable) build.
    let null_rect = CGRect {
        origin: CGPoint {
            x: f64::INFINITY,
            y: f64::INFINITY,
        },
        size: CGSize {
            width: 0.0,
            height: 0.0,
        },
    };
    let image = create_image(
        null_rect,
        kCGWindowListOptionIncludingWindow,
        window.hwnd as CGWindowID,
        kCGWindowImageBoundsIgnoreFraming,
    )
    .ok_or(("capture_failed", "Could not capture the window.".to_string()))?;

    let width = image.width();
    let height = image.height();
    let bytes_per_row = image.bytes_per_row();
    let pixel_bytes = image.bits_per_pixel() / 8;
    if width == 0 || height == 0 || pixel_bytes < 3 {
        return Err((
            "capture_failed",
            "Captured window had no pixels.".to_string(),
        ));
    }
    let data = image.data();
    let raw = data.bytes();

    // Bound the longest edge to keep the payload and image-token cost small,
    // matching the Windows leaf. Nearest-neighbor is adequate for on-screen
    // text/control legibility at this scale.
    let longest = width.max(height) as u32;
    let (display_width, display_height) = if longest > SCREENSHOT_MAX_EDGE {
        let scale = SCREENSHOT_MAX_EDGE as f64 / longest as f64;
        (
            ((width as f64 * scale).round() as usize).max(1),
            ((height as f64 * scale).round() as usize).max(1),
        )
    } else {
        (width, height)
    };

    // CGWindowListCreateImage yields 32-bit BGRA (premultiplied). Repack into
    // tight RGB for the JPEG encoder.
    let mut rgb = Vec::with_capacity(display_width * display_height * 3);
    for out_y in 0..display_height {
        let src_y = (out_y * height / display_height).min(height - 1);
        let row = src_y * bytes_per_row;
        for out_x in 0..display_width {
            let src_x = (out_x * width / display_width).min(width - 1);
            let offset = row + src_x * pixel_bytes;
            rgb.push(raw[offset + 2]);
            rgb.push(raw[offset + 1]);
            rgb.push(raw[offset]);
        }
    }

    let mut jpeg = Vec::new();
    let quality = (SCREENSHOT_JPEG_QUALITY * 100.0).round().clamp(1.0, 100.0) as u8;
    Encoder::new(&mut jpeg, quality)
        .encode(
            &rgb,
            display_width as u16,
            display_height as u16,
            ColorType::Rgb,
        )
        .map_err(|error| ("capture_failed", format!("JPEG encoding failed: {error}")))?;

    let capture_id = next_id("screenshot");
    let snapshot_id = next_id("snapshot");
    // Store the window's on-screen bounds in points so coordinate input can map
    // display-space fractions back to the global point coordinates CGEvent uses.
    let point_bounds = window_bounds(window.hwnd as i64)
        .map(|(x, y, w, h)| [x as i32, y as i32, w as i32, h as i32])
        .unwrap_or([0, 0, width as i32, height as i32]);
    state.snapshots.insert(
        snapshot_id.clone(),
        Snapshot {
            window: window.clone(),
            bounds: point_bounds,
            screenshot_id: capture_id.clone(),
            display_width: display_width as u32,
            display_height: display_height as u32,
        },
    );

    let (accessibility_revision, accessibility) = match collect_accessibility(window) {
        Ok((revision, description, elements)) => {
            state.accessibility.insert(
                revision.clone(),
                AccessibilitySnapshot {
                    window_hwnd: window.hwnd,
                    elements,
                },
            );
            (revision, description)
        }
        Err(reason) => (
            String::new(),
            json!({"available": false, "reason": reason, "elements": []}),
        ),
    };

    Ok(json!({
        "snapshot_id": snapshot_id,
        "geometry_revision": next_id("geometry"),
        "accessibility_revision": accessibility_revision,
        "window": window.to_json(),
        "accessibility": accessibility,
        "screenshots": [{
            "id": capture_id,
            "url": format!(
                "data:image/jpeg;base64,{}",
                base64::engine::general_purpose::STANDARD.encode(&jpeg),
            ),
        }],
    }))
}
