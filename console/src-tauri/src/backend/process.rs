//! Backend process spawning with platform-specific Windows console handling.

use std::{
    ffi::{OsStr, OsString},
    io::{BufRead, BufReader, Read},
    path::PathBuf,
    sync::Arc,
    thread,
};

#[cfg(not(windows))]
use shared_child::SharedChild;
use tauri::async_runtime::{block_on, channel, Receiver, Sender};

#[derive(Debug)]
pub(super) struct BackendCommand {
    program: OsString,
    args: Vec<OsString>,
    current_dir: Option<PathBuf>,
    envs: Vec<(OsString, OsString)>,
}

impl BackendCommand {
    pub(super) fn new(program: impl AsRef<OsStr>) -> Self {
        Self {
            program: program.as_ref().to_os_string(),
            args: Vec::new(),
            current_dir: None,
            envs: Vec::new(),
        }
    }

    #[must_use]
    #[cfg(debug_assertions)]
    pub(super) fn args<I, S>(mut self, args: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: AsRef<OsStr>,
    {
        self.args
            .extend(args.into_iter().map(|arg| arg.as_ref().to_os_string()));
        self
    }

    #[must_use]
    pub(super) fn env(mut self, key: impl AsRef<OsStr>, value: impl AsRef<OsStr>) -> Self {
        self.envs
            .push((key.as_ref().to_os_string(), value.as_ref().to_os_string()));
        self
    }

    #[must_use]
    pub(super) fn current_dir(mut self, current_dir: impl Into<PathBuf>) -> Self {
        self.current_dir = Some(current_dir.into());
        self
    }

    pub(super) fn program_display(&self) -> String {
        self.program.to_string_lossy().into_owned()
    }
}

#[derive(Debug)]
pub(super) enum BackendEvent {
    Stdout(Vec<u8>),
    Stderr(Vec<u8>),
    Error(String),
    Terminated {
        code: Option<i32>,
        signal: Option<i32>,
    },
}

#[derive(Debug)]
pub(super) struct BackendChild {
    inner: PlatformChild,
}

impl BackendChild {
    pub(super) fn pid(&self) -> u32 {
        self.inner.pid()
    }

    pub(super) fn kill(self) -> Result<(), String> {
        self.inner.kill()
    }
}

#[derive(Debug)]
enum PlatformChild {
    #[cfg(not(windows))]
    Shared(Arc<SharedChild>),
    #[cfg(windows)]
    Windows(Arc<windows_impl::WindowsChild>),
}

impl PlatformChild {
    fn pid(&self) -> u32 {
        match self {
            #[cfg(not(windows))]
            Self::Shared(child) => child.id(),
            #[cfg(windows)]
            Self::Windows(child) => child.pid(),
        }
    }

