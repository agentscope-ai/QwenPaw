# -*- coding: utf-8 -*-
"""Keep Windows PTY handles and console control outside the server process."""

import ctypes
import importlib
import multiprocessing
import threading
import time

import psutil


def interrupt_console(pid):
    """Send Ctrl+C only from the isolated worker to its shell's console."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.FreeConsole()
    if not kernel.AttachConsole(pid):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not kernel.SetConsoleCtrlHandler(None, True):
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel.GenerateConsoleCtrlEvent(0, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        # Control handlers run asynchronously; stay attached for delivery.
        time.sleep(0.1)
    finally:
        kernel.FreeConsole()


def write_input(process, data):
    """Preserve text order while translating ETX into a console event."""
    parts = data.split("\x03")
    for index, part in enumerate(parts):
        if index:
            interrupt_console(process.pid)
        if part:
            process.write(part)


def pty_worker(control, output, command, cwd, env, dimensions):
    """Own one native PTY; process exit releases its OS handles as well."""
    try:
        native = importlib.import_module("winpty").PtyProcess
        process = native.spawn(
            command,
            cwd=cwd,
            env=env,
            dimensions=dimensions,
        )
        control.send((True, process.pid))

        def read_output():
            try:
                while True:
                    data = process.read(4096)
                    if data:
                        output.send(data)
            except (EOFError, OSError):
                pass
            finally:
                output.close()

        threading.Thread(target=read_output, daemon=True).start()
        while True:
            operation, args = control.recv()
            try:
                if operation == "write":
                    write_input(process, *args)
                    result = None
                elif operation == "resize":
                    process.setwinsize(*args)
                    result = None
                elif operation == "status":
                    result = (process.isalive(), process.exitstatus)
                else:
                    raise ValueError("Unknown terminal operation")
                control.send((True, result))
            except Exception as exc:
                control.send((False, str(exc)))
    except (EOFError, OSError):
        pass
    except Exception as exc:
        control.send((False, str(exc)))
    finally:
        control.close()
        output.close()


class WindowsPty:
    """A synchronous adapter over a dedicated, disposable PTY worker."""

    def __init__(self, worker, control, output):
        self.worker = worker
        self.control = control
        self.output = output
        self.lock = threading.Lock()
        self.exitstatus = None
        self.closed = False
        try:
            self.owner = psutil.Process(worker.pid)
        except psutil.NoSuchProcess:
            self.owner = None
        self.pid = None

    @staticmethod
    def unavailable_reason():
        """Missing or broken native wheels disable only the terminal."""
        try:
            importlib.import_module("winpty")
        except (ImportError, OSError):
            return "dependency_missing"
        return None

    @classmethod
    def spawn(cls, command, cwd, env, dimensions):
        """Start with spawn, never fork a multithreaded application."""
        if cls.unavailable_reason():
            raise OSError("Install pywinpty in the backend Python environment")
        context = multiprocessing.get_context("spawn")
        control, child_control = context.Pipe()
        output, child_output = context.Pipe(duplex=False)
        worker = context.Process(
            target=pty_worker,
            args=(child_control, child_output, command, cwd, env, dimensions),
            daemon=True,
        )
        try:
            worker.start()
        except BaseException:
            control.close()
            output.close()
            raise
        finally:
            child_control.close()
            child_output.close()
        adapter = cls(worker, control, output)
        try:
            adapter.pid = adapter._receive(35)
        except BaseException:
            adapter.close()
            raise
        return adapter

    def _receive(self, timeout=5):
        if not self.control.poll(timeout):
            raise OSError("Terminal worker did not respond")
        try:
            ok, result = self.control.recv()
        except EOFError as exc:
            raise OSError("Terminal worker exited") from exc
        if not ok:
            raise OSError(result)
        return result

    def _call(self, operation, *args):
        try:
            with self.lock:
                if self.closed:
                    raise OSError("Terminal worker closed")
                self.control.send((operation, args))
                return self._receive()
        except (EOFError, OSError):
            # A timed-out reply must not be consumed by the next request.
            self.close()
            raise

    def read(self, _size):
        """The worker sends bounded decoded output frames."""
        return self.output.recv()

    def write(self, text):
        self._call("write", text)

    def setwinsize(self, rows, cols):
        self._call("resize", rows, cols)

    def isalive(self):
        if self.closed or not self.worker.is_alive():
            return False
        alive, self.exitstatus = self._call("status")
        return alive

    def close(self, force=True):
        """Reclaim only this worker's descendants, never named processes."""
        del force
        with self.lock:
            if self.closed:
                return
            self.closed = True
            try:
                children = (
                    self.owner.children(recursive=True) if self.owner else []
                )
            except psutil.Error:
                children = []
            for child in reversed(children):
                try:
                    child.kill()
                except psutil.Error:
                    pass
            if self.worker.is_alive():
                self.worker.terminate()
            self.worker.join(timeout=3)
            if self.worker.is_alive():
                self.worker.kill()
                self.worker.join(timeout=3)
            psutil.wait_procs(children, timeout=2)
            self.control.close()
            self.output.close()
            if not self.worker.is_alive():
                self.worker.close()
