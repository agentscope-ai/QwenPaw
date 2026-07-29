//! Getting window pixels out of Windows.
//!
//! Windows.Graphics.Capture asks the compositor for a frame, so a window that
//! is partly covered still captures correctly -- which older paths like
//! `PrintWindow` cannot promise. The frame arrives as a Direct3D 11 texture, so
//! it is copied into a staging texture, read back, and written as a bitmap for
//! the capture layer above to encode.
//!
//! This is the Windows counterpart to what `platform_macos::capture` does with
//! CoreGraphics, and it sits here for the same reason: it is an OS call, and the
//! layers above it name no platform API. It lived in the helper binary until the
//! server ended up importing it back out of its own entry point.

use std::io::Write;
use std::thread::sleep;
use std::time::{Duration, Instant};

use windows::core::{factory, Interface};
use windows::Graphics::Capture::{
    Direct3D11CaptureFrame, Direct3D11CaptureFramePool, GraphicsCaptureItem,
};
use windows::Graphics::DirectX::Direct3D11::IDirect3DDevice;
use windows::Graphics::DirectX::DirectXPixelFormat;
use windows::Win32::Foundation::{HMODULE, HWND, RECT};
use windows::Win32::Graphics::Direct3D::{
    D3D_DRIVER_TYPE, D3D_DRIVER_TYPE_HARDWARE, D3D_DRIVER_TYPE_WARP, D3D_FEATURE_LEVEL,
    D3D_FEATURE_LEVEL_11_0, D3D_FEATURE_LEVEL_11_1,
};
use windows::Win32::Graphics::Direct3D11::{
    D3D11CreateDevice, ID3D11Device, ID3D11DeviceContext, ID3D11Resource, ID3D11Texture2D,
    D3D11_CPU_ACCESS_READ, D3D11_CREATE_DEVICE_BGRA_SUPPORT, D3D11_MAPPED_SUBRESOURCE,
    D3D11_MAP_READ, D3D11_SDK_VERSION, D3D11_TEXTURE2D_DESC, D3D11_USAGE_STAGING,
};
use windows::Win32::Graphics::Dxgi::Common::DXGI_SAMPLE_DESC;
use windows::Win32::Graphics::Dxgi::{IDXGIAdapter, IDXGIDevice};
use windows::Win32::System::WinRT::Direct3D11::{
    CreateDirect3D11DeviceFromDXGIDevice, IDirect3DDxgiInterfaceAccess,
};
use windows::Win32::System::WinRT::Graphics::Capture::IGraphicsCaptureItemInterop;
use windows::Win32::System::WinRT::{RoInitialize, RoUninitialize, RO_INIT_MULTITHREADED};
use windows::Win32::UI::HiDpi::{
    SetProcessDpiAwarenessContext, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2,
};
use windows::Win32::UI::WindowsAndMessaging::{IsIconic, IsWindow};

use super::window::get_visible_window_rect;

#[derive(Debug)]
pub(super) struct CaptureArgs {
    pub(super) hwnd: isize,
    pub(super) timeout: Duration,
}

#[derive(Debug)]
pub(super) struct CaptureInfo {
    /// The frame as a 32bpp top-down bitmap, header included.
    pub(super) bitmap: Vec<u8>,
    pub(super) width: u32,
    pub(super) height: u32,
    pub(super) window_rect: [i32; 4],
}

pub(super) fn capture_window(args: CaptureArgs) -> Result<CaptureInfo, String> {
    unsafe {
        let _ = SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    }
    unsafe {
        RoInitialize(RO_INIT_MULTITHREADED)
            .map_err(|err| format!("RoInitialize failed: {err}"))?;
    }
    let result = capture_window_inner(args);
    unsafe {
        RoUninitialize();
    }
    result
}

