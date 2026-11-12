//! Persist startup diagnostics before Tauri windows and regular logging exist.

use std::{
    backtrace::Backtrace,
    error::Error,
    fs::{self, File, OpenOptions},
    io::{self, Write},
    panic::{catch_unwind, AssertUnwindSafe},
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, Ordering},
        Mutex, OnceLock,
    },
    time::{Instant, SystemTime, UNIX_EPOCH},
};

use fs2::FileExt;

const IDENTIFIER: &str = "io.agentscope.qwenpaw.desktop";
const MAX_LOG_BYTES: usize = 128 * 1024;
const NORMAL_LOG_BYTES: usize = MAX_LOG_BYTES / 2;
const HISTORY_COUNT: usize = 20;
const TRUNCATED: &str = "\n[diagnostic truncated]\n";
static DIAGNOSTICS: OnceLock<Diagnostics> = OnceLock::new();

#[derive(Clone, Copy, PartialEq, Eq)]
pub(crate) enum Mode {
    Desktop,
    AgentHost,
}

impl Mode {
    fn name(self) -> &'static str {
        match self {
            Self::Desktop => "desktop",
            Self::AgentHost => "agent-host",
        }
    }
}

struct Diagnostics {
    mode: Mode,
    interactive: bool,
    started: Instant,
    header: String,
    state: Mutex<LogState>,
    reported: AtomicBool,
}

struct LogState {
    directories: Vec<PathBuf>,
    sink: Option<LogSink>,
    stage: String,
    header_suffix: String,
    failure: String,
}

struct LogSink {
    file: File,
    // Lock a separate lease file; a Windows byte-range lock on the log would block readers.
    _lease: File,
    path: PathBuf,
    candidate: usize,
    written: usize,
}

pub(crate) fn init(mode: Mode) {
    DIAGNOSTICS.get_or_init(|| {
        let mut directories = Vec::new();
        if let Some(local) = dirs::data_local_dir() {
            directories.push(local.join(IDENTIFIER).join("logs").join("startup"));
        }
        directories.push(std::env::temp_dir().join("qwenpaw-desktop").join("startup"));
        Diagnostics::new(
            mode,
            directories,
            mode == Mode::Desktop && desktop_session_available(),
        )
    });
}

pub(crate) fn record(stage: &str, detail: impl AsRef<str>) {
    if let Some(diagnostics) = DIAGNOSTICS.get() {
        diagnostics.record(stage, detail.as_ref());
    }
}

pub(crate) fn set_desktop_version(version: &str) {
    if let Some(diagnostics) = DIAGNOSTICS.get() {
        diagnostics.set_desktop_version(version);
    }
}

pub(crate) fn current_stage() -> String {
    DIAGNOSTICS
        .get()
        .map(|diagnostics| {
            diagnostics
                .state
                .lock()
                .unwrap_or_else(|e| e.into_inner())
                .stage
                .clone()
        })
        .unwrap_or_else(|| "Build desktop application".into())
}

pub(crate) fn report_fatal(stage: &str, error: &str) {
    if let Some(diagnostics) = DIAGNOSTICS.get() {
        diagnostics.report_with(
            stage,
            error,
            &Backtrace::force_capture().to_string(),
            show_dialog,
            sync_log,
        );
    } else {
        stderr_message(&format!("{stage}: {error}"));
    }
}

pub(crate) fn error_chain(error: &dyn Error) -> String {
    let mut detail = error.to_string();
    let mut source = error.source();
    while let Some(cause) = source {
        detail.push_str(&format!("\nCaused by: {cause}"));
        source = cause.source();
    }
    detail
}

impl Diagnostics {
    fn new(mode: Mode, directories: Vec<PathBuf>, interactive: bool) -> Self {
        let diagnostics = Self {
            mode,
            interactive,
            started: Instant::now(),
            header: format!(
                "QwenPaw Desktop startup diagnostics\ncargo_version={} pid={} mode={} os={} started_unix_ms={}\n",
                env!("CARGO_PKG_VERSION"),
                std::process::id(),
                mode.name(),
                std::env::consts::OS,
                timestamp(),
            ),
            state: Mutex::new(LogState {
                directories,
                sink: None,
                stage: "Initialize startup diagnostics".into(),
                header_suffix: String::new(),
                failure: String::new(),
            }),
            reported: AtomicBool::new(false),
        };
        let executable = match std::env::current_exe() {
            Ok(path) => format!("executable={}", path.display()),
            Err(error) => format!("Cannot locate executable: {error}"),
        };
        diagnostics.record("Process entry", &executable);
        diagnostics
    }

