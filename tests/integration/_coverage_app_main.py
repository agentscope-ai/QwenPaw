# -*- coding: utf-8 -*-
"""Coverage-mode app launcher for Windows integration tests.

Launches the same server as ``python -m qwenpaw app`` (same CLI entry,
same argv layout), but first maps SIGBREAK to KeyboardInterrupt.

Why this wrapper exists (Windows-only, coverage mode only):

The integration fixture stops the app subprocess with CTRL_BREAK_EVENT
so the child can run its atexit handlers and flush subprocess coverage
data.  But CPython only installs a Python-level handler for SIGINT
(see ``Modules/signalmodule.c`` init: ``set_handler(SIGINT, ...)``);
SIGBREAK keeps the CRT default action, and neither uvicorn (handles
SIGINT/SIGTERM only) nor QwenPaw registers a SIGBREAK handler.  The
default action terminates the process immediately -- atexit never runs,
so coverage's save never happens and all recorded data is dropped.
Forensics proof (fork run 31671241854): every app's tracer was active
(per-app debug logs with ``Tracing '...qwenpaw...'`` dispositions), yet
main-process saves never materialized and the combined data held 752
files with 0 executed lines, while the identical mechanism on
ubuntu/macos recorded ~53k lines.

Raising KeyboardInterrupt instead puts the shutdown on the exact same
graceful path POSIX enjoys with SIGINT: uvicorn unwinds, the interpreter
exits normally, atexit runs, coverage flushes.

This file is only used when ``QWENPAW_INTEGRATION_COVERAGE`` is enabled
on ``win32``; the normal (non-coverage) launch command is unchanged.
"""
import runpy
import signal
import sys


def _sigbreak_to_keyboard_interrupt(signum, frame):
    raise KeyboardInterrupt


if hasattr(signal, "SIGBREAK"):
    signal.signal(signal.SIGBREAK, _sigbreak_to_keyboard_interrupt)

# Emulate ``python -m qwenpaw app <args...>``.  The fixture invokes this
# wrapper as ``python _coverage_app_main.py app --host ...``, so the
# subcommand and its flags are already in sys.argv[1:]; only argv[0]
# (the wrapper path) needs replacing with the program name.
sys.argv = ["qwenpaw", *sys.argv[1:]]
runpy.run_module("qwenpaw", run_name="__main__")
