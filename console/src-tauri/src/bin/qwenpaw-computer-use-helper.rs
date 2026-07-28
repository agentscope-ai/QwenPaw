#[cfg(not(any(windows, target_os = "macos")))]
fn main() {
    eprintln!("qwenpaw-computer-use-helper is only supported on Windows and macOS");
    std::process::exit(2);
}

// On macOS the helper only serves the RPC protocol: screen capture is part of
// the shared server there rather than a separate capture mode, so there is no
// command-line capture entry point to parse.
//
// The server is attached at file scope rather than inside a module the way the
// Windows entry point does it. A `#[path]` inside an inline module resolves
// through a directory named after that module, and since no such directory
// exists, Unix cannot walk `..` out of it -- only Windows folds those segments
// away without touching the filesystem.
#[cfg(target_os = "macos")]
#[path = "../computer_use_server/mod.rs"]
mod computer_use_server;

#[cfg(target_os = "macos")]
fn main() {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    if !args.first().is_some_and(|value| value == "serve") {
        eprintln!("usage: qwenpaw-computer-use-helper serve <endpoint> <capability>");
        std::process::exit(2);
    }
    if let Err(error) = computer_use_server::run(&args[1..]) {
        eprintln!("Computer Use helper failed: {error}");
        std::process::exit(2);
    }
}

#[cfg(windows)]
fn main() {
    windows_app::main();
}

#[cfg(windows)]
mod windows_app {
    use serde::Serialize;
    use serde_json::json;
    use std::env;
    use std::fs::File;
    use std::io::{BufWriter, Write};
    use std::path::{Path, PathBuf};
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
    use windows::Win32::Graphics::Dwm::{DwmGetWindowAttribute, DWMWA_EXTENDED_FRAME_BOUNDS};
    use windows::Win32::Graphics::Dxgi::Common::DXGI_SAMPLE_DESC;
    use windows::Win32::Graphics::Dxgi::{IDXGIAdapter, IDXGIDevice};
    use windows::Win32::Graphics::Gdi::{GetMonitorInfoW, HMONITOR, MONITORINFO};
    use windows::Win32::System::WinRT::Direct3D11::{
        CreateDirect3D11DeviceFromDXGIDevice, IDirect3DDxgiInterfaceAccess,
    };
    use windows::Win32::System::WinRT::Graphics::Capture::IGraphicsCaptureItemInterop;
    use windows::Win32::System::WinRT::{RoInitialize, RoUninitialize, RO_INIT_MULTITHREADED};
    use windows::Win32::UI::HiDpi::{
        SetProcessDpiAwarenessContext, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2,
    };
    use windows::Win32::UI::WindowsAndMessaging::{GetWindowRect, IsIconic, IsWindow};

    #[derive(Debug)]
    struct CaptureArgs {
        hwnd: isize,
        out: PathBuf,
        timeout: Duration,
    }

    #[derive(Debug)]
    struct MonitorArgs {
        handle: isize,
        out: PathBuf,
        timeout: Duration,
    }

    #[derive(Debug)]
    enum Command {
        Window(CaptureArgs),
        Monitor(MonitorArgs),
    }

    #[derive(Serialize)]
    struct CaptureInfo {
        ok: bool,
        method: &'static str,
        hwnd: isize,
        path: String,
        width: u32,
        height: u32,
        window_rect: [i32; 4],
    }

    #[derive(Serialize)]
    struct MonitorInfo {
        ok: bool,
        method: &'static str,
        handle: isize,
        path: String,
        width: u32,
        height: u32,
        monitor_rect: [i32; 4],
    }