    fn set_desktop_version(&self, version: &str) {
        self.state
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .header_suffix = format!("desktop_version={version}\n");
        self.record(
            "Desktop context loaded",
            &format!("desktop_version={version}"),
        );
    }

    fn entry(&self, stage: &str, detail: &str) -> String {
        format!(
            "[unix_ms={}] elapsed_ms={} stage={}\n{}\n",
            timestamp(),
            self.started.elapsed().as_millis(),
            stage,
            detail,
        )
    }

    fn record(&self, stage: &str, detail: &str) {
        let entry = self.entry(stage, detail);
        let mut state = self.state.lock().unwrap_or_else(|e| e.into_inner());
        state.stage = stage.into();
        if let Err(error) = state.persist(&self.header, &entry, false, &mut sync_log) {
            stderr_message(&format!("Cannot save startup diagnostic: {error}"));
        }
    }

    fn report_with(
        &self,
        stage: &str,
        error: &str,
        backtrace: &str,
        mut display: impl FnMut(&str),
        mut synchronize: impl FnMut(&mut File) -> io::Result<()>,
    ) -> Option<PathBuf> {
        if self.reported.swap(true, Ordering::SeqCst) {
            return None;
        }
        let entry = self.entry(
            stage,
            &format!(
                "FATAL: {error}\n\nDiagnostic backtrace (captured at the reporting site, not the original failure):\n{backtrace}",
            ),
        );
        let saved = self
            .state
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .persist(&self.header, &entry, true, &mut synchronize);
        // Persist the full error first; a closed or blocked stderr must not prevent it.
        stderr_message(&format!("{stage}: {error}"));
        let location = match &saved {
            Ok(path) => format!("Diagnostic log:\n{}", path.display()),
            Err(reason) => format!(
                "Diagnostic log could not be saved:\n{}",
                shorten(reason, 600),
            ),
        };
        let message = format!(
            "QwenPaw Desktop could not start.\n\nStage: {stage}\n\nReason:\n{}\n\n{location}",
            shorten(error, 1200),
        );
        // Do not hold the log mutex while the dialog waits for the user, and never
        // let a dialog block background or headless runs.
        if self.mode == Mode::Desktop
            && self.interactive
            && catch_unwind(AssertUnwindSafe(|| display(&message))).is_err()
        {
            stderr_message("Native startup error dialog failed");
        }
        if let Err(reason) = &saved {
            stderr_message(&format!("Startup diagnostic was not saved: {reason}"));
        }
        saved.ok()
    }
}

impl LogState {
    fn persist(
        &mut self,
        header: &str,
        entry: &str,
        fatal: bool,
        synchronize: &mut impl FnMut(&mut File) -> io::Result<()>,
    ) -> Result<PathBuf, String> {
        let header = format!("{header}{}", self.header_suffix);
        let first = self.sink.as_ref().map(|sink| sink.candidate).unwrap_or(0);
        let mut failures = Vec::new();
        for candidate in first..self.directories.len() {
            let mut sink = match self.sink.take() {
                Some(sink) => sink,
                None => {
                    let header = if failures.is_empty() {
                        header.to_owned()
                    } else {
                        format!("{header}Previous logging error: {}\n", failures.join("; "))
                    };
                    match LogSink::open(&self.directories[candidate], candidate, &header) {
                        Ok(sink) => sink,
                        Err(error) => {
                            failures.push(format!(
                                "{}: {error}",
                                self.directories[candidate].display(),
                            ));
                            continue;
                        }
                    }
                }
            };
            match sink.append(entry, fatal, synchronize) {
                Ok(()) => {
                    let path = sink.path.clone();
                    self.sink = Some(sink);
                    return Ok(path);
                }
                Err(error) => {
                    failures.push(format!("{}: {error}", sink.path.display()));
                    // Drop the failed handle and retry the complete error in the
                    // next candidate directory.
                    drop(sink);
                }
            }
        }
        self.failure = if failures.is_empty() {
            "No writable startup log directory".into()
        } else {
            failures.join("; ")
        };
        Err(self.failure.clone())
    }
}