    fn kill(self) -> Result<(), String> {
        match self {
            #[cfg(not(windows))]
            Self::Shared(child) => child.kill().map_err(|err| err.to_string()),
            #[cfg(windows)]
            Self::Windows(child) => child.kill().map_err(|err| err.to_string()),
        }
    }
}

pub(super) fn spawn(
    command: BackendCommand,
) -> Result<(Receiver<BackendEvent>, BackendChild), String> {
    #[cfg(windows)]
    {
        windows_impl::spawn(command)
    }
    #[cfg(not(windows))]
    {
        spawn_std(command)
    }
}

#[cfg(not(windows))]
fn spawn_std(command: BackendCommand) -> Result<(Receiver<BackendEvent>, BackendChild), String> {
    use std::process::{Command as StdCommand, Stdio};

    let mut cmd = StdCommand::new(&command.program);
    cmd.args(&command.args)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    if let Some(current_dir) = &command.current_dir {
        cmd.current_dir(current_dir);
    }
    for (key, value) in &command.envs {
        cmd.env(key, value);
    }

    let mut child = cmd
        .spawn()
        .map_err(|err| format!("failed to spawn backend: {err}"))?;
    let stdout = child.stdout.take();
    let stderr = child.stderr.take();
    let shared = Arc::new(
        SharedChild::new(child).map_err(|err| format!("failed to track backend process: {err}"))?,
    );
    let (tx, rx) = channel(100);

    if let Some(stdout) = stdout {
        spawn_reader(tx.clone(), stdout, BackendEvent::Stdout);
    }
    if let Some(stderr) = stderr {
        spawn_reader(tx.clone(), stderr, BackendEvent::Stderr);
    }
    spawn_shared_waiter(tx, shared.clone());

    Ok((
        rx,
        BackendChild {
            inner: PlatformChild::Shared(shared),
        },
    ))
}

#[cfg(not(windows))]
fn spawn_shared_waiter(tx: Sender<BackendEvent>, child: Arc<SharedChild>) {
    thread::spawn(move || match child.wait() {
        Ok(status) => {
            let signal = exit_signal(&status);
            send_event(
                &tx,
                BackendEvent::Terminated {
                    code: status.code(),
                    signal,
                },
            );
        }
        Err(err) => send_event(&tx, BackendEvent::Error(err.to_string())),
    });
}

#[cfg(all(not(windows), unix))]
fn exit_signal(status: &std::process::ExitStatus) -> Option<i32> {
    use std::os::unix::process::ExitStatusExt;
    status.signal()
}

#[cfg(all(not(windows), not(unix)))]
fn exit_signal(_status: &std::process::ExitStatus) -> Option<i32> {
    None
}

fn spawn_reader<R, F>(tx: Sender<BackendEvent>, reader: R, wrapper: F)
where
    R: Read + Send + 'static,
    F: Fn(Vec<u8>) -> BackendEvent + Copy + Send + 'static,
{
    thread::spawn(move || {
        let mut reader = BufReader::new(reader);
        loop {
            let mut buf = Vec::new();
            match reader.read_until(b'\n', &mut buf) {
                Ok(0) => break,
                Ok(_) => send_event(&tx, wrapper(buf)),
                Err(err) => {
                    send_event(&tx, BackendEvent::Error(err.to_string()));
                    break;
                }
            }
        }
    });
}

fn send_event(tx: &Sender<BackendEvent>, event: BackendEvent) {
    let tx = tx.clone();
    let _ = block_on(async move { tx.send(event).await });
}

#[cfg(windows)]
mod windows_impl {
    use super::*;
    use std::{
        collections::BTreeMap,
        fs::File,
        io,
        mem::size_of,
        os::windows::{
            ffi::OsStrExt,
            io::{FromRawHandle, RawHandle},
        },
        ptr::{null, null_mut},
    };

    use windows_sys::Win32::{
        Foundation::{
            CloseHandle, SetHandleInformation, HANDLE, HANDLE_FLAG_INHERIT, INVALID_HANDLE_VALUE,
        },
        Security::SECURITY_ATTRIBUTES,
        System::{
            Pipes::CreatePipe,
            Threading::{
                CreateProcessW, GetExitCodeProcess, TerminateProcess, WaitForSingleObject,
                CREATE_NEW_CONSOLE, CREATE_UNICODE_ENVIRONMENT, INFINITE, PROCESS_INFORMATION,
                STARTF_USESHOWWINDOW, STARTF_USESTDHANDLES, STARTUPINFOW,
            },
        },
        UI::WindowsAndMessaging::SW_HIDE,
    };

    #[derive(Debug)]
    pub(super) struct WindowsChild {
        process: HANDLE,
        pid: u32,
    }

    unsafe impl Send for WindowsChild {}
    unsafe impl Sync for WindowsChild {}

    impl WindowsChild {
        pub(super) fn pid(&self) -> u32 {
            self.pid
        }

        pub(super) fn kill(&self) -> io::Result<()> {
            let ok = unsafe { TerminateProcess(self.process, 1) };
            if ok == 0 {
                Err(io::Error::last_os_error())
            } else {
                Ok(())
            }
        }

