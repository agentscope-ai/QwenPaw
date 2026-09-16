//! Helper-owned loader and safe owner for the bundled macOS recording shim.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

use serde_json::Value;
use tokio::sync::mpsc;

#[derive(Debug)]
pub(super) struct NativeInputEvent {
    pub(super) seq: u64,
    pub(super) event_type: u32,
    pub(super) monotonic_ns: u64,
    pub(super) source_pid: i64,
    pub(super) x: f64,
    pub(super) y: f64,
    pub(super) scroll_x: f64,
    pub(super) scroll_y: f64,
    pub(super) flags: u64,
    pub(super) key_code: u16,
    pub(super) button: i64,
    pub(super) click_count: i64,
    pub(super) foreground_pid: i64,
    pub(super) application_generation: u64,
}

struct CallbackContext {
    sender: mpsc::Sender<NativeInputEvent>,
    next_seq: Arc<AtomicU64>,
    host_pid: i64,
}

pub(super) struct NativeInputSource {
    #[cfg(target_os = "macos")]
    raw: *mut std::ffi::c_void,
    callback: Box<CallbackContext>,
    active: bool,
}

pub(super) type EmergencyStopCallback = unsafe extern "C" fn();

// Calls are serialized by EventStreamRecorder. Swift locks its callback fields
// and mutates only thread-safe CFRunLoop source state across the ABI.
unsafe impl Send for NativeInputSource {}

impl NativeInputSource {
    pub(super) fn create(
        sender: mpsc::Sender<NativeInputEvent>,
        next_seq: Arc<AtomicU64>,
    ) -> Result<Self, &'static str> {
        #[cfg(target_os = "macos")]
        {
            let api = platform::api().ok_or("native_runtime_unavailable")?;
            let raw = unsafe { (api.create)() };
            if raw.is_null() {
                return Err("native_source_create_failed");
            }
            Ok(Self {
                raw,
                callback: Box::new(CallbackContext {
                    sender,
                    next_seq,
                    host_pid: i64::from(std::process::id()),
                }),
                active: false,
            })
        }
        #[cfg(not(target_os = "macos"))]
        {
            let _ = (sender, next_seq);
            Err("native_runtime_unavailable")
        }
    }

    pub(super) fn start(&mut self) -> Result<(), &'static str> {
        if self.active {
            return Err("recording_already_active");
        }
        #[cfg(target_os = "macos")]
        {
            let api = platform::api().ok_or("native_runtime_unavailable")?;
            let context = self.callback.as_mut() as *mut CallbackContext;
            let status =
                unsafe { (api.start)(self.raw, Some(native_input_callback), context.cast()) };
            if status != 0 {
                return Err(match status {
                    13 => "input_monitoring_denied",
                    16 => "recording_already_active",
                    _ => "native_source_start_failed",
                });
            }
            self.active = true;
            Ok(())
        }
        #[cfg(not(target_os = "macos"))]
        Err("native_runtime_unavailable")
    }

    pub(super) fn stop(&mut self) -> Result<(), &'static str> {
        if !self.active {
            return Ok(());
        }
        #[cfg(target_os = "macos")]
        {
            let api = platform::api().ok_or("native_runtime_unavailable")?;
            let status = unsafe { (api.stop)(self.raw) };
            if status != 0 {
                return Err("native_source_stop_failed");
            }
            self.active = false;
            Ok(())
        }
        #[cfg(not(target_os = "macos"))]
        Err("native_runtime_unavailable")
    }
}

impl Drop for NativeInputSource {
    fn drop(&mut self) {
        #[cfg(target_os = "macos")]
        if let Some(api) = platform::api() {
            if self.active {
                unsafe {
                    (api.stop)(self.raw);
                }
            }
            unsafe {
                (api.destroy)(self.raw);
            }
        }
    }
}