fn capture_window_inner(args: CaptureArgs) -> Result<CaptureInfo, String> {
    let hwnd = HWND(args.hwnd as _);
    if !unsafe { IsWindow(Some(hwnd)).as_bool() } {
        return Err(format!("invalid hwnd: {}", args.hwnd));
    }
    if unsafe { IsIconic(hwnd).as_bool() } {
        // A minimized window produces no frames, so the capture loop would
        // otherwise spin until the timeout. Fail fast with an actionable
        // reason instead.
        return Err("target window is minimized; restore it before capture".to_string());
    }

    let window_rect = get_visible_window_rect(hwnd)?;
    let (device, context) = create_d3d_device()?;
    let winrt_device = create_winrt_device(&device)?;
    let item = create_capture_item(hwnd)?;
    let size = item
        .Size()
        .map_err(|err| format!("GraphicsCaptureItem.Size failed: {err}"))?;
    if size.Width <= 0 || size.Height <= 0 {
        return Err(format!(
            "invalid capture size: {}x{}",
            size.Width, size.Height
        ));
    }

    let frame_pool = Direct3D11CaptureFramePool::CreateFreeThreaded(
        &winrt_device,
        DirectXPixelFormat::B8G8R8A8UIntNormalized,
        1,
        size,
    )
    .map_err(|err| format!("CreateFreeThreaded failed: {err}"))?;
    let session = frame_pool
        .CreateCaptureSession(&item)
        .map_err(|err| format!("CreateCaptureSession failed: {err}"))?;
    let _ = session.SetIsCursorCaptureEnabled(false);
    session
        .StartCapture()
        .map_err(|err| format!("StartCapture failed: {err}"))?;

    let frame = wait_for_frame(&frame_pool, args.timeout)?;
    let (bitmap, width, height) = frame_to_bitmap(&device, &context, &frame)?;

    Ok(CaptureInfo {
        bitmap,
        width,
        height,
        window_rect: rect_to_array(window_rect),
    })
}

fn create_d3d_device() -> Result<(ID3D11Device, ID3D11DeviceContext), String> {
    const LEVELS: [D3D_FEATURE_LEVEL; 2] = [D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0];
    let mut last_error = String::new();

    for driver in [D3D_DRIVER_TYPE_HARDWARE, D3D_DRIVER_TYPE_WARP] {
        match create_d3d_device_with_driver(driver, &LEVELS) {
            Ok(pair) => return Ok(pair),
            Err(error) => last_error = error,
        }
    }

    Err(format!("D3D11CreateDevice failed: {last_error}"))
}

fn create_d3d_device_with_driver(
    driver: D3D_DRIVER_TYPE,
    levels: &[D3D_FEATURE_LEVEL],
) -> Result<(ID3D11Device, ID3D11DeviceContext), String> {
    let mut device = None;
    let mut context = None;
    let mut selected_level = D3D_FEATURE_LEVEL_11_0;

    unsafe {
        D3D11CreateDevice(
            None::<&IDXGIAdapter>,
            driver,
            HMODULE::default(),
            D3D11_CREATE_DEVICE_BGRA_SUPPORT,
            Some(levels),
            D3D11_SDK_VERSION,
            Some(&mut device),
            Some(&mut selected_level),
            Some(&mut context),
        )
    }
    .map_err(|err| format!("{driver:?}: {err}"))?;

    let device = device.ok_or_else(|| "D3D11 device was not returned".to_string())?;
    let context = context.ok_or_else(|| "D3D11 context was not returned".to_string())?;
    Ok((device, context))
}

fn create_winrt_device(device: &ID3D11Device) -> Result<IDirect3DDevice, String> {
    let dxgi_device: IDXGIDevice = device
        .cast()
        .map_err(|err| format!("ID3D11Device -> IDXGIDevice failed: {err}"))?;
    let inspectable = unsafe { CreateDirect3D11DeviceFromDXGIDevice(&dxgi_device) }
        .map_err(|err| format!("CreateDirect3D11DeviceFromDXGIDevice failed: {err}"))?;
    inspectable
        .cast()
        .map_err(|err| format!("IInspectable -> IDirect3DDevice failed: {err}"))
}

fn create_capture_item(hwnd: HWND) -> Result<GraphicsCaptureItem, String> {
    let interop: IGraphicsCaptureItemInterop =
        factory::<GraphicsCaptureItem, IGraphicsCaptureItemInterop>()
            .map_err(|err| format!("GraphicsCaptureItem factory failed: {err}"))?;
    unsafe { interop.CreateForWindow(hwnd) }
        .map_err(|err| format!("CreateForWindow failed: {err}"))
}

fn wait_for_frame(
    frame_pool: &Direct3D11CaptureFramePool,
    timeout: Duration,
) -> Result<Direct3D11CaptureFrame, String> {
    let started = Instant::now();
    loop {
        match frame_pool.TryGetNextFrame() {
            Ok(frame) => return Ok(frame),
            Err(err) => {
                // A not-yet-ready frame surfaces here as a success-coded
                // (S_OK) error, which just means no frame has arrived yet.
                // Any other HRESULT is a genuine capture failure and must
                // stop the wait rather than be reported as a timeout.
                if !err.code().is_ok() {
                    return Err(format!("WGC frame acquisition failed: {err}"));
                }
            }
        }

        if started.elapsed() >= timeout {
            return Err(format!(
                "timed out after {}ms waiting for a WGC frame; the target window may be minimized or not rendering",
                timeout.as_millis()
            ));
        }

        sleep(Duration::from_millis(16));
    }
}

