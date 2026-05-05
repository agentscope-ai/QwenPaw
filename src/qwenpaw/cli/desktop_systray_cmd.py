# -*- coding: utf-8 -*-
"""CLI command: run QwenPaw with system tray icon (Windows only)."""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import click

from ..utils.logging import setup_logger

logger = logging.getLogger(__name__)

# Platform check - only support Windows
if sys.platform != "win32":
    click.echo(
        "Error: System tray is currently only supported on Windows. "
        "Use 'qwenpaw app' or 'qwenpaw desktop' for other platforms.",
        err=True,
    )
    sys.exit(1)

# Windows-only imports
try:
    import pystray
    from PIL import Image
except ImportError as e:
    click.echo(
        f"Error: Required dependencies not installed. Please install with: "
        f"pip install pystray Pillow\n(Details: {e})",
        err=True,
    )
    sys.exit(1)

try:
    import webview
except ImportError:
    webview = None  # type: ignore[assignment]


class TrayIconManager:
    """Manages the system tray icon and menu for QwenPaw."""

    def __init__(
        self,
        on_show_window: Callable[[], None],
        on_hide_window: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        """Initialize the tray icon manager.

        Args:
            on_show_window: Callback to show/restore the window.
            on_hide_window: Callback to hide/minimize the window.
            on_quit: Callback to quit the application.
        """
        self._on_show_window = on_show_window
        self._on_hide_window = on_hide_window
        self._on_quit = on_quit
        self._icon: Optional[pystray.Icon] = None
        self._menu: Optional[pystray.Menu] = None

    def _create_icon_image(self) -> Image.Image:
        """Create the tray icon image from the bundled PNG.

        Returns:
            PIL Image object for the tray icon.
        """
        # Try to load the bundled tray icon
        tray_icon_path = Path(__file__).parent / "assets" / "tray_icon.png"

        if tray_icon_path.exists():
            icon = Image.open(tray_icon_path)
            # Resize to appropriate size for tray
            icon = icon.resize((64, 64), Image.Resampling.LANCZOS)
            return icon
        else:
            # Fallback: create a simple colored circle
            icon = Image.new("RGB", (64, 64), "orange")
            return icon

    def _build_menu(self) -> pystray.Menu:
        """Build the tray icon menu.

        Returns:
            pystray.Menu instance with configured menu items.
        """
        return pystray.Menu(
            pystray.MenuItem(
                "显示窗口",
                lambda icon, item: self._on_show_window(),
                default=True,
            ),
            pystray.MenuItem(
                "隐藏窗口",
                lambda icon, item: self._on_hide_window(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "退出",
                lambda icon, item: self._on_quit(),
            ),
        )

    def run(self, setup: Optional[Callable[[pystray.Icon], None]] = None) -> None:
        """Start the tray icon event loop.

        This method blocks until stop() is called.

        Args:
            setup: Optional callback to execute once the icon is ready.
        """
        icon_image = self._create_icon_image()
        self._icon = pystray.Icon(
            "QwenPaw",
            icon=icon_image,
            title="QwenPaw",
            menu=self._build_menu(),
        )

        # Run the icon (blocking call)
        self._icon.run(setup)

    def stop(self) -> None:
        """Stop the tray icon event loop."""
        if self._icon:
            self._icon.stop()

    def update_menu(self) -> None:
        """Update the tray menu to reflect dynamic changes."""
        if self._icon:
            self._icon.update_menu()


class AppProcess:
    """Manages the QwenPaw app subprocess (runs `qwenpaw app` command)."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: Optional[int] = None,
        log_level: str = "info",
    ) -> None:
        """Initialize the app process.

        Args:
            host: Host to bind the backend server.
            port: Port to bind the backend server (auto-selected if None).
            log_level: Log level for the backend process.
        """
        self._host = host
        self._port = port
        self._log_level = log_level
        self._process: Optional[subprocess.Popen] = None
        self._actual_port: int = 0
        self._stdout_threads: list[threading.Thread] = []

    def _find_free_port(self, host: str = "127.0.0.1") -> int:
        """Bind to port 0 and return the OS-assigned free port.

        Args:
            host: Host to bind to.

        Returns:
            A free port number.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, 0))
            sock.listen(1)
            return sock.getsockname()[1]

    def _wait_for_http(
        self, host: str, port: int, timeout_sec: float = 300.0
    ) -> bool:
        """Wait for HTTP server to be ready.

        Args:
            host: Server host.
            port: Server port.
            timeout_sec: Maximum wait time in seconds.

        Returns:
            True if server is ready, False if timeout.
        """
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(2.0)
                    s.connect((host, port))
                    return True
            except (OSError, socket.error):
                time.sleep(1)
        return False

    def _stream_reader(self, in_stream, out_stream) -> None:
        """Read from subprocess stream and write to output.

        Args:
            in_stream: Input stream to read from.
            out_stream: Output stream to write to.
        """
        try:
            for line in iter(in_stream.readline, ""):
                if not line:
                    break
                out_stream.write(line)
                out_stream.flush()
        except Exception:
            pass
        finally:
            try:
                in_stream.close()
            except Exception:
                pass

    def start(self) -> bool:
        """Start the app subprocess.

        Returns:
            True if started successfully, False otherwise.
        """
        # Auto-select port if not specified
        if self._port is None:
            self._actual_port = self._find_free_port(self._host)
        else:
            self._actual_port = self._port

        url = f"http://{self._host}:{self._actual_port}"
        logger.info(f"Starting QwenPaw app on {url} (port {self._actual_port})")

        env = os.environ.copy()
        from ..constant import LOG_LEVEL_ENV

        env[LOG_LEVEL_ENV] = self._log_level

        # Handle SSL cert file if present
        if "SSL_CERT_FILE" in env:
            cert_file = env["SSL_CERT_FILE"]
            if os.path.exists(cert_file):
                logger.info(f"SSL certificate: {cert_file}")
            else:
                logger.warning(
                    f"SSL_CERT_FILE set but not found: {cert_file}",
                )

        try:
            # Start subprocess
            self._process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "qwenpaw",
                    "app",
                    "--host",
                    self._host,
                    "--port",
                    str(self._actual_port),
                    "--log-level",
                    self._log_level,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                bufsize=1,
                universal_newlines=True,
            )

            # Start threads to handle subprocess output
            stdout_thread = threading.Thread(
                target=self._stream_reader,
                args=(self._process.stdout, sys.stdout),
                daemon=True,
            )
            stderr_thread = threading.Thread(
                target=self._stream_reader,
                args=(self._process.stderr, sys.stderr),
                daemon=True,
            )
            stdout_thread.start()
            stderr_thread.start()
            self._stdout_threads = [stdout_thread, stderr_thread]

            # Wait for server to be ready
            logger.info("Waiting for HTTP ready...")
            if self._wait_for_http(self._host, self._actual_port):
                logger.info("HTTP ready.")
                return True
            else:
                logger.error("Server did not become ready in time.")
                return False

        except Exception as e:
            logger.error(f"Failed to start app process: {e}")
            return False

    def get_url(self) -> str:
        """Get the backend server URL.

        Returns:
            The server URL string.
        """
        return f"http://{self._host}:{self._actual_port}"

    def get_port(self) -> int:
        """Get the backend server port.

        Returns:
            The server port number.
        """
        return self._actual_port

    def stop(self) -> None:
        """Stop the app subprocess gracefully."""
        if self._process and self._process.poll() is None:
            logger.info("Terminating app process...")
            try:
                self._process.terminate()
                try:
                    self._process.wait(timeout=5.0)
                    logger.info("App process terminated cleanly.")
                except subprocess.TimeoutExpired:
                    logger.warning(
                        "App process did not exit in 5s, force killing...",
                    )
                    try:
                        self._process.kill()
                        self._process.wait()
                        logger.info("App process force killed.")
                    except (ProcessLookupError, OSError) as e:
                        logger.debug(
                            f"kill() raised {e.__class__.__name__} "
                            f"(process already exited)",
                        )
            except (ProcessLookupError, OSError) as e:
                logger.debug(
                    f"terminate() raised {e.__class__.__name__} "
                    f"(process already exited)",
                )
        elif self._process:
            logger.info(
                f"App process already exited with code {self._process.returncode}",
            )


