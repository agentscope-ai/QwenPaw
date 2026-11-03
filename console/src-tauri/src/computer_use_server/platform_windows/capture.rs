//! Window screenshot capture, bounding, and JPEG encoding.

use base64::Engine;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::time::Duration;
use windows::core::HSTRING;
use windows::Foundation::{PropertyType, PropertyValue};
use windows::Graphics::Imaging::{
    BitmapAlphaMode, BitmapEncoder, BitmapInterpolationMode, BitmapPixelFormat, BitmapPropertySet,
    BitmapTypedValue,
};
use windows::Storage::Streams::{DataReader, InMemoryRandomAccessStream};
use windows::Win32::Foundation::HWND;

use super::super::state::{
    accessibility_revision, next_id, Observation, ScreenshotTarget, ServerState, WindowInfo,
    BMP_HEADER_BYTES, SCREENSHOT_JPEG_QUALITY, SCREENSHOT_MAX_EDGE,
};
use super::uia::collect_accessibility;
use super::wgc::{capture_window, CaptureArgs, CaptureInfo};
use super::window::{get_visible_window_rect, observation_windows};

struct WindowCapture {
    hwnd: isize,
    kind: &'static str,
    z_index: i32,
    result: Result<CaptureInfo, String>,
}

struct CaptureParts {
    visual: Value,
    screenshots: Value,
    targets: HashMap<String, ScreenshotTarget>,
    viewport: (u32, u32),
}

pub(crate) fn observe_window(
    state: &mut ServerState,
    window: &WindowInfo,
    include_screenshot: bool,
) -> Result<Value, (&'static str, String)> {
    let windows = observation_windows(window);
    let observation_id = next_id("observation");
    let mut captures = Vec::new();
    if include_screenshot {
        captures.push(WindowCapture {
            hwnd: window.hwnd,
            kind: "main",
            z_index: 0,
            result: capture_window(CaptureArgs {
                hwnd: window.hwnd,
                timeout: Duration::from_millis(2500),
            }),
        });
        for (index, hwnd) in windows.related.iter().enumerate() {
            captures.push(WindowCapture {
                hwnd: *hwnd,
                kind: "transient",
                z_index: (index + 1) as i32,
                result: capture_window(CaptureArgs {
                    hwnd: *hwnd,
                    timeout: Duration::from_millis(1200),
                }),
            });
        }
    }
    let accessibility = collect_accessibility(windows.input_hwnd);
    require_observation_source(include_screenshot, &captures, &accessibility)?;
    let (accessibility, elements) = match accessibility {
        Ok(result) => result,
        Err(message) => (
            json!({"available": false, "reason": message, "elements": []}),
            Default::default(),
        ),
    };
    let accessibility_revision = accessibility_revision(&accessibility);
    let window_bounds = get_visible_window_rect(HWND(window.hwnd as _))
        .map(rect_bounds)
        .unwrap_or_default();
    let capture = capture_parts(include_screenshot, captures, windows.related.len());
    state.observations.insert(
        observation_id.clone(),
        Observation {
            window: window.clone(),
            window_bounds,
            screenshots: capture.targets,
            input_hwnd: windows.input_hwnd,
            accessibility_revision,
            elements,
        },
    );
    Ok(json!({
        "observation_id": observation_id,
        "window": window.to_json(),
        "viewport": {"width": capture.viewport.0, "height": capture.viewport.1},
        "visual": capture.visual,
        "accessibility": accessibility,
        "screenshots": capture.screenshots,
    }))
}

fn require_observation_source<A>(
    include_screenshot: bool,
    captures: &[WindowCapture],
    accessibility: &Result<A, String>,
) -> Result<(), (&'static str, String)> {
    if !include_screenshot
        || captures.iter().any(|capture| capture.result.is_ok())
        || accessibility.is_ok()
    {
        return Ok(());
    }
    let capture_error = captures
        .iter()
        .filter_map(|capture| capture.result.as_ref().err())
        .next()
        .cloned()
        .unwrap_or_else(|| "Screenshot capture was not requested.".to_string());
    let accessibility_error = accessibility
        .as_ref()
        .err()
        .cloned()
        .unwrap_or_else(|| "Accessibility text was unavailable.".to_string());
    Err((
        "capture_failed",
        format!("{capture_error} Accessibility was also unavailable: {accessibility_error}"),
    ))
}

