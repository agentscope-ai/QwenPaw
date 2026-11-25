# -*- coding: utf-8 -*-
"""Publish backend-owned POSIX sessions across parent exit and reparenting."""

from __future__ import annotations

import json
import logging
import os
import re
import stat
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


_OWNER = "QWENPAW_BACKEND_INSTANCE"
_backend_key = None
logger = logging.getLogger(__name__)


def _instance(process):
    return f"{process.pid}-{int(process.create_time() * 1_000_000)}"


def _directory():
    # GUI and terminal launchers can have different TMPDIR values on macOS.
    directory = Path("/tmp") / f"qwenpaw-shutdown-{os.getuid()}"
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
    ):
        raise PermissionError("Backend ownership directory is not private")
    return directory


@contextmanager
def backend_instance():
    """Enroll managed launches for the lifetime of this backend."""
    if os.name == "nt":
        yield
        return
    import fcntl
    import psutil

    key = _instance(psutil.Process())
    path = _directory() / key
    global _backend_key
    previous = _backend_key
    fd = os.open(
        path,
        os.O_CREAT | os.O_EXCL | os.O_APPEND | os.O_WRONLY,
        0o600,
    )
    with os.fdopen(fd, "wb") as journal:
        _backend_key = key
        try:
            yield
            journal.write(b'"closed"\n')
            journal.flush()
        finally:
            _backend_key = previous
            try:
                fcntl.flock(journal, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass  # An attached CLI owns final verification and removal.
            else:
                path.unlink(missing_ok=True)


@contextmanager
def managed_launch(options):
    """Publish intent before spawn, then the identity returned by the OS."""
    key = _backend_key or os.environ.get(_OWNER)
    session = bool(options.get("start_new_session"))
    if (
        os.name == "nt"
        or not key
        or not (session or options.get("process_group") == 0)
    ):
        yield lambda _pid: None
        return
    # Isolated SDK workers need psutil only for an enrolled launch.
    import psutil

    if not re.fullmatch(r"[0-9]+-[0-9]+", key):
        raise ValueError("Invalid backend instance")
    env = options.get("env")
    options["env"] = {**(os.environ if env is None else env), _OWNER: key}
    ticket = uuid4().hex
    # Open without O_CREAT. An ended backend cannot admit new launches.
    fd = os.open(_directory() / key, os.O_APPEND | os.O_WRONLY)
    with os.fdopen(fd, "wb", buffering=0) as journal:

        def publish(*fields):
            journal.write((json.dumps([ticket, *fields]) + "\n").encode())

        spawned = False

        def started(pid):
            nonlocal spawned
            spawned = True
            try:
                try:
                    child = psutil.Process(pid)
                    birth = (
                        child.create_time()
                        if child.ppid() == os.getpid()
                        else None
                    )
                except psutil.NoSuchProcess:
                    birth = None
                publish(pid, birth, session)
            except (OSError, psutil.Error):
                # Leave the ticket pending and return the live process to
                # its supervisor, which still owns its normal teardown.
                logger.exception("Cannot record ownership of PID %s", pid)

        publish()
        try:
            yield started
        except (OSError, TypeError, ValueError):
            # Spawn validation and OS exec failures return no process handle.
            if not spawned:
                publish(None)
            raise


@contextmanager
def observe_backend(process):
    """Pin this generation's journal before sending the shutdown signal."""
    import fcntl

    path = _directory() / _instance(process)
    try:
        journal = path.open("rb")
    except FileNotFoundError:
        yield None
        return
    with journal:
        fcntl.flock(journal, fcntl.LOCK_SH)
        try:
            yield OwnershipSnapshot(journal) if path.exists() else None
        finally:
            if not process.is_running():
                path.unlink(missing_ok=True)


class OwnershipSnapshot:
    """Read complete launch records and resolve live OS identities."""

    def __init__(self, journal):
        self.journal = journal
        self.launches = {}
        self.closed = False

    def members(self, known):
        """Return live members and whether the launch records are resolved."""
        for line in self.journal:
            event = json.loads(line)
            if event == "closed":
                self.closed = True
            else:
                ticket, *fields = event
                self.launches[ticket] = fields

        verified = True
        sessions = {}
        groups = {}
        for fields in self.launches.values():
            if not fields:
                verified = False  # A spawner has not published its result.
            elif fields != [None]:
                pid, birth, session = fields
                (sessions if session else groups)[pid] = birth

        found, resolved = self._live_members(sessions, groups, known)
        # A middle process can publish and exit during the OS snapshot.
        size = os.fstat(self.journal.fileno()).st_size
        return found, verified and resolved and self.journal.tell() == size

    @staticmethod
    def _live_members(sessions, groups, known):
        import psutil

        found = set()
        verified = True
        candidates = defaultdict(set)
        pids = psutil.pids() if sessions or groups else ()
        for identify, leaders in ((os.getsid, sessions), (os.getpgid, groups)):
            if not leaders:
                continue
            for pid in pids:
                try:
                    leader = identify(pid)
                    if leader not in leaders:
                        continue
                    member = psutil.Process(pid)
                    if member.status() in (
                        psutil.STATUS_DEAD,
                        psutil.STATUS_ZOMBIE,
                    ):
                        continue
                    # Ensure the handle belongs to the sampled OS group.
                    if identify(pid) == leader and member.is_running():
                        candidates[leader, leaders[leader]].add(member)
                except (ProcessLookupError, psutil.NoSuchProcess):
                    continue

        for (leader, birth), members in candidates.items():
            try:
                if psutil.Process(leader).create_time() == birth:
                    found.update(members)
                elif birth is None:
                    verified = False
                # A reused leader PID belongs to another generation.
            except psutil.NoSuchProcess:
                if any(member in known for member in members):
                    found.update(members)
                else:
                    # A leaderless group with no known surviving member
                    # cannot safely be distinguished from a recycled ID.
                    verified = False
        return found, verified