impl LogSink {
    fn open(directory: &Path, candidate: usize, header: &str) -> io::Result<Self> {
        fs::create_dir_all(directory)?;
        let name = format!(
            "startup-{}-{}-{}.log",
            timestamp(),
            std::process::id(),
            uuid::Uuid::new_v4(),
        );
        let path = directory.join(name);
        let lease_path = path.with_extension("lock");
        let lease = create_file(&lease_path)?;
        if let Err(error) = lease.try_lock_exclusive() {
            drop(lease);
            let _ = fs::remove_file(lease_path);
            return Err(error);
        }
        let file = match create_file(&path) {
            Ok(file) => file,
            Err(error) => {
                drop(lease);
                let _ = fs::remove_file(lease_path);
                return Err(error);
            }
        };
        let mut sink = Self {
            file,
            _lease: lease,
            path,
            candidate,
            written: 0,
        };
        sink.append(header, false, &mut sync_log)?;
        prune_history(directory);
        Ok(sink)
    }

    fn append(
        &mut self,
        entry: &str,
        fatal: bool,
        synchronize: &mut impl FnMut(&mut File) -> io::Result<()>,
    ) -> io::Result<()> {
        // Keep half the capacity for fatal errors; wait records must not crowd out the cause.
        let limit = if fatal {
            MAX_LOG_BYTES
        } else {
            NORMAL_LOG_BYTES
        };
        let remaining = limit.saturating_sub(self.written);
        if remaining > 0 {
            let text = bounded_bytes(entry, remaining);
            self.file.write_all(text.as_bytes())?;
            self.written += text.len();
        }
        if fatal {
            synchronize(&mut self.file)?;
        }
        Ok(())
    }
}

fn create_file(path: &Path) -> io::Result<File> {
    let mut options = OpenOptions::new();
    options.read(true).write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    options.open(path)
}

fn sync_log(file: &mut File) -> io::Result<()> {
    file.flush()?;
    file.sync_all()
}

fn stderr_message(message: &str) {
    // stderr itself may be closed or failing; never panic and mask the original failure.
    let text = bounded_bytes(message, 4096);
    let _ = writeln!(io::stderr().lock(), "[QwenPaw Desktop] {text}");
}

fn timestamp() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
}

fn bounded_bytes(text: &str, limit: usize) -> String {
    if text.len() <= limit {
        return text.into();
    }
    if limit < TRUNCATED.len() {
        return TRUNCATED[..limit].into();
    }
    let mut end = limit - TRUNCATED.len();
    while !text.is_char_boundary(end) {
        end -= 1;
    }
    format!("{}{TRUNCATED}", &text[..end])
}

fn shorten(text: &str, characters: usize) -> String {
    let mut chars = text.chars();
    let short: String = chars.by_ref().take(characters).collect();
    if chars.next().is_some() {
        format!("{short}\n[Details truncated; see diagnostic log]")
    } else {
        short
    }
}

fn history_timestamp(path: &Path) -> Option<u128> {
    if path.extension()?.to_str()? != "log" {
        return None;
    }
    let mut parts = path
        .file_stem()?
        .to_str()?
        .strip_prefix("startup-")?
        .splitn(3, '-');
    let time = parts.next()?.parse().ok()?;
    parts.next()?.parse::<u32>().ok()?;
    uuid::Uuid::parse_str(parts.next()?).ok()?;
    Some(time)
}

fn prune_history(directory: &Path) {
    let Ok(entries) = fs::read_dir(directory) else {
        return;
    };
    let mut paths: Vec<_> = entries
        .flatten()
        .filter(|entry| entry.file_type().is_ok_and(|kind| kind.is_file()))
        .filter_map(|entry| history_timestamp(&entry.path()).map(|time| (time, entry.path())))
        .collect();
    paths.sort_by(|a, b| b.cmp(a));
    let mut closed = 0;
    for (_, path) in paths {
        let lease_path = path.with_extension("lock");
        if !fs::symlink_metadata(&lease_path).is_ok_and(|meta| meta.file_type().is_file()) {
            continue;
        }
        let Ok(lease) = OpenOptions::new().read(true).write(true).open(&lease_path) else {
            continue;
        };
        if lease.try_lock_exclusive().is_err() {
            continue;
        }
        closed += 1;
        if closed > HISTORY_COUNT && fs::remove_file(&path).is_ok() {
            drop(lease);
            let _ = fs::remove_file(lease_path);
        }
    }
}