class WindowProcess:
    """Manages the WebView window subprocess.
    
    The window can be started, stopped, and restarted. When the window process
    exits (e.g., user closes the window), it can be restarted by calling start().
    Uses a local socket for IPC communication with the window process.
    """
    
    def __init__(self, url: str, log_level: str) -> None:
        """Initialize the window process.
        
        Args:
            url: URL to load in the webview.
            log_level: Log level for the window process.
        """
        self._url = url
        self._log_level = log_level
        self._process: Optional[subprocess.Popen] = None
        self._control_socket_path: Optional[str] = None
        
        # Create a unique socket path for IPC
        import tempfile
        import uuid
        self._socket_name = f"qwenpaw_window_{uuid.uuid4().hex[:8]}"
        if sys.platform == "win32":
            # On Windows, use a named pipe path
            # Construct path to avoid escaping issues
            self._control_socket_path = "\\\\.\\pipe\\" + self._socket_name
        else:
            # On Unix, use a Unix domain socket
            self._control_socket_path = os.path.join(tempfile.gettempdir(), f"{self._socket_name}.sock")
        
        # Pass socket path to subprocess - escape backslashes for Windows
        socket_path_escaped = self._control_socket_path.replace('\\', '\\\\') if sys.platform == "win32" else self._control_socket_path
        
        self._script = f"""
import sys
sys.path.insert(0, '{Path(__file__).parent.parent.parent}')
from qwenpaw.cli.desktop_systray_cmd import _run_webview_window
_run_webview_window('{self._url}', '{self._log_level}', '{socket_path_escaped}')
        """.strip()
    
    def start(self) -> bool:
        """Start the window process.
        
        Returns:
            True if started successfully, False if already running.
        """
        if self._process and self._process.poll() is None:
            logger.debug("Window process already running")
            return False
        
        try:
            self._process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    self._script,
                ],
                stdin=subprocess.DEVNULL,
                stdout=None,  # Let output go to console for debugging
                stderr=None,  # Let errors go to console for debugging
            )
            logger.info(f"Window process started with PID: {self._process.pid}")
            logger.debug(f"Control socket path: {self._control_socket_path}")
            
            # Wait for the socket server to start (retry loop)
            max_retries = 20
            for i in range(max_retries):
                time.sleep(0.2)  # 100ms per retry = 2 seconds total
                if self._try_connect():
                    logger.debug(f"Socket server ready after {i+1} attempts")
                    return True
            
            logger.warning("Socket server did not become ready in time")
            return True  # Still return True, window may work without IPC
            
        except Exception as e:
            logger.error(f"Failed to start window process: {e}")
            return False
    
    def _try_connect(self) -> bool:
        """Try to connect to the socket server to check if it's ready.
        
        Returns:
            True if connection successful, False otherwise.
        """
        try:
            if sys.platform == "win32":
                import win32file
                import win32pipe
                
                # Just try to open the pipe, don't actually read/write
                handle = win32file.CreateFile(
                    self._control_socket_path,
                    win32file.GENERIC_READ,  # Read-only to avoid interfering
                    0,  # No sharing - exclusive access
                    None,
                    win32file.OPEN_EXISTING,
                    win32file.FILE_FLAG_OVERLAPPED,  # Use overlapped for non-blocking
                    None,
                )
                # Don't close immediately - just check if we can open it
                # Actually, we need to close it, but the pipe should stay open on server side
                win32file.CloseHandle(handle)
                return True
            else:
                import socket
                client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    client.connect(self._control_socket_path)
                    client.close()
                    return True
                finally:
                    try:
                        client.close()
                    except:
                        pass
        except:
            return False
    
    def stop(self) -> None:
        """Stop the window process gracefully."""
        if self._process and self._process.poll() is None:
            logger.info("Stopping window process...")
            try:
                self._process.terminate()
                try:
                    self._process.wait(timeout=3.0)
                    logger.info("Window process stopped cleanly")
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait()
                    logger.info("Window process force killed")
            except Exception as e:
                logger.error(f"Error stopping window process: {e}")
        elif self._process:
            logger.debug(f"Window process already exited with code {self._process.returncode}")
    
    def is_running(self) -> bool:
        """Check if the window process is currently running.
        
        Returns:
            True if running, False otherwise.
        """
        return self._process is not None and self._process.poll() is None
    
    def send_command(self, command: str) -> bool:
        """Send a command to the window process via socket.
        
        Args:
            command: Command string to send (e.g., "focus", "hide", "close").
        
        Returns:
            True if command was sent successfully, False otherwise.
        """
        if not self.is_running():
            logger.debug("Cannot send command: window process not running")
            return False
        
        logger.debug(f"Attempting to send command '{command}' via pipe: {self._control_socket_path}")
        
        try:
            if sys.platform == "win32":
                # Windows: use named pipe
                import win32file
                import win32pipe
                
                try:
                    handle = win32file.CreateFile(
                        self._control_socket_path,
                        win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                        0,
                        None,
                        win32file.OPEN_EXISTING,
                        0,
                        None,
                    )
                    win32file.WriteFile(handle, command.encode('utf-8'))
                    win32file.CloseHandle(handle)
                    logger.debug(f"Command '{command}' sent to window process")
                    return True
                except Exception as e:
                    logger.error(f"Failed to send command via named pipe: {e}")
                    logger.error(f"Pipe path: {self._control_socket_path}")
                    return False
            else:
                # Unix: use Unix domain socket
                import socket
                
                client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    client.connect(self._control_socket_path)
                    client.sendall(command.encode('utf-8'))
                    logger.debug(f"Command '{command}' sent to window process")
                    return True
                except Exception as e:
                    logger.error(f"Failed to send command via Unix socket: {e}")
                    return False
                finally:
                    client.close()
        except Exception as e:
            logger.error(f"Failed to send command '{command}': {e}")
            return False


