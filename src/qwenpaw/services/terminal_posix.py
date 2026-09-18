# -*- coding: utf-8 -*-
"""POSIX PTY adapter using spawn instead of Python code after fork."""

import codecs
import fcntl
import os
import signal
import struct
import termios


class PosixPty:
    """Open a controlling terminal with async-signal-safe spawn actions."""

    def __init__(self, pid, master):
        self.pid = pid
        self.fd = master
        self.exitstatus = None
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")

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
            actions = [
                (os.POSIX_SPAWN_CLOSE, master),
                (os.POSIX_SPAWN_CLOSE, slave),
                (os.POSIX_SPAWN_OPEN, 0, os.ttyname(slave), os.O_RDWR, 0),
                (os.POSIX_SPAWN_DUP2, 0, 1),
                (os.POSIX_SPAWN_DUP2, 0, 2),
            ]
            # Python 3.11/3.12 expose no spawn chdir action. Paths travel as
            # positional arguments, never as interpolated shell source.
            argv = [
                "/bin/sh",
                "-c",
                'cd -- "$1" && shift && exec "$@"',
                "qwenpaw-terminal",
                cwd,
                *command,
            ]
            pid = os.posix_spawn(
                "/bin/sh",
                argv,
                env,
                file_actions=actions,
                setsid=True,
                setsigdef=(signal.SIGINT, signal.SIGQUIT, signal.SIGPIPE),
                setsigmask=(),
            )
        except BaseException:
            os.close(master)
            raise
        finally:
            os.close(slave)
        return cls(pid, master)

    def read(self, size):
        """Decode output incrementally, tolerating arbitrary program bytes."""
        data = os.read(self.fd, size)
        if not data:
            raise EOFError()
        return self.decoder.decode(data)

    def write(self, text):
        """Handle short OS writes without dropping pasted input."""
        data = text.encode("utf-8")
        while data:
            count = os.write(self.fd, data)
            data = data[count:]

    def setwinsize(self, rows, cols):
        """Notify the foreground process group of terminal size changes."""
        fcntl.ioctl(
            self.fd,
            termios.TIOCSWINSZ,
            struct.pack("HHHH", rows, cols, 0, 0),
        )

    def isalive(self):
        """Reap exited shells and retain their exit status."""
        if self.exitstatus is not None:
            return False
        try:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            return False
        if pid:
            self.exitstatus = os.waitstatus_to_exitcode(status)
            return False
        return True

    def close(self, force=True):
        """Release the master descriptor after the manager stops the tree."""
        if self.fd < 0:
            return
        if force and self.isalive():
            try:
                os.kill(self.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        os.close(self.fd)
        self.fd = -1
        try:
            _, status = os.waitpid(self.pid, 0)
            self.exitstatus = os.waitstatus_to_exitcode(status)
        except ChildProcessError:
            pass