fn desktop_session_available() -> bool {
    #[cfg(windows)]
    {
        use windows::Win32::{
            Foundation::HANDLE,
            System::StationsAndDesktops::{
                GetProcessWindowStation, GetUserObjectInformationW, UOI_FLAGS, USEROBJECTFLAGS,
            },
        };
        // Window station visibility flag from winuser.h; Windows metadata omits it.
        const WSF_VISIBLE: u32 = 0x0001;
        let Ok(station) = (unsafe { GetProcessWindowStation() }) else {
            return false;
        };
        let mut flags = USEROBJECTFLAGS::default();
        unsafe {
            GetUserObjectInformationW(
                HANDLE(station.0),
                UOI_FLAGS,
                Some((&mut flags as *mut USEROBJECTFLAGS).cast()),
                std::mem::size_of::<USEROBJECTFLAGS>() as u32,
                None,
            )
        }
        .is_ok()
            && flags.dwFlags & WSF_VISIBLE != 0
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        std::env::var_os("DISPLAY").is_some_and(|value| !value.is_empty())
            || std::env::var_os("WAYLAND_DISPLAY").is_some_and(|value| !value.is_empty())
    }
    #[cfg(target_os = "macos")]
    {
        #[link(name = "Security", kind = "framework")]
        extern "C" {
            fn SessionGetInfo(session: u32, session_id: *mut u32, attributes: *mut u32) -> i32;
        }
        // Query the caller's security session; daemons and SSH sessions lack graphic access.
        const SESSION_HAS_GRAPHIC_ACCESS: u32 = 0x0010;
        let mut attributes = 0;
        let status = unsafe { SessionGetInfo(u32::MAX, std::ptr::null_mut(), &mut attributes) };
        status == 0 && attributes & SESSION_HAS_GRAPHIC_ACCESS != 0
    }
    #[cfg(not(any(windows, unix)))]
    {
        false
    }
}

const DIALOG_TITLE: &str = "QwenPaw Desktop - Startup failed";

#[cfg(windows)]
fn show_dialog(message: &str) {
    use windows::{
        core::PCWSTR,
        Win32::UI::WindowsAndMessaging::{
            MessageBoxW, MB_ICONERROR, MB_OK, MB_SETFOREGROUND, MB_TASKMODAL,
        },
    };
    // The classic message box wraps long paths instead of eliding their
    // middle like the task dialog does, and Ctrl+C copies the full text.
    let wide = |text: &str| text.encode_utf16().chain(Some(0)).collect::<Vec<u16>>();
    let text = wide(message);
    let title = wide(DIALOG_TITLE);
    unsafe {
        MessageBoxW(
            None,
            PCWSTR(text.as_ptr()),
            PCWSTR(title.as_ptr()),
            MB_OK | MB_ICONERROR | MB_SETFOREGROUND | MB_TASKMODAL,
        );
    }
}

#[cfg(not(windows))]
fn show_dialog(message: &str) {
    rfd::MessageDialog::new()
        .set_title(DIALOG_TITLE)
        .set_description(message)
        .set_level(rfd::MessageLevel::Error)
        .set_buttons(rfd::MessageButtons::Ok)
        .show();
}

#[cfg(test)]
mod tests {
    use super::*;

    struct TestDirectory(PathBuf);

    impl TestDirectory {
        fn new() -> Self {
            let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("../../.scratch/issue8616/startup-tests")
                .join(uuid::Uuid::new_v4().to_string());
            fs::create_dir_all(&path).unwrap();
            Self(path)
        }

        fn child(&self, name: &str) -> PathBuf {
            self.0.join(name)
        }
    }

    impl Drop for TestDirectory {
        fn drop(&mut self) {
            // Remove only this test's UUID directory; never touch real user data.
            fs::remove_dir_all(&self.0).unwrap();
        }
    }

    fn log_path(diagnostics: &Diagnostics) -> PathBuf {
        diagnostics
            .state
            .lock()
            .unwrap()
            .sink
            .as_ref()
            .unwrap()
            .path
            .clone()
    }

