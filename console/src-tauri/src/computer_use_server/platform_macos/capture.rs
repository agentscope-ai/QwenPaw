//! Window capture and observation on macOS.
//!
//! Mirrors the Windows `capture.rs` leaf: produces the screenshot plus the
//! observation that binds later input to what the model actually saw.

use base64::Engine;
use block2::RcBlock;
use core_graphics::image::CGImageRef;
use jpeg_encoder::{ColorType, Encoder};
use objc2::AnyThread;
use objc2_screen_capture_kit::{
    SCContentFilter, SCScreenshotManager, SCShareableContent, SCStreamConfiguration,
};
use serde_json::{json, Value};
use std::sync::mpsc;
use std::time::Duration;

use super::super::state::{
    accessibility_revision, next_id, Observation, ServerState, WindowInfo, SCREENSHOT_JPEG_QUALITY,
    SCREENSHOT_MAX_EDGE,
};
use super::accessibility_tree::collect_accessibility;
use super::window_bounds;

pub(crate) fn observe_window(
    state: &mut ServerState,
    window: &WindowInfo,
) -> Result<Value, (&'static str, String)> {
    let window_id = u32::try_from(window.hwnd).map_err(|_| {
        (
            "window_not_capturable",
            "The selected window is no longer available.".to_string(),
        )
    })?;
    let point_bounds = window_bounds(window.hwnd as i64)
        .map(|(x, y, w, h)| [x as i32, y as i32, w as i32, h as i32]);
    let (capture_width, capture_height) = point_bounds
        .map(|bounds| bounded_capture_dimensions(bounds[2], bounds[3]))
        .unwrap_or((SCREENSHOT_MAX_EDGE as usize, SCREENSHOT_MAX_EDGE as usize));
    let capture = capture_window_image(window_id, capture_width, capture_height);
    let accessibility = collect_accessibility(window);
    if let (Err(capture_error), Err(accessibility_error)) = (&capture, &accessibility) {
        return Err((
            "capture_failed",
            format!("{capture_error} Accessibility was also unavailable: {accessibility_error}",),
        ));
    }

    let (accessibility, elements) = match accessibility {
        Ok(result) => result,
        Err(reason) => (
            json!({"available": false, "reason": reason, "elements": []}),
            Default::default(),
        ),
    };
    let point_bounds = point_bounds.unwrap_or([0, 0, capture_width as i32, capture_height as i32]);
    let accessibility_revision = accessibility_revision(&accessibility);
    let (display_width, display_height, visual, screenshots) = match capture {
        Ok(capture) => {
            let width = capture.width;
            let height = capture.height;
            // Bound the longest edge to keep payload and image-token cost
            // small while leaving desktop controls legible.
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
            let rgb = downscale_bgra_to_rgb(
                &capture.pixels,
                width,
                height,
                capture.bytes_per_row,
                capture.bytes_per_pixel,
                display_width,
                display_height,
            )?;
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
            (
                display_width as u32,
                display_height as u32,
                json!({"available": true}),
                json!([{
                    "url": format!(
                        "data:image/jpeg;base64,{}",
                        base64::engine::general_purpose::STANDARD.encode(&jpeg),
                    ),
                }]),
            )
        }
        Err(reason) => (
            0,
            0,
            json!({"available": false, "reason": reason}),
            json!([]),
        ),
    };

    let observation_id = next_id("observation");
    state.observations.insert(
        observation_id.clone(),
        Observation {
            window: window.clone(),
            bounds: point_bounds,
            display_width,
            display_height,
            accessibility_revision,
            elements,
        },
    );

    Ok(json!({
        "observation_id": observation_id,
        "window": window.to_json(),
        "viewport": {"width": display_width, "height": display_height},
        "visual": visual,
        "accessibility": accessibility,
        "screenshots": screenshots,
    }))
}

struct CapturedImage {
    width: usize,
    height: usize,
    bytes_per_row: usize,
    bytes_per_pixel: usize,
    pixels: Vec<u8>,
}