fn capture_parts(
    requested: bool,
    captures: Vec<WindowCapture>,
    related_surface_count: usize,
) -> CaptureParts {
    let failure = captures
        .iter()
        .find_map(|capture| capture.result.as_ref().err())
        .cloned();
    let mut screenshots = Vec::new();
    let mut targets = HashMap::new();
    let mut viewport = (0, 0);
    for capture in captures {
        let Ok(result) = capture.result else { continue };
        let screenshot_id = next_id("screenshot");
        let (target, screenshot) = captured_parts(
            result,
            capture.hwnd,
            &screenshot_id,
            capture.kind,
            capture.z_index,
        );
        if capture.kind == "main" {
            viewport = (target.display_width, target.display_height);
        }
        targets.insert(screenshot_id, target);
        screenshots.push(screenshot);
    }
    let visual = if !requested {
        json!({
            "available": false,
            "requested": false,
            "related_surface_count": related_surface_count,
        })
    } else if screenshots.is_empty() {
        json!({"available": false, "reason": failure.unwrap_or_else(|| "No window image was captured.".to_string())})
    } else {
        json!({"available": true})
    };
    CaptureParts {
        visual,
        screenshots: Value::Array(screenshots),
        targets,
        viewport,
    }
}

fn captured_parts(
    capture: CaptureInfo,
    hwnd: isize,
    screenshot_id: &str,
    kind: &str,
    z_index: i32,
) -> (ScreenshotTarget, Value) {
    let [left, top, right, bottom] = capture.window_rect;
    let bounds = [left, top, right - left, bottom - top];
    let (display_width, display_height) = bounded_dimensions(capture.width, capture.height);
    let bytes = capture.bitmap;
    let (media_type, image_bytes) = match encode_screenshot_jpeg(
        &bytes,
        capture.width,
        capture.height,
        display_width,
        display_height,
    ) {
        Ok(jpeg) => ("image/jpeg", jpeg),
        Err(error) => {
            // Keep the turn alive with the raw bitmap if re-encoding
            // fails; the payload is larger but still valid.
            eprintln!("Computer Use screenshot JPEG encoding failed: {error}");
            ("image/bmp", bytes)
        }
    };
    let target = ScreenshotTarget {
        hwnd,
        bounds,
        display_width,
        display_height,
    };
    let screenshot = json!({
        "id": screenshot_id,
        "url": format!(
            "data:{media_type};base64,{}",
            base64::engine::general_purpose::STANDARD.encode(image_bytes),
        ),
        "origin_x": bounds[0],
        "origin_y": bounds[1],
        "width": display_width,
        "height": display_height,
        "z_index": z_index,
        "kind": kind,
    });
    (target, screenshot)
}

fn rect_bounds(rect: windows::Win32::Foundation::RECT) -> [i32; 4] {
    [
        rect.left,
        rect.top,
        rect.right - rect.left,
        rect.bottom - rect.top,
    ]
}

/// Compute the delivered screenshot size, downscaling proportionally when
/// the longest edge exceeds [`SCREENSHOT_MAX_EDGE`]. Smaller captures are
/// returned unchanged so the common case keeps full fidelity.
fn bounded_dimensions(width: u32, height: u32) -> (u32, u32) {
    let longest = width.max(height);
    if longest <= SCREENSHOT_MAX_EDGE || longest == 0 {
        return (width, height);
    }
    let scale = f64::from(SCREENSHOT_MAX_EDGE) / f64::from(longest);
    let scaled_w = ((f64::from(width) * scale).round() as u32).max(1);
    let scaled_h = ((f64::from(height) * scale).round() as u32).max(1);
    (scaled_w, scaled_h)
}

