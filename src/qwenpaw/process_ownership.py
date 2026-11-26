# -*- coding: utf-8 -*-
"""Publish backend-owned POSIX sessions across parent exit and reparenting."""

from __future__ import annotations

import json
import logging
import math
import os
import re
import stat
import time
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .shutdown import SERVER_EXIT_SECONDS


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
    """Enroll launches and yield a callback for explicit cleanup failures."""
    if os.name == "nt":
        yield lambda: None
        return
    import fcntl
    import psutil

    key = _instance(psutil.Process())
    path = _directory() / key
    global _backend_key
    previous = _backend_key
    if previous and previous.partition(":")[0] == key:
        raise RuntimeError("A backend lifespan is already active")
    fd = os.open(
        path,
        os.O_CREAT | os.O_EXCL | os.O_APPEND | os.O_RDWR,
        0o600,
    )
    with os.fdopen(fd, "r+b", buffering=0) as journal:
        nonce = uuid4().hex
        # A resolved no-process ticket also identifies this lifespan if the
        # same interpreter serves another instance at the same lookup path.
        header = json.dumps([f"instance:{nonce}", None])
        journal.write((header + "\n").encode())
        _backend_key = f"{key}:{nonce}"
        failed = False

        def record_failure():
            nonlocal failed
            if not failed:
                failed = True
                try:
                    journal.write(b'"failed"\n')
                except OSError:
                    logger.exception("Could not publish backend failure")

        try:
            yield record_failure
        except Exception:
            record_failure()
            raise
        else:
            # Readers keep their descriptor. Spawners that already opened
            # this file must check the link count under their shared lock.
            path.unlink()
            if not failed:
                deadline = time.monotonic() + SERVER_EXIT_SECONDS
                while True:
                    try:
                        fcntl.flock(journal, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            logger.warning("Backend launches still in flight")
                            return
                        time.sleep(0.02)
                journal.seek(0)
                receipt = OwnershipSnapshot(journal)
                try:
                    members, resolved = receipt.members(set())
                except (OSError, psutil.Error):
                    logger.warning(
                        "Could not verify backend process ownership",
                    )
                    return
                if (
                    resolved
                    and not members
                    and not (receipt.failed or receipt.closed)
                ):
                    journal.write(b'"closed"\n')
        finally:
            _backend_key = previous
            # Normal sealing has already unlinked the file.
            if os.fstat(fd).st_nlink:
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
    import fcntl
    import psutil

    match = re.fullmatch(r"([0-9]+-[0-9]+)(?::([a-f0-9]{32}))?", key)
    if not match:
        raise ValueError("Invalid backend instance")
    env = options.get("env")
    options["env"] = {**(os.environ if env is None else env), _OWNER: key}
    ticket = uuid4().hex
    fd = os.open(_directory() / match[1], os.O_APPEND | os.O_RDWR)
    with os.fdopen(fd, "r+b", buffering=0) as journal:
        fcntl.flock(journal, fcntl.LOCK_SH)
        if not os.fstat(fd).st_nlink:
            raise RuntimeError("Backend launch admission is closed")
        header = os.pread(fd, 80, 0).split(b"\n", 1)[0]
        if match[2] or header.startswith(b'["instance:'):
            expected = json.dumps([f"instance:{match[2]}", None]).encode()
            if expected != header:
                raise RuntimeError("Backend launch generation has ended")

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
    try:
        path = _directory() / _instance(process)
        journal = path.open("rb")
    except OSError:
        yield None
        return
    with journal:
        try:
            yield OwnershipSnapshot(journal)
        finally:
            if not process.is_running():
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Could not remove stale ownership journal")


class OwnershipSnapshot:
    """Read complete launch records and resolve live OS identities."""

    def __init__(self, journal):
        self.journal = journal
        self.launches = {}
        self.closed = False
        self.failed = False
        self.damaged = False

    def read_records(self):
        """Keep valid identities even if another record is unreadable."""
        for line in self.journal:
            try:
                if not line.endswith(b"\n"):
                    raise ValueError("Truncated record")
                event = json.loads(line)
                if self.closed:
                    self.damaged = True
                if event == "closed":
                    self.closed = True
                elif event == "failed":
                    self.failed = True
                else:
                    if not isinstance(event, list) or not event:
                        raise ValueError("Invalid launch record")
                    ticket, *fields = event
                    if not isinstance(ticket, str):
                        raise ValueError("Invalid launch ticket")
                    if fields and fields != [None]:
                        pid, birth, session = fields
                        if (
                            type(pid) is not int
                            or pid <= 0
                            or (
                                birth is not None
                                and (
                                    type(birth) not in (float, int)
                                    or not math.isfinite(birth)
                                )
                            )
                            or type(session) is not bool
                        ):
                            raise ValueError("Invalid process identity")
                    if ticket in self.launches and (
                        self.launches[ticket] or not fields
                    ):
                        raise ValueError("Duplicate launch ticket")
                    if (
                        fields
                        and ticket not in self.launches
                        and not (
                            ticket.startswith("instance:") and fields == [None]
                        )
                    ):
                        raise ValueError("Missing launch intent")
                    self.launches[ticket] = fields
            except (ValueError, OverflowError, RecursionError):
                self.damaged = True
        return not self.damaged and all(self.launches.values())

    def members(self, known):
        """Return live members and whether the launch records are resolved."""
        try:
            verified = self.read_records()
        except OSError:
            self.damaged = True
            verified = False
        sessions = {}
        groups = {}
        for fields in self.launches.values():
            if fields and fields != [None]:
                pid, birth, session = fields
                (sessions if session else groups)[pid] = birth

        found, resolved = self._live_members(sessions, groups, known)
        # A middle process can publish and exit during the OS snapshot.
        try:
            size = os.fstat(self.journal.fileno()).st_size
            unchanged = self.journal.tell() == size
        except OSError:
            self.damaged = True
            unchanged = False
        return found, verified and resolved and unchanged

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
                except (PermissionError, psutil.AccessDenied):
                    verified = False

        for (leader, birth), members in candidates.items():
            try:
                if psutil.Process(leader).create_time() == birth:
                    found.update(members)
                elif birth is None:
                    verified = False
                # A reused leader PID belongs to another generation.
            except psutil.AccessDenied:
                verified = False
            except psutil.NoSuchProcess:
                if any(member in known for member in members):
                    found.update(members)
                else:
                    # A leaderless group with no known surviving member
                    # cannot safely be distinguished from a recycled ID.
                    verified = False
        return found, verified