class WebViewAPI:
    """API exposed to the webview for external links and file downloads."""

    def open_external_link(self, url: str) -> None:
        """Open URL in system's default browser."""
        if not url.startswith(("http://", "https://")):
            return
        import webbrowser

        webbrowser.open(url)

    def save_file(self, url: str, filename: str) -> bool:
        """Download a file from *url* and save it via a native save dialog.

        Args:
            url: Full HTTP(S) URL of the file to download.
            filename: Default filename shown in the save dialog.

        Returns:
            True if the file was saved successfully, False if the user
            cancelled the dialog or an error occurred.
        """
        import re
        import shutil
        import urllib.request

        if not url.startswith(("http://", "https://")):
            return False

        # Sanitize filename
        safe_name = re.sub(r'[<>:"/\\|?*]', "_", filename).strip(" .")

        try:
            # Show native OS save dialog via pywebview
            result = webview.windows[0].create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=safe_name,
            )
            if not result:
                return False  # user cancelled

            dest_path = result if isinstance(result, str) else result[0]

            # Download from the local backend and write to chosen path
            with urllib.request.urlopen(url) as response:
                with open(dest_path, "wb") as f:
                    shutil.copyfileobj(response, f)

            return True
        except Exception:
            logger.exception("save_file failed")
            return False