/// Re-encode a raw 32bpp window capture as JPEG through the Windows
/// imaging pipeline (`Windows.Graphics.Imaging.BitmapEncoder`), scaling
/// the source to the requested delivery size when they differ.
fn encode_screenshot_jpeg(
    bmp: &[u8],
    width: u32,
    height: u32,
    dst_width: u32,
    dst_height: u32,
) -> Result<Vec<u8>, String> {
    let pixel_len = (width as usize)
        .checked_mul(height as usize)
        .and_then(|value| value.checked_mul(4))
        .ok_or_else(|| "capture pixel size overflow".to_string())?;
    let pixels = bmp
        .get(BMP_HEADER_BYTES..BMP_HEADER_BYTES + pixel_len)
        .ok_or_else(|| "capture file is smaller than its header claims".to_string())?;
    let stream = InMemoryRandomAccessStream::new()
        .map_err(|error| format!("create in-memory stream: {error}"))?;
    let quality_value = PropertyValue::CreateSingle(SCREENSHOT_JPEG_QUALITY)
        .map_err(|error| format!("create quality value: {error}"))?;
    let quality = BitmapTypedValue::Create(&quality_value, PropertyType::Single)
        .map_err(|error| format!("wrap quality value: {error}"))?;
    let options =
        BitmapPropertySet::new().map_err(|error| format!("create encoder options: {error}"))?;
    options
        .Insert(&HSTRING::from("ImageQuality"), &quality)
        .map_err(|error| format!("set encoder quality: {error}"))?;
    let encoder_id = BitmapEncoder::JpegEncoderId()
        .map_err(|error| format!("resolve JPEG encoder id: {error}"))?;
    let encoder = BitmapEncoder::CreateWithEncodingOptionsAsync(encoder_id, &stream, &options)
        .map_err(|error| format!("create JPEG encoder: {error}"))?
        .get()
        .map_err(|error| format!("create JPEG encoder: {error}"))?;
    encoder
        .SetPixelData(
            BitmapPixelFormat::Bgra8,
            BitmapAlphaMode::Ignore,
            width,
            height,
            96.0,
            96.0,
            pixels,
        )
        .map_err(|error| format!("set encoder pixel data: {error}"))?;
    // Scale the encoded output to the delivery size. Setting the transform
    // to the source size is a no-op, so this is safe when no downscaling is
    // required.
    if dst_width != width || dst_height != height {
        let transform = encoder
            .BitmapTransform()
            .map_err(|error| format!("read encoder transform: {error}"))?;
        transform
            .SetScaledWidth(dst_width)
            .map_err(|error| format!("set scaled width: {error}"))?;
        transform
            .SetScaledHeight(dst_height)
            .map_err(|error| format!("set scaled height: {error}"))?;
        transform
            .SetInterpolationMode(BitmapInterpolationMode::Fant)
            .map_err(|error| format!("set interpolation mode: {error}"))?;
    }
    encoder
        .FlushAsync()
        .map_err(|error| format!("flush JPEG encoder: {error}"))?
        .get()
        .map_err(|error| format!("flush JPEG encoder: {error}"))?;
    let size = stream
        .Size()
        .map_err(|error| format!("read encoded stream size: {error}"))?;
    let input = stream
        .GetInputStreamAt(0)
        .map_err(|error| format!("open encoded stream: {error}"))?;
    let reader = DataReader::CreateDataReader(&input)
        .map_err(|error| format!("create stream reader: {error}"))?;
    reader
        .LoadAsync(size as u32)
        .map_err(|error| format!("load encoded stream: {error}"))?
        .get()
        .map_err(|error| format!("load encoded stream: {error}"))?;
    let mut encoded = vec![0u8; size as usize];
    reader
        .ReadBytes(&mut encoded)
        .map_err(|error| format!("read encoded stream: {error}"))?;
    Ok(encoded)
}

#[cfg(test)]
mod tests {
    use super::{capture_parts, require_observation_source};

    #[test]
    fn accessibility_keeps_an_observation_alive_when_capture_fails() {
        let captures = vec![super::WindowCapture {
            hwnd: 1,
            kind: "main",
            z_index: 0,
            result: Err("capture unavailable".to_string()),
        }];
        let accessibility: Result<(), String> = Ok(());

        require_observation_source(true, &captures, &accessibility)
            .expect("accessibility-only observations must remain usable");
    }

    #[test]
    fn observation_fails_when_both_sources_fail() {
        let captures = vec![super::WindowCapture {
            hwnd: 1,
            kind: "main",
            z_index: 0,
            result: Err("capture unavailable".to_string()),
        }];
        let accessibility: Result<(), String> = Err("UIA unavailable".to_string());

        let error = require_observation_source(true, &captures, &accessibility)
            .expect_err("an observation needs at least one source");
        assert_eq!(error.0, "capture_failed");
        assert!(error.1.contains("capture unavailable"));
        assert!(error.1.contains("UIA unavailable"));
    }

    #[test]
    fn lightweight_refresh_does_not_require_an_image() {
        let accessibility: Result<(), String> = Err("UIA unavailable".to_string());

        require_observation_source(false, &[], &accessibility)
            .expect("the caller can request a full observation next");
    }

    #[test]
    fn lightweight_refresh_reports_related_surfaces_without_images() {
        let parts = capture_parts(false, Vec::new(), 2);

        assert_eq!(parts.visual["requested"], false);
        assert_eq!(parts.visual["related_surface_count"], 2);
        assert!(parts.screenshots.as_array().unwrap().is_empty());
        assert!(parts.targets.is_empty());
    }
}