    pub fn main() {
        let args = env::args().skip(1).collect::<Vec<_>>();
        if args.first().is_some_and(|value| value == "serve") {
            if let Err(error) = computer_use_server::run(&args[1..]) {
                eprintln!("Computer Use helper failed: {error}");
                std::process::exit(2);
            }
            return;
        }
        let result = parse_args().and_then(|command| match command {
            Command::Window(args) => capture_window(args)
                .and_then(|info| serde_json::to_string(&info).map_err(|err| err.to_string())),
            Command::Monitor(args) => capture_monitor(args)
                .and_then(|info| serde_json::to_string(&info).map_err(|err| err.to_string())),
        });
        match result {
            Ok(json_line) => {
                println!("{json_line}");
            }
            Err(error) => {
                println!(
                    "{}",
                    json!({
                        "ok": false,
                        "method": "wgc",
                        "error": error,
                    })
                );
                std::process::exit(2);
            }
        }
    }

    fn parse_args() -> Result<Command, String> {
        let mut args = env::args().skip(1);
        let command = args.next().ok_or_else(usage)?;

        let mut hwnd: Option<isize> = None;
        let mut handle: Option<isize> = None;
        let mut out: Option<PathBuf> = None;
        let mut timeout = Duration::from_millis(2500);

        while let Some(arg) = args.next() {
            match arg.as_str() {
                "--hwnd" => {
                    let value = args
                        .next()
                        .ok_or_else(|| "--hwnd requires a value".to_string())?;
                    hwnd = Some(parse_hwnd(&value)?);
                }
                "--handle" => {
                    let value = args
                        .next()
                        .ok_or_else(|| "--handle requires a value".to_string())?;
                    handle = Some(parse_hwnd(&value)?);
                }
                "--out" => {
                    let value = args
                        .next()
                        .ok_or_else(|| "--out requires a value".to_string())?;
                    out = Some(PathBuf::from(value));
                }
                "--timeout-ms" => {
                    let value = args
                        .next()
                        .ok_or_else(|| "--timeout-ms requires a value".to_string())?;
                    let millis = value
                        .parse::<u64>()
                        .map_err(|_| format!("invalid --timeout-ms value: {value}"))?;
                    timeout = Duration::from_millis(millis.max(100));
                }
                _ => return Err(format!("unknown argument: {arg}")),
            }
        }

        let out = out.ok_or_else(|| "--out is required".to_string())?;
        match command.as_str() {
            "capture-window" => Ok(Command::Window(CaptureArgs {
                hwnd: hwnd.ok_or_else(|| "--hwnd is required".to_string())?,
                out,
                timeout,
            })),
            "capture-monitor" => Ok(Command::Monitor(MonitorArgs {
                handle: handle.ok_or_else(|| "--handle is required".to_string())?,
                out,
                timeout,
            })),
            _ => Err(usage()),
        }
    }

    fn usage() -> String {
        "usage: qwenpaw-computer-use-helper <capture-window --hwnd <hwnd> | capture-monitor --handle \
         <hmonitor>> --out <bmp> [--timeout-ms <ms>]"
            .to_string()
    }

    fn parse_hwnd(value: &str) -> Result<isize, String> {
        let trimmed = value.trim();
        if let Some(hex) = trimmed
            .strip_prefix("0x")
            .or_else(|| trimmed.strip_prefix("0X"))
        {
            isize::from_str_radix(hex, 16).map_err(|_| format!("invalid hwnd: {value}"))
        } else {
            trimmed
                .parse::<isize>()
                .map_err(|_| format!("invalid hwnd: {value}"))
        }
    }

    fn capture_window(args: CaptureArgs) -> Result<CaptureInfo, String> {
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
        let (width, height) = copy_frame_to_bmp(&device, &context, &frame, &args.out)?;

        Ok(CaptureInfo {
            ok: true,
            method: "wgc",
            hwnd: args.hwnd,
            path: args.out.to_string_lossy().to_string(),
            width,
            height,
            window_rect: rect_to_array(window_rect),
        })
    }

    fn capture_monitor(args: MonitorArgs) -> Result<MonitorInfo, String> {
        unsafe {
            let _ = SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
        }
        unsafe {
            RoInitialize(RO_INIT_MULTITHREADED)
                .map_err(|err| format!("RoInitialize failed: {err}"))?;
        }
        let result = capture_monitor_inner(args);
        unsafe {
            RoUninitialize();
        }
        result
    }