    fn old_log(directory: &Path, time: u128) -> PathBuf {
        let path = directory.join(format!("startup-{time}-1-{}.log", uuid::Uuid::new_v4()));
        fs::write(&path, "old diagnostic").unwrap();
        fs::write(path.with_extension("lock"), "").unwrap();
        path
    }

    #[test]
    fn normal_startup_records_version_mode_and_executable_without_dialog() {
        let directory = TestDirectory::new();
        let diagnostics = Diagnostics::new(Mode::Desktop, vec![directory.child("logs")], true);
        diagnostics.record("Load desktop context", "started");
        let text = fs::read_to_string(log_path(&diagnostics)).unwrap();
        assert!(text.contains("version="));
        assert!(text.contains("mode=desktop"));
        assert!(text.contains("executable="));
        assert!(text.contains("stage=Load desktop context"));
        assert!(!diagnostics.reported.load(Ordering::SeqCst));
    }

    #[test]
    fn unwritable_primary_directory_uses_fallback() {
        let directory = TestDirectory::new();
        let blocked = directory.child("blocked");
        fs::write(&blocked, "not a directory").unwrap();
        let fallback = directory.child("fallback");
        let diagnostics = Diagnostics::new(Mode::Desktop, vec![blocked, fallback.clone()], false);
        let path = log_path(&diagnostics);
        assert!(path.starts_with(fallback));
        assert!(fs::read_to_string(path)
            .unwrap()
            .contains("Previous logging error:"));
    }

    #[test]
    fn fatal_error_is_synced_and_readable_before_dialog() {
        let directory = TestDirectory::new();
        let diagnostics = Diagnostics::new(Mode::Desktop, vec![directory.child("logs")], true);
        let expected = log_path(&diagnostics);
        let mut calls = 0;
        let mut observed = None;
        // Assert outside the callback so the dialog panic guard cannot swallow failures.
        let did_sync = std::cell::Cell::new(false);
        let saved = diagnostics.report_with(
            "Register desktop window",
            "Cannot open C:\\Missing Path\\installer: path not found (os error 3)",
            "test backtrace",
            |message| {
                calls += 1;
                observed = Some((
                    did_sync.get(),
                    message.to_owned(),
                    fs::read_to_string(&expected),
                ));
            },
            |file| {
                sync_log(file)?;
                did_sync.set(true);
                Ok(())
            },
        );
        assert_eq!(saved, Some(expected.clone()));
        assert_eq!(calls, 1);
        let (synced_before_dialog, message, contents) = observed.unwrap();
        assert!(synced_before_dialog);
        assert!(message.contains("Register desktop window"));
        assert!(message.contains("os error 3"));
        assert!(message.contains(&expected.display().to_string()));
        let text = contents.unwrap();
        assert!(text.contains("FATAL:"));
        assert!(text.contains("captured at the reporting site"));
        assert!(text.contains("test backtrace"));
    }

    #[test]
    fn repeated_fatal_reporting_shows_only_one_dialog() {
        let directory = TestDirectory::new();
        let diagnostics = Diagnostics::new(Mode::Desktop, vec![directory.child("logs")], true);
        let mut calls = 0;
        assert!(diagnostics
            .report_with(
                "startup",
                "first failure",
                "trace",
                |_| calls += 1,
                sync_log
            )
            .is_some());
        let path = log_path(&diagnostics);
        let first = fs::read_to_string(&path).unwrap();
        assert!(diagnostics
            .report_with(
                "startup",
                "second failure",
                "trace",
                |_| calls += 1,
                sync_log
            )
            .is_none());
        assert_eq!(calls, 1);
        assert_eq!(fs::read_to_string(path).unwrap(), first);
    }

    #[test]
    fn agent_host_never_displays_a_dialog_even_in_interactive_session() {
        let directory = TestDirectory::new();
        let diagnostics = Diagnostics::new(Mode::AgentHost, vec![directory.child("logs")], true);
        let mut calls = 0;
        let saved = diagnostics
            .report_with(
                "background supervisor",
                "backend failed",
                "trace",
                |_| calls += 1,
                sync_log,
            )
            .unwrap();
        assert_eq!(calls, 0);
        let text = fs::read_to_string(saved).unwrap();
        assert!(text.contains("mode=agent-host"));
        assert!(text.contains("backend failed"));
    }