def _run_webview_window(url: str, log_level: str, control_socket_path: str) -> None:
    """Run webview window in a separate process.
    
    This function is designed to run in its own process so that closing
    the window doesn't affect the tray icon or backend process.
    
    Args:
        url: URL to load in the webview.
        log_level: Log level for the process.
        control_socket_path: Path to the control socket for IPC.
    """
    # Setup logger for this process
    setup_logger(log_level)
    logger.info(f"WebView process starting with URL: {url}")
    logger.info(f"Control socket path received: {control_socket_path}")
    
    if not webview:
        logger.error("pywebview not available")
        return

    # for IPC server
    # Start socket server in a background thread
    def socket_server():
        """Listen for commands from the tray process."""
        if sys.platform == "win32":
            # Windows: use named pipe
            import win32file
            import win32pipe
            import pywintypes
            
            try:
                logger.info(f"Named pipe server created: {control_socket_path}")
                
                # Keep accepting connections until window closes
                while True:
                    # Create a new pipe instance
                    pipe = win32pipe.CreateNamedPipe(
                        control_socket_path,
                        win32pipe.PIPE_ACCESS_DUPLEX,
                        win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                        1,  # max instances
                        65536,  # output buffer size
                        65536,  # input buffer size
                        0,  # default timeout
                        None,
                    )
                    
                    # Wait for client connection (blocking)
                    win32pipe.ConnectNamedPipe(pipe, None)
                    logger.debug("Client connected to named pipe")
                    
                    # Read commands until this connection closes
                    try:
                        while True:
                            result = win32file.ReadFile(pipe, 64*1024)
                            if result[0] == 0:  # success
                                command = result[1].decode('utf-8').strip()
                                logger.debug(f"Received command: {command}")
                                
                                # Execute command
                                if command == "focus":
                                    if webview.windows:
                                        window = webview.windows[0]
                                        logger.info("Focusing window...")
                                        
                                        # Step 1: Show the window (if hidden)
                                        window.show()
                                        
                                        # Step 2: Restore if minimized
                                        window.restore()
                                        
                                        # Small delay to ensure window is ready
                                        time.sleep(0.05)  # 50ms
                                        
                                        # Step 3: Bring to foreground using native Windows API
                                        try:
                                            import ctypes
                                            from ctypes import wintypes
                                            user32 = ctypes.windll.user32
                                            hwnd = window.native.Handle.ToInt32()
                                            
                                            # Method 1: Try AllowSetForegroundWindow + SetForegroundWindow
                                            user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
                                            result = user32.SetForegroundWindow(hwnd)
                                            
                                            if result:
                                                logger.info("Window brought to foreground (method 1)")
                                            else:
                                                logger.debug("SetForegroundWindow failed, trying method 2...")
                                                
                                                # Method 2: Use ShowWindow with SW_RESTORE and SW_SHOW
                                                SW_RESTORE = 9
                                                SW_SHOW = 5
                                                user32.ShowWindow(hwnd, SW_RESTORE)
                                                user32.ShowWindow(hwnd, SW_SHOW)
                                                
                                                # Try SetForegroundWindow again
                                                result = user32.SetForegroundWindow(hwnd)
                                                if result:
                                                    logger.info("Window brought to foreground (method 2)")
                                                else:
                                                    # Method 3: Use SetActiveWindow + SetFocus
                                                    user32.SetActiveWindow(hwnd)
                                                    user32.SetFocus(hwnd)
                                                    
                                                    # Bring to top of Z-order
                                                    user32.BringWindowToTop(hwnd)
                                                    logger.debug("Window activated with SetActiveWindow + SetFocus")
                                            
                                            # Always bring to top of Z-order
                                            user32.BringWindowToTop(hwnd)
                                            
                                        except Exception as e:
                                            logger.error(f"Failed to bring window to foreground: {e}")
                                    else:
                                        logger.warning("No window available to focus")
                                elif command == "hide":
                                    if webview.windows:
                                        webview.windows[0].hide()
                                        logger.info("Window hidden")
                                elif command == "close":
                                    if webview.windows:
                                        webview.windows[0].destroy()
                                    break
                                elif command == "quit":
                                    if webview.windows:
                                        webview.windows[0].destroy()
                                    break
                    except Exception as e:
                        logger.debug(f"Connection closed: {e}")
                    finally:
                        win32file.CloseHandle(pipe)
                        logger.debug("Pipe instance closed")
                    
                    # Check if we should exit the outer loop too
                    if not webview.windows:
                        break
                
                logger.info("Named pipe server shutting down")
            except Exception as e:
                logger.error(f"Named pipe server error: {e}")
        else:
            # Unix: use Unix domain socket
            import socket
            import os
            
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                # Remove existing socket file if it exists
                if os.path.exists(control_socket_path):
                    os.remove(control_socket_path)
                
                sock.bind(control_socket_path)
                sock.listen(1)
                logger.debug(f"Unix socket server created: {control_socket_path}")
                
                conn, _ = sock.accept()
                logger.debug("Client connected to Unix socket")
                
                while True:
                    try:
                        data = conn.recv(4096)
                        if not data:
                            break
                        command = data.decode('utf-8').strip()
                        logger.debug(f"Received command: {command}")
                        
                        # Execute command
                        if command == "focus":
                            if webview.windows:
                                window = webview.windows[0]
                                window.show()
                                window.restore()
                        elif command == "hide":
                            if webview.windows:
                                webview.windows[0].hide()
                        elif command == "close":
                            if webview.windows:
                                webview.windows[0].destroy()
                            break
                        elif command == "quit":
                            if webview.windows:
                                webview.windows[0].destroy()
                            break
                    except Exception as e:
                        logger.debug(f"Error reading from socket: {e}")
                        break
                
                conn.close()
                logger.debug("Unix socket connection closed")
            except Exception as e:
                logger.error(f"Unix socket server error: {e}")
            finally:
                sock.close()
                if os.path.exists(control_socket_path):
                    os.remove(control_socket_path)
    
    # Start socket server in a background thread
    # Use daemon=True so it exits when the main thread exits
    socket_thread = threading.Thread(target=socket_server, daemon=True)
    socket_thread.start()
    logger.debug("Socket server thread started")
    
    # Create and run webview
    api = WebViewAPI()
    window = webview.create_window(
        "QwenPaw",
        url,
        width=1280,
        height=800,
        text_select=True,
        js_api=api,
    )
    
    # Note: pywebview on Windows doesn't support setting window icon at runtime.
    # The icon can only be set during packaging (e.g., PyInstaller).
    # Window will use the default icon, but tray icon and taskbar will still work.
    
    # Intercept window close button to hide instead of close
    def on_closing():
        """Called when user clicks the window close button.
        
        Instead of destroying the window, hide it to tray.
        This makes the window behave like a typical tray application.
        
        Returns:
            False to cancel the close operation (pywebview convention).
        """
        logger.info("Window close button clicked - hiding to tray instead")
        # Hide the window
        window.hide()
        # Return False to CANCEL the close operation
        # (pywebview: False = prevent closing, True = allow closing)
        return False
    
    # Register the closing event handler
    if hasattr(window, 'events') and hasattr(window.events, 'closing'):
        window.events.closing += on_closing
        logger.debug("Window closing event handler registered")
    
    logger.info("WebView window created, calling webview.start()...")
    webview.start(private_mode=False)
    logger.info("WebView window closed")