    fn capture_monitor_inner(args: MonitorArgs) -> Result<MonitorInfo, String> {
        let hmonitor = HMONITOR(args.handle as _);
        let monitor_rect = get_monitor_rect(hmonitor)?;
        let (device, context) = create_d3d_device()?;
        let winrt_device = create_winrt_device(&device)?;
        let item = create_capture_item_for_monitor(hmonitor)?;
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
        let (width, height) = copy_frame_to_bmp(&device, &context, &frame, &args.out)?;

        Ok(MonitorInfo {
            ok: true,
            method: "wgc",
            handle: args.handle,
            path: args.out.to_string_lossy().to_string(),
            width,
            height,
            monitor_rect: rect_to_array(monitor_rect),
        })
    }

    fn get_monitor_rect(hmonitor: HMONITOR) -> Result<RECT, String> {
        let mut info = MONITORINFO {
            cbSize: std::mem::size_of::<MONITORINFO>() as u32,
            ..Default::default()
        };
        let ok = unsafe { GetMonitorInfoW(hmonitor, &mut info) };
        if !ok.as_bool() {
            return Err(format!(
                "GetMonitorInfoW failed for handle {}",
                hmonitor.0 as isize
            ));
        }
        let rect = info.rcMonitor;
        if rect.right <= rect.left || rect.bottom <= rect.top {
            return Err("monitor rect has zero area".to_string());
        }
        Ok(rect)
    }

    fn create_capture_item_for_monitor(hmonitor: HMONITOR) -> Result<GraphicsCaptureItem, String> {
        let interop: IGraphicsCaptureItemInterop =
            factory::<GraphicsCaptureItem, IGraphicsCaptureItemInterop>()
                .map_err(|err| format!("GraphicsCaptureItem factory failed: {err}"))?;
        unsafe { interop.CreateForMonitor(hmonitor) }
            .map_err(|err| format!("CreateForMonitor failed: {err}"))
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

    fn copy_frame_to_bmp(
        device: &ID3D11Device,
        context: &ID3D11DeviceContext,
        frame: &Direct3D11CaptureFrame,
        out: &Path,
    ) -> Result<(u32, u32), String> {
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
        let write_result = write_bmp(out, desc.Width, desc.Height, mapped.RowPitch, mapped.pData);
        unsafe {
            context.Unmap(&staging_resource, 0);
        }
        write_result?;

        Ok((desc.Width, desc.Height))
    }

    fn get_visible_window_rect(hwnd: HWND) -> Result<RECT, String> {
        let mut rect = RECT::default();
        let dwm_result = unsafe {
            DwmGetWindowAttribute(
                hwnd,
                DWMWA_EXTENDED_FRAME_BOUNDS,
                &mut rect as *mut RECT as *mut _,
                std::mem::size_of::<RECT>() as u32,
            )
        };
        if dwm_result.is_ok() && rect.right > rect.left && rect.bottom > rect.top {
            return Ok(rect);
        }

        unsafe {
            GetWindowRect(hwnd, &mut rect).map_err(|err| format!("GetWindowRect failed: {err}"))?;
        }
        if rect.right <= rect.left || rect.bottom <= rect.top {
            return Err("window rect has zero area".to_string());
        }
        Ok(rect)
    }

    fn rect_to_array(rect: RECT) -> [i32; 4] {
        [rect.left, rect.top, rect.right, rect.bottom]
    }

    fn write_bmp(
        path: &Path,
        width: u32,
        height: u32,
        row_pitch: u32,
        data: *mut std::ffi::c_void,
    ) -> Result<(), String> {
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

        let file = File::create(path)
            .map_err(|err| format!("failed to create {}: {err}", path.display()))?;
        let mut writer = BufWriter::new(file);

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
        writer.flush().map_err(|err| err.to_string())
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

    #[path = "../../computer_use_server/mod.rs"]
    mod computer_use_server;
}