/// Read the captured frame back from the GPU as a 32bpp top-down bitmap.
///
/// The bytes are returned rather than written anywhere: the caller encodes them
/// as JPEG. They used to go to a temporary file, which was how a command-line
/// capture handed its result back -- a round trip through disk that a window on
/// a large display made expensive, for a buffer the next line reads again.
fn frame_to_bitmap(
    device: &ID3D11Device,
    context: &ID3D11DeviceContext,
    frame: &Direct3D11CaptureFrame,
) -> Result<(Vec<u8>, u32, u32), String> {
    let surface = frame
        .Surface()
        .map_err(|err| format!("frame.Surface failed: {err}"))?;
    let access: IDirect3DDxgiInterfaceAccess = surface
        .cast()
        .map_err(|err| format!("surface cast failed: {err}"))?;
    let texture: ID3D11Texture2D = unsafe { access.GetInterface() }
        .map_err(|err| format!("surface texture access failed: {err}"))?;

    let mut desc = D3D11_TEXTURE2D_DESC::default();
    unsafe {
        texture.GetDesc(&mut desc);
    }
    if desc.Width == 0 || desc.Height == 0 {
        return Err("captured texture has zero size".to_string());
    }

    let mut staging_desc = desc;
    staging_desc.BindFlags = 0;
    staging_desc.MiscFlags = 0;
    staging_desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ.0 as u32;
    staging_desc.Usage = D3D11_USAGE_STAGING;
    staging_desc.SampleDesc = DXGI_SAMPLE_DESC {
        Count: 1,
        Quality: 0,
    };

    let mut staging = None;
    unsafe {
        device
            .CreateTexture2D(&staging_desc, None, Some(&mut staging))
            .map_err(|err| format!("CreateTexture2D staging failed: {err}"))?;
    }
    let staging = staging.ok_or_else(|| "staging texture was not returned".to_string())?;
    let staging_resource: ID3D11Resource = staging
        .cast()
        .map_err(|err| format!("staging resource cast failed: {err}"))?;
    let source_resource: ID3D11Resource = texture
        .cast()
        .map_err(|err| format!("source resource cast failed: {err}"))?;

    unsafe {
        context.CopyResource(&staging_resource, &source_resource);
    }

    let mut mapped = D3D11_MAPPED_SUBRESOURCE::default();
    unsafe {
        context
            .Map(&staging_resource, 0, D3D11_MAP_READ, 0, Some(&mut mapped))
            .map_err(|err| format!("Map staging texture failed: {err}"))?;
    }
    let write_result = write_bmp(desc.Width, desc.Height, mapped.RowPitch, mapped.pData);
    unsafe {
        context.Unmap(&staging_resource, 0);
    }
    let bitmap = write_result?;

    Ok((bitmap, desc.Width, desc.Height))
}

fn rect_to_array(rect: RECT) -> [i32; 4] {
    [rect.left, rect.top, rect.right, rect.bottom]
}

fn write_bmp(
    width: u32,
    height: u32,
    row_pitch: u32,
    data: *mut std::ffi::c_void,
) -> Result<Vec<u8>, String> {
    if data.is_null() {
        return Err("mapped texture data is null".to_string());
    }
    if width > i32::MAX as u32 || height > i32::MAX as u32 {
        return Err(format!("capture too large for BMP: {width}x{height}"));
    }

    let row_bytes = width
        .checked_mul(4)
        .ok_or_else(|| "BMP row size overflow".to_string())?;
    if row_pitch < row_bytes {
        return Err(format!("invalid row pitch {row_pitch} for width {width}"));
    }
    let pixel_bytes = row_bytes
        .checked_mul(height)
        .ok_or_else(|| "BMP pixel size overflow".to_string())?;
    let file_size = 14u32
        .checked_add(40)
        .and_then(|value| value.checked_add(pixel_bytes))
        .ok_or_else(|| "BMP file size overflow".to_string())?;

    let mut writer = Vec::with_capacity(file_size as usize);

    writer.write_all(b"BM").map_err(|err| err.to_string())?;
    write_u32(&mut writer, file_size)?;
    write_u16(&mut writer, 0)?;
    write_u16(&mut writer, 0)?;
    write_u32(&mut writer, 54)?;
    write_u32(&mut writer, 40)?;
    write_i32(&mut writer, width as i32)?;
    // A negative height declares a top-down DIB, which is the row order
    // Windows Graphics Capture hands us; a positive one would mean the
    // bottom-up order BMP defaults to and flip the image.
    write_i32(&mut writer, -(height as i32))?;
    write_u16(&mut writer, 1)?;
    write_u16(&mut writer, 32)?;
    write_u32(&mut writer, 0)?;
    write_u32(&mut writer, pixel_bytes)?;
    write_i32(&mut writer, 2835)?;
    write_i32(&mut writer, 2835)?;
    write_u32(&mut writer, 0)?;
    write_u32(&mut writer, 0)?;

    let base = data as *const u8;
    let row_len = row_bytes as usize;
    for y in 0..height as usize {
        let row =
            unsafe { std::slice::from_raw_parts(base.add(y * row_pitch as usize), row_len) };
        writer.write_all(row).map_err(|err| err.to_string())?;
    }
    Ok(writer)
}

