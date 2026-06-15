# -*- coding: utf-8 -*-
"""
QwenPaw Desktop Launcher (Python + tkinter)

Shows loading window immediately, then starts Python backend.
Once backend is ready, opens the actual app window.
"""

import os
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk


class QwenPawLauncher:
    """Native launcher for QwenPaw Desktop."""

    def __init__(self):
        self.backend_host = "127.0.0.1"
        self.backend_port = 0
        self.backend_process = None
        self.root = None
        self.loading_label = None
        self.progress_bar = None

    def find_free_port(self):
        """Find a free port on localhost."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((self.backend_host, 0))
            sock.listen(1)
            return sock.getsockname()[1]

    def is_backend_ready(self):
        """Check if backend is accepting connections."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1.0)
                sock.connect((self.backend_host, self.backend_port))
                return True
        except (socket.error, OSError):
            return False

    def create_loading_window(self):
        """Create and show loading window."""
        self.root = tk.Tk()
        self.root.title("QwenPaw Desktop")
        self.root.geometry("600x400")
        self.root.resizable(False, False)
        self.root.configure(bg="white")

        # Center window
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - (600 // 2)
        y = (self.root.winfo_screenheight() // 2) - (400 // 2)
        self.root.geometry(f"+{x}+{y}")

        # Title
        title_label = tk.Label(
            self.root,
            text="QwenPaw",
            font=("Segoe UI", 32, "bold"),
            fg="#404040",
            bg="white",
        )
        title_label.pack(pady=(80, 20))

        # Loading message
        self.loading_label = tk.Label(
            self.root,
            text="正在启动...",
            font=("Segoe UI", 12),
            fg="#808080",
            bg="white",
        )
        self.loading_label.pack(pady=20)

        # Progress bar
        self.progress_bar = ttk.Progressbar(
            self.root,
            mode="indeterminate",
            length=400,
        )
        self.progress_bar.pack(pady=20)
        self.progress_bar.start(30)

        # Version
        version_label = tk.Label(
            self.root,
            text="v1.1.11",
            font=("Segoe UI", 9),
            fg="#c0c0c0",
            bg="white",
        )
        version_label.pack(side="bottom", pady=20)

        return self.root

    def start_backend(self):
        """Start Python backend process."""
        python_exe = sys.executable

        if not os.path.exists(python_exe):
            raise FileNotFoundError(
                f"Python executable not found: {python_exe}",
            )

        env = os.environ.copy()
        env["QWENPAW_LOG_LEVEL"] = "info"

        cmd = [
            python_exe,
            "-m", "qwenpaw", "app",
            "--host", self.backend_host,
            "--port", str(self.backend_port),
            "--log-level", "info",
        ]

        # pylint: disable=consider-using-with
        # Cannot use 'with' here: process must live beyond this method
        # so it can be terminated in the finally block of run().
        self.backend_process = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if sys.platform == "win32" else 0
            ),
        )

        print(f"Backend process started (PID: {self.backend_process.pid})")

    def wait_for_backend(self, timeout_seconds=60):
        """Wait for backend to be ready."""
        start_time = time.time()

        while time.time() - start_time < timeout_seconds:
            if self.is_backend_ready():
                return True

            elapsed = int(time.time() - start_time)
            if self.loading_label:
                self.loading_label.config(
                    text=f"正在启动... ({elapsed}s)",
                )
                self.root.update()

            time.sleep(0.5)

        return False

    def open_backend_app(self):
        """Open the actual app window using pywebview."""
        url = f"http://{self.backend_host}:{self.backend_port}"
        print(f"Opening backend at: {url}")

        python_exe = sys.executable

        webview_script = (
            f"import webview; "
            f"webview.create_window('QwenPaw Desktop', '{url}', "
            f"width=1280, height=800); "
            f"webview.start()"
        )

        # pylint: disable=consider-using-with
        # Short-lived process; no cleanup needed beyond return.
        app_process = subprocess.Popen(
            [python_exe, "-c", webview_script],
        )

        return app_process

    def run(self):
        """Main launcher logic."""
        try:
            print("QwenPaw Desktop Launcher starting...")

            # Find free port
            self.backend_port = self.find_free_port()
            print(f"Using port: {self.backend_port}")

            # Create and show loading window
            self.create_loading_window()
            self.root.update()

            # Start backend in background thread
            backend_thread = threading.Thread(
                target=self.start_backend, daemon=True,
            )
            backend_thread.start()

            # Wait for backend
            print("Waiting for backend to be ready...")
            ready = self.wait_for_backend(timeout_seconds=60)

            if ready:
                print("Backend is ready!")
                self.loading_label.config(text="启动完成，正在打开...")
                self.root.update()

                time.sleep(0.5)

                # Close loading window
                self.root.destroy()

                # Open actual app
                app_process = self.open_backend_app()

                # Wait for app to close
                if app_process:
                    app_process.wait()
            else:
                print("Backend failed to start within timeout")
                self.loading_label.config(text="启动失败，请重试", fg="red")
                self.root.update()
                time.sleep(3)
                self.root.destroy()

        except Exception as e:
            print(f"Launcher error: {e}")
            if self.root:
                self.loading_label.config(text=f"错误: {e}", fg="red")
                self.root.update()
                time.sleep(3)
                self.root.destroy()

        finally:
            # Cleanup backend process
            if self.backend_process and self.backend_process.poll() is None:
                print("Stopping backend process...")
                self.backend_process.terminate()
                try:
                    self.backend_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.backend_process.kill()


if __name__ == "__main__":
    launcher = QwenPawLauncher()
    launcher.run()
