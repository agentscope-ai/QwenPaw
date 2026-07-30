//! Window screenshot capture, bounding, and JPEG encoding.

use base64::Engine;
use serde_json::{json, Value};
use std::time::Duration;
use windows::core::HSTRING;
use windows::Foundation::{PropertyType, PropertyValue};
use windows::Graphics::Imaging::{
    BitmapAlphaMode, BitmapEncoder, BitmapInterpolationMode, BitmapPixelFormat, BitmapPropertySet,
    BitmapTypedValue,
};
use windows::Storage::Streams::{DataReader, InMemoryRandomAccessStream};

use super::super::state::{
    next_id, Observation, ServerState, WindowInfo, BMP_HEADER_BYTES, SCREENSHOT_JPEG_QUALITY,
    SCREENSHOT_MAX_EDGE,
};
use super::uia::collect_accessibility;
use super::wgc::{capture_window, CaptureArgs};

pub(crate) fn observe_window(
    state: &mut ServerState,
    window: &WindowInfo,
) -> Result<Value, (&'static str, String)> {
    let observation_id = next_id("observation");
    let capture = capture_window(CaptureArgs {
        hwnd: window.hwnd,
        timeout: Duration::from_millis(2500),
    })
    .map_err(|error| ("capture_failed", error))?;
    let bytes = capture.bitmap;
    let (display_width, display_height) = bounded_dimensions(capture.width, capture.height);
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
    // Observations record origin plus size, while the capture reports edges.
    let [left, top, right, bottom] = capture.window_rect;
    let bounds = [left, top, right - left, bottom - top];
    let (accessibility, elements) = match collect_accessibility(window) {
        Ok((description, elements)) => (description, elements),
        Err(message) => (
            json!({"available": false, "reason": message, "elements": []}),
            Default::default(),
        ),
    };
    state.observations.insert(
        observation_id.clone(),
        Observation {
            window: window.clone(),
            bounds,
            display_width,
            display_height,
            elements,
        },
    );
    Ok(json!({
        "observation_id": observation_id,
        "window": window.to_json(),
        "viewport": {"width": display_width, "height": display_height},
        "accessibility": accessibility,
        "screenshots": [{
            "url": format!(
                "data:{media_type};base64,{}",
                base64::engine::general_purpose::STANDARD.encode(image_bytes),
            ),
            "origin_x": bounds[0],
            "origin_y": bounds[1],
            "width": display_width,
            "height": display_height,
            "z_index": 0,
            "kind": "main",
        }],
    }))
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