unsafe extern "C" fn native_input_callback(
    context: *mut std::ffi::c_void,
    event_type: u32,
    monotonic_ns: u64,
    source_pid: i64,
    x: f64,
    y: f64,
    scroll_x: f64,
    scroll_y: f64,
    flags: u64,
    key_code: u16,
    button: i64,
    click_count: i64,
    foreground_pid: i64,
    application_generation: u64,
) {
    if context.is_null() {
        return;
    }
    let context = unsafe { &*(context.cast::<CallbackContext>()) };
    if source_pid == context.host_pid {
        return;
    }
    let seq = context.next_seq.fetch_add(1, Ordering::Relaxed);
    let event = NativeInputEvent {
        seq,
        event_type,
        monotonic_ns,
        source_pid,
        x,
        y,
        scroll_x,
        scroll_y,
        flags,
        key_code,
        button,
        click_count,
        foreground_pid,
        application_generation,
    };
    // The callback never waits for backpressure. Sequence allocation happens
    // before try_send, so the worker can report every lost range explicitly.
    let _ = context.sender.try_send(event);
}

#[cfg(target_os = "macos")]
mod platform {
    use std::ffi::{c_char, c_int, c_void, CStr, CString};
    use std::mem;
    use std::path::PathBuf;
    use std::sync::OnceLock;

    use serde_json::Value;

    const RTLD_NOW: c_int = 0x2;
    const LIBRARY_NAME: &str = "libqwenpaw_record_replay.dylib";
    const ABI_VERSION: u32 = 7;
    static API: OnceLock<NativeApi> = OnceLock::new();

    unsafe extern "C" {
        fn dlopen(path: *const c_char, mode: c_int) -> *mut c_void;
        fn dlclose(handle: *mut c_void) -> c_int;
        fn dlsym(handle: *mut c_void, symbol: *const c_char) -> *mut c_void;
    }

    type AbiVersion = unsafe extern "C" fn() -> u32;
    type Create = unsafe extern "C" fn() -> *mut c_void;
    type EventCallback = unsafe extern "C" fn(
        *mut c_void,
        u32,
        u64,
        i64,
        f64,
        f64,
        f64,
        f64,
        u64,
        u16,
        i64,
        i64,
        i64,
        u64,
    );
    type Start = unsafe extern "C" fn(*mut c_void, Option<EventCallback>, *mut c_void) -> i32;
    type Stop = unsafe extern "C" fn(*mut c_void) -> i32;
    type Destroy = unsafe extern "C" fn(*mut c_void);
    type Enrich = unsafe extern "C" fn(u32, u64, f64, f64, i64, u64) -> *mut c_char;
    type StringFree = unsafe extern "C" fn(*mut c_char);
    type IndicatorSet = unsafe extern "C" fn(u32, Option<super::EmergencyStopCallback>);
    type CaptureGuard = unsafe extern "C" fn(*mut u64) -> u32;

    pub(super) struct NativeApi {
        #[allow(dead_code)]
        handle: usize,
        pub(super) create: Create,
        pub(super) start: Start,
        pub(super) stop: Stop,
        pub(super) destroy: Destroy,
        pub(super) enrich: Enrich,
        pub(super) string_free: StringFree,
        pub(super) indicator_set: IndicatorSet,
        pub(super) capture_guard: CaptureGuard,
    }

    // dlopen handles and immutable function pointers are process-lifetime data.
    unsafe impl Send for NativeApi {}
    unsafe impl Sync for NativeApi {}

