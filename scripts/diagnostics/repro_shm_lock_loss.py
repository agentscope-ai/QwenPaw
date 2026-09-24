# -*- coding: utf-8 -*-
"""Isolated Linux reproduction. Creates only temporary databases.

Run in a disposable Linux container. The opener instruments SQLite's VFS
ftruncate syscall to pause AFTER SQLite itself truncates shm to 3 bytes.
This widens the race deterministically; it does not force a truncation.
Expected SIGBUS is confined to child processes. Core dumps are disabled.
"""

import ast
import ctypes
import ctypes.util
import io
import json
import logging
import os
from pathlib import Path
import resource
import runpy
import sqlite3
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import zipfile


def emit(**values):
    print(json.dumps(values), flush=True)


def locks(path):
    inode = str(os.stat(path).st_ino)
    return [
        line.strip()
        for line in Path("/proc/locks")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.split()[5].split(":")[-1] == inode
    ]


def opener(path):
    # sqlite3_vfs version 3 ABI, through xNextSystemCall.
    methods = (
        "xOpen xDelete xAccess xFullPathname xDlOpen xDlError "
        "xDlSym xDlClose xRandomness xSleep xCurrentTime xGetLastError "
        "xCurrentTimeInt64 xSetSystemCall xGetSystemCall xNextSystemCall"
    )

    class Vfs(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_int)
            for name in ("iVersion", "szOsFile", "mxPathname")
        ] + [
            (name, ctypes.c_void_p)
            for name in ("pNext zName pAppData " + methods).split()
        ]

    lib = ctypes.CDLL(ctypes.util.find_library("sqlite3"))
    lib.sqlite3_vfs_find.restype = ctypes.POINTER(Vfs)
    lib.sqlite3_vfs_find.argtypes = [ctypes.c_char_p]
    vfs = lib.sqlite3_vfs_find(None)
    assert vfs.contents.iVersion >= 3
    get_syscall = ctypes.CFUNCTYPE(
        ctypes.c_void_p,
        ctypes.POINTER(Vfs),
        ctypes.c_char_p,
    )(vfs.contents.xGetSystemCall)
    truncate_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_long)
    original = truncate_type(get_syscall(vfs, b"ftruncate"))

    @truncate_type
    def instrumented(fd, size):
        result = original(fd, size)
        if size == 3 and result == 0:
            emit(
                event="sqlite_truncated",
                size=os.fstat(fd).st_size,
                inode=os.fstat(fd).st_ino,
                fd_target=os.readlink(f"/proc/self/fd/{fd}"),
            )
            # Parent either releases us or dies, closing the pipe.
            if not sys.stdin.readline():
                # Holder died as expected; avoid a secondary broken-pipe error.
                os._exit(0)
        return result

    set_syscall = ctypes.CFUNCTYPE(
        ctypes.c_int,
        ctypes.POINTER(Vfs),
        ctypes.c_char_p,
        ctypes.c_void_p,
    )(vfs.contents.xSetSystemCall)
    assert (
        set_syscall(
            vfs,
            b"ftruncate",
            ctypes.cast(instrumented, ctypes.c_void_p),
        )
        == 0
    )
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.execute("SELECT count(*) FROM events").fetchone()
    emit(event="opened_without_truncation")
    sys.stdin.readline()
    conn.close()


def product_backup(root):
    # Execute the actual repository function without importing app dependencies.
    source = Path(
        "/repo/src/qwenpaw/backup/_ops/create_helpers.py",
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "add_agent_workspaces"
    )
    snapshot_module = runpy.run_path(
        "/repo/src/qwenpaw/backup/_ops/sqlite_snapshot.py",
    )
    namespace = {
        "zipfile": zipfile,
        "Path": Path,
        "Any": object,
        "tempfile": tempfile,
        "stage_databases": snapshot_module["stage_databases"],
        "logger": logging.getLogger("repro"),
        "PREFIX_WORKSPACES": "workspaces/",
    }
    exec(
        compile(
            ast.Module(body=[function], type_ignores=[]),
            "product_create_helpers.py",
            "exec",
        ),
        namespace,
    )
    with zipfile.ZipFile(io.BytesIO(), "w", zipfile.ZIP_DEFLATED) as archive:
        namespace["add_agent_workspaces"](
            archive,
            [("test", SimpleNamespace(workspace_dir=root))],
        )
        emit(backup_members=archive.namelist())


def holder(case):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    with tempfile.TemporaryDirectory(prefix="shm-lock-repro-") as root:
        path = str(Path(root) / "history.db")
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute("CREATE TABLE events(payload BLOB)")
        conn.executemany(
            "INSERT INTO events VALUES (?)",
            [(b"x" * 4096,)] * 400,
        )
        conn.commit()
        shm = path + "-shm"
        emit(case=case, phase="before", locks=locks(shm))
        if case == "same_process_read":
            Path(shm).read_bytes()
        elif case == "external_process_read":
            subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; import sys; "
                    "Path(sys.argv[1]).read_bytes()",
                    shm,
                ],
                check=True,
            )
        elif case == "stat_only":
            os.stat(shm)
        elif case == "product_backup":
            errors = []

            def backup():
                try:
                    product_backup(root)
                except BaseException as exc:
                    errors.append(exc)

            thread = threading.Thread(target=backup)
            thread.start()
            thread.join()
            if errors:
                raise errors[0]
        emit(case=case, phase="after", locks=locks(shm))
        with subprocess.Popen(
            [sys.executable, __file__, "opener", path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        ) as child:
            try:
                event = child.stdout.readline().strip()
                assert event, "opener exited without a result"
                emit(case=case, opener=json.loads(event))
                # Actual sqlite3 query, not an artificial mmap access.
                result = conn.execute(
                    "SELECT sum(length(payload)) FROM events",
                ).fetchone()
                emit(case=case, query_result=result)
            finally:
                child.communicate("\n", timeout=10)
        conn.close()


def main():
    emit(sqlite_version=sqlite3.sqlite_version, platform=sys.platform)
    cases = [
        "baseline",
        "stat_only",
        "external_process_read",
        "same_process_read",
        "product_backup",
    ]
    for case in cases:
        result = subprocess.run(
            [sys.executable, __file__, "holder", case],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        print(result.stdout, end="", flush=True)
        emit(case=case, returncode=result.returncode, stderr=result.stderr)
        expected = -7 if case == "same_process_read" else 0
        if result.returncode != expected:
            raise SystemExit(
                f"{case}: expected {expected}, got {result.returncode}",
            )


if __name__ == "__main__":
    if len(sys.argv) == 1:
        main()
    elif sys.argv[1] == "holder":
        holder(sys.argv[2])
    elif sys.argv[1] == "opener":
        opener(sys.argv[2])