    #[test]
    fn headless_desktop_records_failure_without_a_dialog() {
        let directory = TestDirectory::new();
        let diagnostics = Diagnostics::new(Mode::Desktop, vec![directory.child("logs")], false);
        let mut calls = 0;
        assert!(diagnostics
            .report_with("startup", "failure", "trace", |_| calls += 1, sync_log)
            .is_some());
        assert_eq!(calls, 0);
    }

    #[test]
    fn update_deferred_is_logged_without_reporting_a_fatal_error() {
        let directory = TestDirectory::new();
        let diagnostics = Diagnostics::new(Mode::Desktop, vec![directory.child("logs")], true);
        diagnostics.record("Wait for installer", "record=installation/installer");
        diagnostics.record("Installer handoff finished", "waited_ms=420000");
        diagnostics.record("Update deferred", "Desktop start deferred while updating");
        assert!(!diagnostics.reported.load(Ordering::SeqCst));
        let text = fs::read_to_string(log_path(&diagnostics)).unwrap();
        assert!(text.contains("waited_ms=420000"));
        assert!(!text.contains("FATAL:"));
    }

    #[test]
    fn failed_directories_do_not_replace_original_error_or_claim_a_saved_log() {
        let directory = TestDirectory::new();
        let blocked = directory.child("blocked");
        fs::write(&blocked, "file").unwrap();
        let diagnostics = Diagnostics::new(
            Mode::Desktop,
            vec![blocked.join("primary"), blocked.join("fallback")],
            true,
        );
        let mut message = String::new();
        let saved = diagnostics.report_with(
            "Register desktop",
            "original missing path",
            "trace",
            |text| message = text.into(),
            sync_log,
        );
        assert!(saved.is_none());
        assert!(message.contains("original missing path"));
        assert!(message.contains("Diagnostic log could not be saved:"));
        assert!(!message.contains("Diagnostic log:\n"));
    }

    #[test]
    fn write_failure_retries_complete_error_in_fallback() {
        let directory = TestDirectory::new();
        let primary = directory.child("primary");
        let fallback = directory.child("fallback");
        let diagnostics = Diagnostics::new(Mode::Desktop, vec![primary, fallback.clone()], true);
        {
            let mut state = diagnostics.state.lock().unwrap();
            let sink = state.sink.as_mut().unwrap();
            // Simulate a write failure with a read-only handle; no permission or global changes.
            sink.file = File::open(&sink.path).unwrap();
        }
        let mut message = String::new();
        let saved = diagnostics
            .report_with(
                "Register desktop",
                "original failure",
                "trace",
                |text| message = text.into(),
                sync_log,
            )
            .unwrap();
        assert!(saved.starts_with(fallback));
        assert!(message.contains(&saved.display().to_string()));
        assert!(fs::read_to_string(saved)
            .unwrap()
            .contains("original failure"));
    }

    #[test]
    fn sync_failure_uses_fallback_before_showing_the_log_location() {
        let directory = TestDirectory::new();
        let fallback = directory.child("fallback");
        let diagnostics = Diagnostics::new(
            Mode::Desktop,
            vec![directory.child("primary"), fallback.clone()],
            true,
        );
        let mut attempts = 0;
        let mut message = String::new();
        let saved = diagnostics
            .report_with(
                "startup",
                "original failure",
                "trace",
                |text| message = text.into(),
                |file| {
                    attempts += 1;
                    if attempts == 1 {
                        Err(io::Error::other("injected sync failure"))
                    } else {
                        sync_log(file)
                    }
                },
            )
            .unwrap();
        assert_eq!(attempts, 2);
        assert!(saved.starts_with(fallback));
        assert!(message.contains(&saved.display().to_string()));
        let text = fs::read_to_string(saved).unwrap();
        assert!(text.contains("original failure"));
        assert!(text.contains("injected sync failure"));
    }

    #[test]
    fn sync_failure_in_all_candidates_reports_unsaved_original_error() {
        let directory = TestDirectory::new();
        let diagnostics = Diagnostics::new(
            Mode::Desktop,
            vec![directory.child("primary"), directory.child("fallback")],
            true,
        );
        let mut message = String::new();
        let saved = diagnostics.report_with(
            "startup",
            "original failure",
            "trace",
            |text| message = text.into(),
            |_| Err(io::Error::other("injected sync failure")),
        );
        assert!(saved.is_none());
        assert!(message.contains("original failure"));
        assert!(message.contains("Diagnostic log could not be saved:"));
    }