fn write_u16(writer: &mut impl Write, value: u16) -> Result<(), String> {
    writer
        .write_all(&value.to_le_bytes())
        .map_err(|err| err.to_string())
}

fn write_u32(writer: &mut impl Write, value: u32) -> Result<(), String> {
    writer
        .write_all(&value.to_le_bytes())
        .map_err(|err| err.to_string())
}

fn write_i32(writer: &mut impl Write, value: i32) -> Result<(), String> {
    writer
        .write_all(&value.to_le_bytes())
        .map_err(|err| err.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Build a mapped-texture stand-in: `height` rows of `row_pitch` bytes, of
    /// which the first `width * 4` carry pixels, mirroring how Direct3D hands
    /// back a staging texture whose rows are padded to a hardware stride.
    fn mapped_rows(width: u32, height: u32, row_pitch: u32) -> Vec<u8> {
        let mut buffer = vec![0_u8; (row_pitch * height) as usize];
        for row in 0..height {
            for column in 0..width * 4 {
                let index = (row * row_pitch + column) as usize;
                // A value that identifies its row, so a stride mistake shows up
                // as pixels from the wrong row rather than as plausible noise.
                buffer[index] = (row * 16 + column) as u8;
            }
        }
        buffer
    }

    #[test]
    fn the_header_describes_a_top_down_32bpp_bitmap() {
        let mut rows = mapped_rows(2, 2, 8);
        let bitmap = write_bmp(2, 2, 8, rows.as_mut_ptr().cast()).expect("bitmap");

        assert_eq!(&bitmap[0..2], b"BM");
        assert_eq!(u32::from_le_bytes(bitmap[2..6].try_into().unwrap()), 70);
        assert_eq!(u32::from_le_bytes(bitmap[10..14].try_into().unwrap()), 54);
        assert_eq!(u32::from_le_bytes(bitmap[14..18].try_into().unwrap()), 40);
        assert_eq!(i32::from_le_bytes(bitmap[18..22].try_into().unwrap()), 2);
        // Negative height means the rows are stored top-down, which is the
        // order the compositor delivers them; a positive one would flip the
        // image and every mapped coordinate with it.
        assert_eq!(i32::from_le_bytes(bitmap[22..26].try_into().unwrap()), -2);
        assert_eq!(u16::from_le_bytes(bitmap[28..30].try_into().unwrap()), 32);
        assert_eq!(bitmap.len(), 54 + 16);
    }

    #[test]
    fn padded_rows_are_read_without_their_padding() {
        // A stride wider than the pixels is the normal case, not an edge one.
        let mut rows = mapped_rows(2, 2, 12);
        let bitmap = write_bmp(2, 2, 12, rows.as_mut_ptr().cast()).expect("bitmap");

        assert_eq!(bitmap.len(), 54 + 16);
        let pixels = &bitmap[54..];
        assert_eq!(pixels[0..8], [0, 1, 2, 3, 4, 5, 6, 7]);
        // Row one starts at 16 in the generator, so reading it as 12 would mean
        // the padding was copied instead of skipped.
        assert_eq!(pixels[8..16], [16, 17, 18, 19, 20, 21, 22, 23]);
    }

    #[test]
    fn a_stride_narrower_than_the_pixels_is_refused() {
        let mut rows = mapped_rows(2, 1, 8);
        let error = write_bmp(2, 1, 4, rows.as_mut_ptr().cast()).expect_err("must refuse");
        assert!(error.contains("row pitch"), "{error}");
    }

    #[test]
    fn a_null_mapping_is_refused() {
        let error = write_bmp(2, 2, 8, std::ptr::null_mut()).expect_err("must refuse");
        assert!(error.contains("null"), "{error}");
    }
}
