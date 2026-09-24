# -*- coding: utf-8 -*-
"""POSIX PTY adapter with isolated descriptors and no preexec callback."""

import codecs
import fcntl
import os
import select
import struct
import subprocess
import termios
import threading


IO_POLL_INTERVAL = 0.1


class PosixPty:
    """Open a controlling terminal without running Python after fork."""

    def __init__(self, process, master):
        self.process = process
        self.pid = process.pid
        self.fd = master
        self.exitstatus = None
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.closing = threading.Event()
        os.set_blocking(master, False)

    @classmethod
    def spawn(cls, command, cwd, env, dimensions):
        """Start an interactive shell in a new session and controlling tty."""
        master, slave = os.openpty()
        try:
            fcntl.ioctl(
                slave,
                termios.TIOCSWINSZ,
                struct.pack("HHHH", *dimensions, 0, 0),
            )
            # Reopen the slave after setsid to acquire a controlling tty.
            # Paths are arguments, never interpolated shell source. Popen
            # closes unrelated FDs in the child, without a
            # race-prone parent FD snapshot or Python preexec_fn callback.
            argv = [
                "/bin/sh",
                "-c",
                'exec < "$1" > "$1" 2>&1; shift; '
                'cd -- "$1" && shift && exec "$@"',
                "qwenpaw-terminal",
                os.ttyname(slave),
                cwd,
                *command,
            ]
            # The adapter owns this process until close(), beyond spawn().
            process = subprocess.Popen(  # pylint: disable=consider-using-with
                argv,
                env=env,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                close_fds=True,
                start_new_session=True,
            )
        except BaseException:
            os.close(master)
            raise
        finally:
            os.close(slave)
        return cls(process, master)

    def read(self, size):
        """Decode output incrementally, tolerating arbitrary program bytes."""
        while not self.closing.is_set():
            readable, _, _ = select.select(
                [self.fd],
                [],
                [],
                IO_POLL_INTERVAL,
            )
            if not readable:
                continue
            try:
                data = os.read(self.fd, size)
            except BlockingIOError:
                continue
            if not data:
                break
            return self.decoder.decode(data)
        raise EOFError()

    def write(self, text):
        """Handle partial writes while allowing teardown to cancel waits."""
        data = text.encode("utf-8")
        while data:
            if self.closing.is_set():
                raise OSError("Terminal is closing")
            try:
                count = os.write(self.fd, data)
            except BlockingIOError:
                select.select(
                    [],
                    [self.fd],
                    [],
                    IO_POLL_INTERVAL,
                )
                continue
            data = data[count:]

    def cancel_write(self):
        """Wake bounded write retries before the descriptor is closed."""
        self.closing.set()

    def setwinsize(self, rows, cols):
        """Notify the foreground process group of terminal size changes."""
        fcntl.ioctl(
            self.fd,
            termios.TIOCSWINSZ,
            struct.pack("HHHH", rows, cols, 0, 0),
        )

    def isalive(self):
        """Reap exited shells and retain their exit status."""
        self.exitstatus = self.process.poll()
        return self.exitstatus is None

    def close(self, force=True):
        """Release the master descriptor after the manager stops the tree."""
        if self.fd < 0:
            return
        self.closing.set()
        if force and self.isalive():
            try:
                self.process.kill()
            except ProcessLookupError:
                pass
        os.close(self.fd)
        self.fd = -1
        self.exitstatus = self.process.wait()