    #[test]
    fn unicode_paths_and_errors_remain_readable() {
        let directory = TestDirectory::new();
        let diagnostics = Diagnostics::new(Mode::Desktop, vec![directory.child("中文 目录")], true);
        let error = "无法打开文件 C:\\用户\\中文 路径\\installer";
        let mut message = String::new();
        let saved = diagnostics
            .report_with(
                "Register desktop",
                error,
                "trace",
                |text| message = text.into(),
                sync_log,
            )
            .unwrap();
        assert!(message.contains(error));
        assert!(message.contains("中文 目录"));
        assert!(fs::read_to_string(saved).unwrap().contains(error));
    }

    #[test]
    fn large_normal_records_reserve_space_for_fatal_details() {
        let directory = TestDirectory::new();
        let diagnostics = Diagnostics::new(Mode::Desktop, vec![directory.child("logs")], false);
        diagnostics.record("stage", &"界".repeat(MAX_LOG_BYTES));
        assert!(fs::metadata(log_path(&diagnostics)).unwrap().len() <= NORMAL_LOG_BYTES as u64);
        let saved = diagnostics
            .report_with("startup", "important failure", "trace", |_| {}, sync_log)
            .unwrap();
        let text = fs::read_to_string(saved).unwrap();
        assert!(text.contains(TRUNCATED));
        assert!(text.contains("FATAL: important failure"));
        assert!(text.len() <= MAX_LOG_BYTES);
    }

    #[test]
    fn oversized_fatal_error_is_bounded_and_explicitly_truncated() {
        let directory = TestDirectory::new();
        let diagnostics = Diagnostics::new(Mode::Desktop, vec![directory.child("logs")], false);
        let saved = diagnostics
            .report_with(
                "startup",
                &format!("original failure {}", "界".repeat(MAX_LOG_BYTES)),
                "trace",
                |_| {},
                sync_log,
            )
            .unwrap();
        let text = fs::read_to_string(saved).unwrap();
        assert!(text.len() <= MAX_LOG_BYTES);
        assert!(text.contains("FATAL: original failure"));
        assert!(text.ends_with(TRUNCATED));
    }

    #[test]
    fn dialog_shortens_error_without_shortening_saved_details() {
        let directory = TestDirectory::new();
        let diagnostics = Diagnostics::new(Mode::Desktop, vec![directory.child("logs")], true);
        let error = "界".repeat(2000);
        let mut message = String::new();
        let saved = diagnostics
            .report_with(
                "startup",
                &error,
                "trace",
                |text| message = text.into(),
                sync_log,
            )
            .unwrap();
        assert!(message.contains(&"界".repeat(1200)));
        assert!(!message.contains(&"界".repeat(1201)));
        assert!(message.contains("Details truncated"));
        assert!(fs::read_to_string(saved).unwrap().contains(&error));
    }

    #[test]
    fn truncation_never_splits_utf8() {
        for limit in 0..100 {
            let text = bounded_bytes(&"中文 diagnostic".repeat(20), limit);
            assert!(text.len() <= limit);
        }
    }

    #[test]
    fn pruning_keeps_twenty_closed_logs_and_ignores_unrelated_files() {
        let directory = TestDirectory::new();
        let mut paths = Vec::new();
        for time in 0..30 {
            paths.push(old_log(&directory.0, time));
        }
        let unrelated = directory.child("qwenpaw-desktop.log");
        let invalid = directory.child("startup-0-1-not-a-uuid.log");
        fs::write(&unrelated, "keep").unwrap();
        fs::write(&invalid, "keep").unwrap();
        let diagnostics = Diagnostics::new(Mode::Desktop, vec![directory.0.clone()], false);
        assert_eq!(
            paths.iter().filter(|path| path.exists()).count(),
            HISTORY_COUNT
        );
        assert!(!paths[0].exists());
        assert!(!paths[0].with_extension("lock").exists());
        assert!(paths[29].exists());
        assert!(unrelated.exists());
        assert!(invalid.exists());
        assert!(log_path(&diagnostics).exists());
    }