        fn wait(&self) -> io::Result<Option<i32>> {
            let wait = unsafe { WaitForSingleObject(self.process, INFINITE) };
            if wait == u32::MAX {
                return Err(io::Error::last_os_error());
            }

            let mut code = 0u32;
            let ok = unsafe { GetExitCodeProcess(self.process, &mut code) };
            if ok == 0 {
                Err(io::Error::last_os_error())
            } else {
                Ok(Some(code as i32))
            }
        }
    }

    impl Drop for WindowsChild {
        fn drop(&mut self) {
            unsafe {
                CloseHandle(self.process);
            }
        }
    }

    #[derive(Debug)]
    struct OwnedHandle(HANDLE);

    impl OwnedHandle {
        fn invalid() -> Self {
            Self(null_mut())
        }

        fn as_raw(&self) -> HANDLE {
            self.0
        }

        fn take(&mut self) -> HANDLE {
            std::mem::replace(&mut self.0, null_mut())
        }

        unsafe fn into_file(mut self) -> File {
            File::from_raw_handle(self.take() as RawHandle)
        }
    }

    impl Drop for OwnedHandle {
        fn drop(&mut self) {
            if !self.0.is_null() && self.0 != INVALID_HANDLE_VALUE {
                unsafe {
                    CloseHandle(self.0);
                }
            }
        }
    }

    pub(super) fn spawn(
        command: BackendCommand,
    ) -> Result<(Receiver<BackendEvent>, BackendChild), String> {
        let stdout_pipe = create_pipe(false, true).map_err(format_spawn_error)?;
        let stderr_pipe = create_pipe(false, true).map_err(format_spawn_error)?;
        let stdin_pipe = create_pipe(true, false).map_err(format_spawn_error)?;

        let mut startup = STARTUPINFOW {
            cb: size_of::<STARTUPINFOW>() as u32,
            dwFlags: STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW,
            wShowWindow: SW_HIDE as u16,
            hStdInput: stdin_pipe.0.as_raw(),
            hStdOutput: stdout_pipe.1.as_raw(),
            hStdError: stderr_pipe.1.as_raw(),
            ..Default::default()
        };
        let mut process_info = PROCESS_INFORMATION::default();
        let application = wide_null(&command.program);
        let mut command_line = wide_null_os(&build_command_line(&command));
        let current_dir = command.current_dir.as_ref().map(wide_null_path);
        let mut env_block = environment_block(&command.envs);

        let ok = unsafe {
            CreateProcessW(
                application.as_ptr(),
                command_line.as_mut_ptr(),
                null(),
                null(),
                1,
                CREATE_NEW_CONSOLE | CREATE_UNICODE_ENVIRONMENT,
                env_block.as_mut_ptr().cast(),
                current_dir
                    .as_ref()
                    .map_or(null(), |current_dir| current_dir.as_ptr()),
                &mut startup,
                &mut process_info,
            )
        };

        // Parent no longer needs child-side handles after CreateProcessW.
        drop(stdout_pipe.1);
        drop(stderr_pipe.1);
        drop(stdin_pipe.0);
        drop(stdin_pipe.1);

        if ok == 0 {
            return Err(format_spawn_error(io::Error::last_os_error()));
        }

        unsafe {
            CloseHandle(process_info.hThread);
        }

        let stdout = unsafe { stdout_pipe.0.into_file() };
        let stderr = unsafe { stderr_pipe.0.into_file() };
        let child = Arc::new(WindowsChild {
            process: process_info.hProcess,
            pid: process_info.dwProcessId,
        });
        let (tx, rx) = channel(100);

        spawn_reader(tx.clone(), stdout, BackendEvent::Stdout);
        spawn_reader(tx.clone(), stderr, BackendEvent::Stderr);
        spawn_windows_waiter(tx, child.clone());

        Ok((
            rx,
            BackendChild {
                inner: PlatformChild::Windows(child),
            },
        ))
    }