fn capture_window_image(
    window_id: u32,
    width: usize,
    height: usize,
) -> Result<CapturedImage, String> {
    let (sender, receiver) = mpsc::sync_channel(1);
    let content_handler = RcBlock::new(
        move |content: *mut SCShareableContent, content_error: *mut objc2_foundation::NSError| {
            if !content_error.is_null() {
                let _ = sender.send(Err(
                    "ScreenCaptureKit could not list capturable windows.".to_string()
                ));
                return;
            }
            let Some(content) = (unsafe { content.as_ref() }) else {
                let _ = sender.send(Err(
                    "ScreenCaptureKit returned no capturable windows.".to_string()
                ));
                return;
            };
            let windows = unsafe { content.windows() };
            let Some(target) = windows
                .iter()
                .find(|candidate| unsafe { candidate.windowID() == window_id })
            else {
                let _ = sender.send(Err(
                    "The selected window is no longer available for capture.".to_string(),
                ));
                return;
            };
            if !unsafe { target.isOnScreen() } {
                let _ = sender.send(Err(
                    "The selected window is not on the active desktop.".to_string()
                ));
                return;
            }

            let filter = unsafe {
                SCContentFilter::initWithDesktopIndependentWindow(SCContentFilter::alloc(), &target)
            };
            let configuration =
                unsafe { SCStreamConfiguration::init(SCStreamConfiguration::alloc()) };
            unsafe {
                configuration.setWidth(width);
                configuration.setHeight(height);
                configuration.setShowsCursor(false);
            }
            let image_sender = sender.clone();
            let image_handler = RcBlock::new(
                move |image: *mut objc2_core_graphics::CGImage,
                      image_error: *mut objc2_foundation::NSError| {
                    let _ = image_sender.send(captured_image_from_callback(image, image_error));
                },
            );
            unsafe {
                SCScreenshotManager::captureImageWithFilter_configuration_completionHandler(
                    &filter,
                    &configuration,
                    Some(&image_handler),
                );
            }
        },
    );

    unsafe {
        SCShareableContent::getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler(
            true,
            false,
            &content_handler,
        );
    }
    receiver
        .recv_timeout(Duration::from_secs(3))
        .map_err(|_| "ScreenCaptureKit timed out while capturing the window.".to_string())?
}

fn captured_image_from_callback(
    image: *mut objc2_core_graphics::CGImage,
    error: *mut objc2_foundation::NSError,
) -> Result<CapturedImage, String> {
    if !error.is_null() {
        return Err("ScreenCaptureKit could not capture the selected window.".to_string());
    }
    let Some(image) = (unsafe { image.as_ref() }) else {
        return Err("ScreenCaptureKit returned no window image.".to_string());
    };
    // The callback owns the lifetime of this image. Reinterpret it only for
    // the duration of the callback and copy the pixels before returning.
    let image = unsafe { &*(image as *const _ as *const CGImageRef) };
    let width = image.width();
    let height = image.height();
    let bytes_per_row = image.bytes_per_row();
    let bytes_per_pixel = image.bits_per_pixel() / 8;
    if width == 0 || height == 0 || bytes_per_pixel < 3 {
        return Err("Captured window had no usable pixels.".to_string());
    }
    let pixels = image.data().bytes().to_vec();
    Ok(CapturedImage {
        width,
        height,
        bytes_per_row,
        bytes_per_pixel,
        pixels,
    })
}

fn bounded_capture_dimensions(width: i32, height: i32) -> (usize, usize) {
    let width = width.max(1) as usize;
    let height = height.max(1) as usize;
    let longest = width.max(height) as u32;
    if longest <= SCREENSHOT_MAX_EDGE {
        return (width, height);
    }
    let scale = SCREENSHOT_MAX_EDGE as f64 / longest as f64;
    (
        ((width as f64 * scale).round() as usize).max(1),
        ((height as f64 * scale).round() as usize).max(1),
    )
}

fn downscale_bgra_to_rgb(
    raw: &[u8],
    width: usize,
    height: usize,
    bytes_per_row: usize,
    bytes_per_pixel: usize,
    display_width: usize,
    display_height: usize,
) -> Result<Vec<u8>, (&'static str, String)> {
    let expected = bytes_per_row.checked_mul(height).ok_or((
        "capture_failed",
        "Captured window dimensions overflowed.".to_string(),
    ))?;
    if bytes_per_pixel < 3 || raw.len() < expected {
        return Err((
            "capture_failed",
            "Captured window pixel data was incomplete.".to_string(),
        ));
    }

    let mut rgb = Vec::with_capacity(display_width * display_height * 3);
    for out_y in 0..display_height {
        let src_y = (out_y * height / display_height).min(height - 1);
        let row = src_y * bytes_per_row;
        for out_x in 0..display_width {
            let src_x = (out_x * width / display_width).min(width - 1);
            let offset = row + src_x * bytes_per_pixel;
            rgb.extend_from_slice(&[raw[offset + 2], raw[offset + 1], raw[offset]]);
        }
    }
    Ok(rgb)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn downscales_bgra_to_rgb() {
        let raw = [
            1, 2, 3, 255, 4, 5, 6, 255, // first row
            7, 8, 9, 255, 10, 11, 12, 255, // second row
        ];

        assert_eq!(
            downscale_bgra_to_rgb(&raw, 2, 2, 8, 4, 1, 1).expect("valid source pixels"),
            vec![3, 2, 1]
        );
    }

    #[test]
    fn rejects_incomplete_pixel_data() {
        let error = downscale_bgra_to_rgb(&[1, 2, 3], 1, 1, 4, 4, 1, 1)
            .expect_err("incomplete source pixels must fail");

        assert_eq!(error.0, "capture_failed");
    }

    #[test]
    fn limits_capture_dimensions_proportionally() {
        assert_eq!(bounded_capture_dimensions(3200, 1600), (1600, 800));
    }
}