    #[test]
    fn pruning_never_removes_a_live_log_lease() {
        let directory = TestDirectory::new();
        let diagnostics = Diagnostics::new(Mode::Desktop, vec![directory.0.clone()], false);
        let live = log_path(&diagnostics);
        let future = timestamp() + 1000;
        let paths: Vec<_> = (0..30)
            .map(|offset| old_log(&directory.0, future + offset))
            .collect();
        prune_history(&directory.0);
        assert!(live.exists());
        assert!(live.with_extension("lock").exists());
        assert_eq!(
            paths.iter().filter(|path| path.exists()).count(),
            HISTORY_COUNT
        );
        diagnostics.record("still running", "live log was not removed");
        assert!(fs::read_to_string(live)
            .unwrap()
            .contains("live log was not removed"));
    }

    #[cfg(unix)]
    #[test]
    fn pruning_does_not_follow_log_symlinks() {
        let directory = TestDirectory::new();
        let target = directory.child("keep.txt");
        fs::write(&target, "keep").unwrap();
        let link = directory.child(&format!("startup-0-1-{}.log", uuid::Uuid::new_v4()));
        std::os::unix::fs::symlink(&target, &link).unwrap();
        fs::write(link.with_extension("lock"), "").unwrap();
        for time in 1..30 {
            old_log(&directory.0, time);
        }
        prune_history(&directory.0);
        assert!(link.exists());
        assert_eq!(fs::read_to_string(target).unwrap(), "keep");
    }

    #[test]
    fn concurrent_instances_have_independent_logs() {
        let directory = TestDirectory::new();
        let paths = std::thread::scope(|scope| {
            let handles: Vec<_> = (0..8)
                .map(|index| {
                    let root = directory.0.clone();
                    scope.spawn(move || {
                        let diagnostics = Diagnostics::new(Mode::AgentHost, vec![root], false);
                        let error = format!("failure from process {index}");
                        let path = diagnostics
                            .report_with("startup", &error, "trace", |_| {}, sync_log)
                            .unwrap();
                        (path, error)
                    })
                })
                .collect();
            handles
                .into_iter()
                .map(|handle| handle.join().unwrap())
                .collect::<Vec<_>>()
        });
        let unique: std::collections::BTreeSet<_> =
            paths.iter().map(|(path, _)| path.clone()).collect();
        assert_eq!(unique.len(), 8);
        for (path, error) in paths {
            let text = fs::read_to_string(path).unwrap();
            assert_eq!(text.matches("FATAL:").count(), 1);
            assert!(text.contains(&error));
        }
    }

    #[test]
    fn failed_dialog_does_not_lose_saved_error() {
        let directory = TestDirectory::new();
        let diagnostics = Diagnostics::new(Mode::Desktop, vec![directory.child("logs")], true);
        let mut calls = 0;
        let saved = diagnostics
            .report_with(
                "startup",
                "original failure",
                "trace",
                |_| {
                    calls += 1;
                    panic!("injected dialog failure");
                },
                sync_log,
            )
            .unwrap();
        assert_eq!(calls, 1);
        assert!(fs::read_to_string(saved)
            .unwrap()
            .contains("original failure"));
    }

    #[test]
    fn fallback_log_preserves_the_configured_desktop_version() {
        let directory = TestDirectory::new();
        let fallback = directory.child("fallback");
        let diagnostics = Diagnostics::new(
            Mode::Desktop,
            vec![directory.child("primary"), fallback.clone()],
            false,
        );
        diagnostics.set_desktop_version("2.3.0-beta.4");
        {
            let mut state = diagnostics.state.lock().unwrap();
            let sink = state.sink.as_mut().unwrap();
            sink.file = File::open(&sink.path).unwrap();
        }
        let saved = diagnostics
            .report_with("startup", "original failure", "trace", |_| {}, sync_log)
            .unwrap();
        assert!(saved.starts_with(fallback));
        assert!(fs::read_to_string(saved)
            .unwrap()
            .contains("desktop_version=2.3.0-beta.4"));
    }

    #[test]
    fn error_source_chain_is_preserved_when_available() {
        #[derive(Debug)]
        struct Outer(io::Error);
        impl std::fmt::Display for Outer {
            fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                write!(formatter, "desktop setup failed")
            }
        }
        impl Error for Outer {
            fn source(&self) -> Option<&(dyn Error + 'static)> {
                Some(&self.0)
            }
        }
        let text = error_chain(&Outer(io::Error::other("underlying failure")));
        assert_eq!(text, "desktop setup failed\nCaused by: underlying failure");
    }
}