    pub(super) fn api() -> Option<&'static NativeApi> {
        API.get()
    }

    pub(super) fn load() -> Result<(), String> {
        if API.get().is_some() {
            return Ok(());
        }
        for candidate in candidates() {
            if !candidate.is_file() {
                continue;
            }
            let path = CString::new(candidate.to_string_lossy().as_bytes())
                .map_err(|_| "native shim path contains NUL".to_owned())?;
            unsafe {
                let handle = dlopen(path.as_ptr(), RTLD_NOW);
                if handle.is_null() {
                    continue;
                }
                match load_api(handle) {
                    Ok(loaded) => {
                        if API.set(loaded).is_err() {
                            dlclose(handle);
                        }
                        return Ok(());
                    }
                    Err(error) => {
                        dlclose(handle);
                        return Err(error);
                    }
                }
            }
        }
        Err("bundled native shim could not be loaded".to_owned())
    }

    unsafe fn load_api(handle: *mut c_void) -> Result<NativeApi, String> {
        let version: AbiVersion = unsafe { symbol(handle, "qwenpaw_record_replay_abi_version")? };
        if unsafe { version() } != ABI_VERSION {
            return Err("native shim ABI version mismatch".to_owned());
        }
        Ok(NativeApi {
            handle: handle as usize,
            create: unsafe { symbol(handle, "qwenpaw_record_replay_input_source_create")? },
            start: unsafe { symbol(handle, "qwenpaw_record_replay_input_source_start")? },
            stop: unsafe { symbol(handle, "qwenpaw_record_replay_input_source_stop")? },
            destroy: unsafe { symbol(handle, "qwenpaw_record_replay_input_source_destroy")? },
            enrich: unsafe { symbol(handle, "qwenpaw_record_replay_event_enrich_json")? },
            string_free: unsafe { symbol(handle, "qwenpaw_record_replay_string_free")? },
            indicator_set: unsafe { symbol(handle, "qwenpaw_record_replay_indicator_set")? },
            capture_guard: unsafe { symbol(handle, "qwenpaw_record_replay_capture_guard")? },
        })
    }

    pub(super) fn enrich_event(event: &super::NativeInputEvent) -> Result<Value, &'static str> {
        let Some(api) = api() else {
            return Err("native_runtime_unavailable");
        };
        let raw = unsafe {
            (api.enrich)(
                event.event_type,
                event.monotonic_ns,
                event.x,
                event.y,
                event.foreground_pid,
                event.application_generation,
            )
        };
        if raw.is_null() {
            return Err("native_enrichment_failed");
        }
        let parsed = unsafe { CStr::from_ptr(raw) }
            .to_str()
            .map_err(|_| "native_enrichment_invalid_utf8")
            .and_then(|value| {
                serde_json::from_str(value).map_err(|_| "native_enrichment_invalid_json")
            });
        unsafe {
            (api.string_free)(raw);
        }
        parsed
    }

    unsafe fn symbol<T>(handle: *mut c_void, name: &str) -> Result<T, String> {
        let name = CString::new(name).map_err(|_| "native symbol contains NUL".to_owned())?;
        let raw = unsafe { dlsym(handle, name.as_ptr()) };
        if raw.is_null() {
            return Err(format!("native shim missing symbol {name:?}"));
        }
        Ok(unsafe { mem::transmute_copy(&raw) })
    }

    fn candidates() -> Vec<PathBuf> {
        let mut candidates = Vec::new();
        if let Ok(executable) = std::env::current_exe() {
            if let Some(contents) = executable.parent().and_then(|macos| macos.parent()) {
                candidates.push(contents.join("Frameworks").join(LIBRARY_NAME));
            }
        }
        #[cfg(debug_assertions)]
        candidates.push(
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("target/native")
                .join(LIBRARY_NAME),
        );
        candidates
    }
}

pub(super) fn capture_guard() -> Result<u64, &'static str> {
    #[cfg(target_os = "macos")]
    {
        let api = platform::api().ok_or("native_runtime_unavailable")?;
        let mut generation = 0;
        match unsafe { (api.capture_guard)(&mut generation) } {
            0 => Ok(generation),
            1 => Err("recording_screen_locked"),
            2 => Err("recording_secure_input"),
            3 => Err("recording_session_inactive"),
            5 => Err("recording_permission_revoked"),
            _ => Err("recording_environment_unavailable"),
        }
    }
    #[cfg(not(target_os = "macos"))]
    Err("native_runtime_unavailable")
}

#[cfg(target_os = "macos")]
pub(super) fn set_activity_indicator(activity: u32, emergency_stop: Option<EmergencyStopCallback>) {
    if let Some(api) = platform::api() {
        unsafe {
            (api.indicator_set)(activity, emergency_stop);
        }
    }
}

#[cfg(not(target_os = "macos"))]
pub(super) fn set_activity_indicator(
    _activity: u32,
    _emergency_stop: Option<EmergencyStopCallback>,
) {
}

#[cfg(target_os = "macos")]
pub(super) fn load() -> Result<(), String> {
    platform::load()
}

#[cfg(not(target_os = "macos"))]
pub(super) fn load() -> Result<(), String> {
    Err("native desktop runtime is not available on this platform".to_owned())
}

#[cfg(target_os = "macos")]
pub(super) fn enrich_event(event: &NativeInputEvent) -> Result<Value, &'static str> {
    platform::enrich_event(event)
}

#[cfg(not(target_os = "macos"))]
pub(super) fn enrich_event(_event: &NativeInputEvent) -> Result<Value, &'static str> {
    Err("native_runtime_unavailable")
}