@click.command("desktop-systray")
@click.option(
    "--host",
    default="127.0.0.1",
    show_default=True,
    help="Bind host for the app server.",
)
@click.option(
    "--port",
    default=None,
    type=int,
    show_default=True,
    help="Bind port for the app server (auto-selected if not specified).",
)
@click.option(
    "--log-level",
    default="info",
    type=click.Choice(
        ["critical", "error", "warning", "info", "debug", "trace"],
        case_sensitive=False,
    ),
    show_default=True,
    help="Log level for the app process.",
)
def desktop_systray_cmd(
    host: str,
    port: int | None,
    log_level: str,
) -> None:
    """Run QwenPaw app with system tray icon.

    Starts the FastAPI app in a subprocess, opens a native webview window
    in a separate process, and displays a system tray icon for quick access.
    The window can be minimized to tray and restored from the tray menu.
    Closing the window does not quit the application - use the tray menu to exit.
    """
    # Setup logger
    setup_logger(log_level)

    # Initialize process managers
    app_proc = AppProcess(host=host, port=port, log_level=log_level)
    window_mgr: Optional[WindowProcess] = None
    tray_icon_mgr: Optional[TrayIconManager] = None
    should_exit = False

    def show_window() -> None:
        """Show or restore the webview window.
        
        If the window process is not running (closed or never started),
        start a new window process. Otherwise, send a focus command to
        bring the existing window to the front.
        
        This is the default behavior when:
        - User double-clicks tray icon
        - User selects "Show Window" from tray menu
        """
        nonlocal window_mgr
        if window_mgr is None:
            logger.warning("Window manager not initialized")
            return
        
        if window_mgr.is_running():
            logger.info("Window is running, sending focus command...")
            # Send focus command via IPC
            if window_mgr.send_command("focus"):
                logger.info("Focus command sent to window")
            else:
                logger.warning("Failed to send focus command")
        else:
            logger.info("Window was closed, starting new window process...")
            window_mgr.start()

    def hide_window() -> None:
        """Hide the webview window by sending a hide command.
        
        This does NOT stop the window process - the window is just hidden
        and can be shown again. The window process continues running in
        the background.
        
        This is used when:
        - User selects "Hide Window" from tray menu
        - User clicks window close button (intercepted to hide instead)
        """
        nonlocal window_mgr
        if window_mgr is None:
            logger.warning("Window manager not initialized")
            return
        
        if window_mgr.is_running():
            logger.info("Sending hide command to window...")
            if window_mgr.send_command("hide"):
                logger.info("Hide command sent to window")
            else:
                logger.warning("Failed to send hide command")
        else:
            logger.debug("Window already stopped")

    def quit_app() -> None:
        """Quit the entire application."""
        nonlocal should_exit
        logger.info("Quitting application...")
        should_exit = True
        if tray_icon_mgr:
            tray_icon_mgr.stop()

    # Initialize tray icon manager
    tray_icon_mgr = TrayIconManager(
        on_show_window=show_window,
        on_hide_window=hide_window,
        on_quit=quit_app,
    )

    # Start app process
    if not app_proc.start():
        logger.error("Failed to start app process")
        sys.exit(1)

    url = app_proc.get_url()
    click.echo(f"Starting QwenPaw app on {url}")

    # Initialize window manager
    if webview:
        window_mgr = WindowProcess(url=url, log_level=log_level)
        logger.info("Starting initial window process...")
        window_mgr.start()
    else:
        logger.warning("pywebview not available, no window will be shown")

    # Define setup function for tray icon
    def tray_setup(icon: pystray.Icon) -> None:
        """Setup callback executed when tray icon is ready."""
        logger.info("Tray icon ready")
        # Icon is visible by default
        icon.visible = True

    # Run tray icon on main thread (blocking)
    try:
        tray_icon_mgr.run(setup=tray_setup)
    except Exception as e:
        logger.error(f"Tray icon error: {e}")
    finally:
        # Cleanup
        logger.info("Cleaning up...")
        should_exit = True

        # Stop window process
        if window_mgr:
            logger.info("Stopping window process...")
            window_mgr.stop()

        # Stop app process
        app_proc.stop()

        logger.info("Application exited")