    fn spawn_windows_waiter(tx: Sender<BackendEvent>, child: Arc<WindowsChild>) {
        thread::spawn(move || match child.wait() {
            Ok(code) => send_event(&tx, BackendEvent::Terminated { code, signal: None }),
            Err(err) => send_event(&tx, BackendEvent::Error(err.to_string())),
        });
    }

    fn create_pipe(
        inherit_read: bool,
        inherit_write: bool,
    ) -> io::Result<(OwnedHandle, OwnedHandle)> {
        let mut read = OwnedHandle::invalid();
        let mut write = OwnedHandle::invalid();
        let security = SECURITY_ATTRIBUTES {
            nLength: size_of::<SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: null_mut(),
            bInheritHandle: 1,
        };

        let ok = unsafe { CreatePipe(&mut read.0, &mut write.0, &security, 0) };
        if ok == 0 {
            return Err(io::Error::last_os_error());
        }

        set_inherit(read.as_raw(), inherit_read)?;
        set_inherit(write.as_raw(), inherit_write)?;
        Ok((read, write))
    }

    fn set_inherit(handle: HANDLE, inherit: bool) -> io::Result<()> {
        let flags = if inherit { HANDLE_FLAG_INHERIT } else { 0 };
        let ok = unsafe { SetHandleInformation(handle, HANDLE_FLAG_INHERIT, flags) };
        if ok == 0 {
            Err(io::Error::last_os_error())
        } else {
            Ok(())
        }
    }

    fn build_command_line(command: &BackendCommand) -> OsString {
        let mut parts = Vec::with_capacity(command.args.len() + 1);
        parts.push(quote_arg(&command.program));
        parts.extend(command.args.iter().map(|arg| quote_arg(arg)));
        OsString::from(parts.join(" "))
    }

    fn quote_arg(arg: &OsStr) -> String {
        let text = arg.to_string_lossy();
        if !text.is_empty()
            && !text
                .chars()
                .any(|ch| matches!(ch, ' ' | '\t' | '\n' | '\r' | '"'))
        {
            return text.into_owned();
        }

        let mut out = String::from("\"");
        let mut backslashes = 0usize;
        for ch in text.chars() {
            match ch {
                '\\' => backslashes += 1,
                '"' => {
                    out.push_str(&"\\".repeat(backslashes * 2 + 1));
                    out.push('"');
                    backslashes = 0;
                }
                _ => {
                    out.push_str(&"\\".repeat(backslashes));
                    backslashes = 0;
                    out.push(ch);
                }
            }
        }
        out.push_str(&"\\".repeat(backslashes * 2));
        out.push('"');
        out
    }

    fn environment_block(overrides: &[(OsString, OsString)]) -> Vec<u16> {
        let mut values = BTreeMap::<String, (OsString, OsString)>::new();
        for (key, value) in std::env::vars_os() {
            values.insert(env_key(&key), (key, value));
        }
        for (key, value) in overrides {
            values.insert(env_key(key), (key.clone(), value.clone()));
        }

        let mut block = Vec::new();
        for (_normalized, (key, value)) in values {
            block.extend(key.as_os_str().encode_wide());
            block.push('=' as u16);
            block.extend(value.as_os_str().encode_wide());
            block.push(0);
        }
        block.push(0);
        block
    }

    fn env_key(key: &OsString) -> String {
        key.to_string_lossy().to_ascii_uppercase()
    }

    fn wide_null(value: &OsStr) -> Vec<u16> {
        value.encode_wide().chain(std::iter::once(0)).collect()
    }

    fn wide_null_os(value: &OsString) -> Vec<u16> {
        value
            .as_os_str()
            .encode_wide()
            .chain(std::iter::once(0))
            .collect()
    }

    fn wide_null_path(value: &PathBuf) -> Vec<u16> {
        value
            .as_os_str()
            .encode_wide()
            .chain(std::iter::once(0))
            .collect()
    }

    fn format_spawn_error(err: io::Error) -> String {
        format!("failed to spawn backend: {err}")
    }
}
