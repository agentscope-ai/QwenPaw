# -*- coding: utf-8 -*-
"""The process-wide media gate: one permit set, and no orphaned group."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

import pytest

from services.media_files import media_gate

pytestmark = pytest.mark.unit

FAKE_SLEEP_SECONDS = 0.15


@pytest.fixture(autouse=True)
def _fresh_gate():
    """The gate is built once from the environment; tests rebuild it."""

    media_gate.reset_gate()
    yield
    media_gate.reset_gate()


def _child_script(body: str) -> list[str]:
    return [sys.executable, "-c", body]


def test_gate_never_runs_more_media_processes_than_slots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Six spawns under a two-slot gate overlap in pairs, never more."""

    monkeypatch.setenv(media_gate.ENV_SLOTS, "2")
    media_gate.reset_gate()
    ledger = tmp_path / "overlaps.jsonl"
    ledger.write_text("", encoding="utf-8")

    _spawn_gated_runs(runs=6, ledger=ledger)

    assert _max_overlap(ledger) <= 2


_LEDGER_BODY = (
    "import json, sys, time\n"
    "path, seconds = sys.argv[1], float(sys.argv[2])\n"
    "for event in ('start', 'end'):\n"
    "    with open(path, 'a', encoding='utf-8') as handle:\n"
    "        handle.write(json.dumps(\n"
    "            {'event': event, 'at': time.time(), 'id': sys.argv[3]}\n"
    "        ) + chr(10))\n"
    "    if event == 'start':\n"
    "        time.sleep(seconds)\n"
)


def _max_overlap(ledger) -> int:
    """Largest number of fake media processes that were live at once."""

    events = []
    for line in ledger.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        events.append((row["at"], 1 if row["event"] == "start" else -1))
    # An end at the same instant as a start is not an overlap.
    events.sort(key=lambda item: (item[0], item[1]))
    live = peak = 0
    for _, delta in events:
        live += delta
        peak = max(peak, live)
    return peak


def test_active_count_tracks_the_permits_held() -> None:
    assert media_gate.active_count() == 0
    with media_gate.slot("first"):
        assert media_gate.active_count() == 1
    assert media_gate.active_count() == 0


def test_a_slot_is_never_taken_twice_by_the_same_thread() -> None:
    """A nested acquire would deadlock a saturated gate against its holder."""

    with media_gate.slot("outer"):
        with pytest.raises(RuntimeError, match="nests inside"):
            with media_gate.slot("inner"):
                pass
    assert media_gate.active_count() == 0


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups only")
def test_timeout_takes_the_whole_group_down(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """subprocess.run only kills its direct child; the gate kills the group."""

    monkeypatch.setenv(media_gate.ENV_SLOTS, "1")
    media_gate.reset_gate()
    marker = tmp_path / "grandchild.pid"
    body = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen(\n"
        "    [sys.executable, '-c', 'import time; time.sleep(30)'],\n"
        ")\n"
        "open(sys.argv[1], 'w', encoding='utf-8').write(str(child.pid))\n"
        "time.sleep(30)\n"
    )

    with pytest.raises(subprocess.TimeoutExpired):
        media_gate.run(
            _child_script(body) + [str(marker)],
            timeout=0.5,
            check=False,
        )

    grandchild = int(marker.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = subprocess.run(
            ["ps", "-o", "state=", "-p", str(grandchild)],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        # A zombie has already given its memory back; only a live process
        # would still show up as running, sleeping or stopped.
        if not state or state[0] not in "RSDT":
            return
        time.sleep(0.05)
    pytest.fail(
        f"grandchild {grandchild} survived the timeout: state {state!r}",
    )


def test_timeout_on_a_platform_without_process_groups_still_releases_the_slot(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-POSIX ``kill_group`` cannot reach grandchildren.

    Review #243 r4548690072: on the non-POSIX branch (Windows, or any
    environment where ``setpgid`` is unavailable) ``kill_group`` falls
    back to ``terminate`` + ``kill`` on the direct child. A grandchild
    that inherited the pipe stays alive, and ``run()`` used to follow
    with an unbounded ``process.communicate()`` -- the permit never
    released. The follow-up wait is now bounded and the still-held
    streams are detached (never closed from this thread) on the second
    timeout, so the sweep hands the slot back within
    ``_KILL_GRACE_SECONDS`` regardless of the descendant's lifetime.

    The branch is exercised by forcing ``_GROUPS_SUPPORTED`` to False
    under POSIX -- same code path Windows takes, no cross-platform
    test skips needed.
    """

    monkeypatch.setenv(media_gate.ENV_SLOTS, "1")
    media_gate.reset_gate()
    monkeypatch.setattr(media_gate, "_GROUPS_SUPPORTED", False)
    monkeypatch.setattr(media_gate, "_KILL_GRACE_SECONDS", 0.5)
    marker = tmp_path / "grandchild.pid"
    # Child spawns a grandchild that inherits stdout/stderr and sleeps;
    # killing the direct child leaves the grandchild holding the write
    # end, exactly the state that would block an unbounded communicate().
    body = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen(\n"
        "    [sys.executable, '-c', 'import time; time.sleep(30)'],\n"
        ")\n"
        "open(sys.argv[1], 'w', encoding='utf-8').write(str(child.pid))\n"
        "time.sleep(30)\n"
    )
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        media_gate.run(
            _child_script(body) + [str(marker)],
            timeout=0.5,
            check=False,
            capture_output=True,
        )
    elapsed = time.monotonic() - start

    # The permit must be free again immediately; a lingering slot here is
    # what starved the whole gate under MIN_SLOTS=1.
    assert media_gate.active_count() == 0
    # kill_group's terminate + kill ladder plus the bounded follow-up
    # communicate all fit inside one grace window each; a real hang
    # would blow well past 30s.
    assert elapsed < media_gate._KILL_GRACE_SECONDS * 4, (
        f"non-POSIX timeout path took {elapsed:.2f}s -- the follow-up "
        "wait was not bounded"
    )
    # Reap the grandchild the child spawned so it does not linger past
    # the assertion window. It has no group to reach on this branch,
    # so kill it directly.
    grandchild = int(marker.read_text(encoding="utf-8"))
    try:
        os.kill(grandchild, 15)
    except ProcessLookupError:
        pass


def test_abandon_streams_returns_while_a_reader_thread_holds_the_lock() -> (
    None
):
    """The buffered-pipe primitive probe, on this very machine.

    Review #243 r4559333554: CPython's Windows ``communicate`` drains
    pipes from daemon reader threads parked inside
    ``BufferedReader.read()``, holding the buffer's internal lock until
    the write end closes. The reviewer measured ~1.5 s of ``close()``
    blockage with a real ``os.pipe`` + background read -- and that is a
    *lock* effect, not a Windows-only effect, so it reproduces under
    POSIX too. This test pins the mechanism and the fix in one place:

    1. control: a plain ``close()`` from another thread does NOT return
       while the read is parked (the hazard the old ``_close_pipes``
       and ``Popen.__exit__`` both walked into);
    2. ``abandon_streams`` returns immediately on the very same pipe
       state, because detaching an attribute never touches the lock;
    3. once the write end finally closes, the parked read ends and the
       stream IS closed by its owner -- the handoff leaks nothing.
    """

    import io

    r_fd, w_fd = os.pipe()
    try:
        reader = io.BufferedReader(io.FileIO(r_fd, closefd=True))
        entered = threading.Event()

        def _hold() -> None:
            entered.set()
            try:
                reader.read()
            except OSError:
                pass

        holder = threading.Thread(target=_hold, daemon=True)
        holder.start()
        assert entered.wait(2)
        # Give the parked read time to take the buffer lock.
        time.sleep(0.3)

        # (1) Control: closing from this side waits on the reader's
        # lock -- exactly what blocked the main thread on Windows.
        close_done = threading.Event()

        def _close() -> None:
            try:
                reader.close()
            finally:
                close_done.set()

        closer = threading.Thread(target=_close, daemon=True)
        closer.start()
        assert not close_done.wait(0.5), (
            "control failed: close() did not block on the parked read's "
            "lock; this environment cannot demonstrate the hazard"
        )

        # (2) The fix: detaching never touches the lock, so it returns
        # immediately even while the pipe is in exactly that state.
        class _Stub:
            stdout = None
            stderr = None

        stub = _Stub()
        stub.stdout = reader
        start = time.monotonic()
        media_gate.abandon_streams(stub)
        elapsed = time.monotonic() - start
        assert stub.stdout is None
        assert stub.stderr is None
        assert elapsed < 0.5, f"abandon_streams blocked for {elapsed:.2f}s"

        # (3) Release the write end: the parked read reaches EOF, the
        # blocked closer finally runs, and the stream ends up closed by
        # its owner -- proof the handoff does not leak the fd.
        os.close(w_fd)
        w_fd = -1
        holder.join(3)
        closer.join(3)
        assert not holder.is_alive()
        assert close_done.is_set()
        assert reader.closed
    finally:
        if w_fd != -1:
            os.close(w_fd)


def test_run_timeout_detaches_the_child_streams(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: after a timeout the pipes are detached, not closed.

    Complements the primitive probe above with the real ``run()`` path.
    Two things must hold when the follow-up ``communicate`` expires
    while a grandchild still owns the write end:

    - ``Popen.__exit__`` on the way out of the ``with`` block must not
      close the streams (it checks ``if self.stdout:``), so the streams
      have to be ``None`` by the time the ``TimeoutExpired`` propagates;
    - the permit is released on a bounded clock.

    Together those close the reviewer's r4559333554 finding at the
    call-site level: no thread of this process waits on a pipe lock
    that a foreign lifetime controls.
    """

    monkeypatch.setenv(media_gate.ENV_SLOTS, "1")
    media_gate.reset_gate()
    monkeypatch.setattr(media_gate, "_GROUPS_SUPPORTED", False)
    monkeypatch.setattr(media_gate, "_KILL_GRACE_SECONDS", 0.5)

    instances: list = []
    real_popen = subprocess.Popen

    class SpyPopen(real_popen):  # type: ignore[misc,valid-type]
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            instances.append(self)

    monkeypatch.setattr(media_gate.subprocess, "Popen", SpyPopen)

    marker = tmp_path / "grandchild.pid"
    body = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen(\n"
        "    [sys.executable, '-c', 'import time; time.sleep(30)'],\n"
        ")\n"
        "open(sys.argv[1], 'w', encoding='utf-8').write(str(child.pid))\n"
        "time.sleep(30)\n"
    )
    start = time.monotonic()
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            media_gate.run(
                _child_script(body) + [str(marker)],
                timeout=0.3,
                check=False,
                capture_output=True,
            )
    finally:
        elapsed = time.monotonic() - start
        try:
            grandchild = int(marker.read_text(encoding="utf-8"))
            os.kill(grandchild, 15)
        except (OSError, ProcessLookupError, ValueError):
            pass

    assert instances, "run() never spawned the spy Popen"
    process = instances[0]
    # Detached before the ``with`` block exited -- __exit__ saw None and
    # closed nothing, so it could not wait on any reader-thread lock.
    assert process.stdout is None
    assert process.stderr is None
    assert media_gate.active_count() == 0
    assert elapsed < 5, f"timeout path took {elapsed:.2f}s -- not bounded"


def test_slot_count_prefers_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(media_gate.ENV_SLOTS, "7")
    assert media_gate.slot_count() == 7
    monkeypatch.setenv(media_gate.ENV_SLOTS, "not-a-number")
    monkeypatch.setattr(media_gate, "container_memory_mb", lambda: None)
    assert media_gate.slot_count() == media_gate.MAX_SLOTS


def test_slot_count_shrinks_with_a_tight_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(media_gate.ENV_SLOTS, raising=False)
    monkeypatch.setattr(media_gate, "cgroup_used_mb", lambda: 0.0)
    monkeypatch.setattr(
        media_gate,
        "container_memory_mb",
        lambda: media_gate.DEFAULT_FFMPEG_PEAK_MB * 2.9,
    )
    assert media_gate.slot_count() == 2
    monkeypatch.setattr(media_gate, "container_memory_mb", lambda: 10.0)
    assert media_gate.slot_count() == media_gate.MIN_SLOTS


def test_run_forwards_the_subprocess_contract(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same return object, same exceptions, same captured streams."""

    monkeypatch.setenv(media_gate.ENV_SLOTS, "2")
    media_gate.reset_gate()
    marker = tmp_path / "ok.txt"

    completed = media_gate.run(
        _child_script(
            "import sys\n"
            "open(sys.argv[1], 'w', encoding='utf-8').write('written')\n"
            "print('to-stdout')\n",
        )
        + [str(marker)],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )

    assert completed.returncode == 0
    assert completed.stdout == "to-stdout\n"
    assert marker.read_text(encoding="utf-8") == "written"

    with pytest.raises(subprocess.CalledProcessError) as failure:
        media_gate.run(
            _child_script("import sys; sys.exit(3)"),
            capture_output=True,
            timeout=30,
            check=True,
        )
    assert failure.value.returncode == 3


def test_slot_count_reserves_the_host_before_sizing_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ffmpeg is not the only tenant: the host interpreter pays first."""

    monkeypatch.delenv(media_gate.ENV_SLOTS, raising=False)
    monkeypatch.setattr(media_gate, "cgroup_used_mb", lambda: 0.0)
    monkeypatch.setattr(
        media_gate,
        "container_memory_mb",
        lambda: media_gate.HOST_RESERVE_MB
        + media_gate.DEFAULT_FFMPEG_PEAK_MB * 1.9,
    )
    assert media_gate.slot_count() == 1
    # A 1 GB container fits one measured 512 MB encoder plus the host, not the
    # four the old 120 MB estimate happily handed out.
    monkeypatch.setattr(media_gate, "container_memory_mb", lambda: 1024.0)
    assert media_gate.slot_count() == 1
    monkeypatch.setattr(media_gate, "container_memory_mb", lambda: 4096.0)
    assert media_gate.slot_count() == media_gate.MAX_SLOTS


def test_slot_count_shrinks_when_the_ceiling_is_already_spent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Field case 2026-11-05: a 12 GB ceiling looked like room for four
    encoders while glibc arena fragmentation had already pinned 3.9 GB of
    RSS in this same cgroup. Sizing off the ceiling alone admitted four
    512 MB ffmpeg processes into space that was already gone, and the
    container was OOM-killed. Page cache is excluded because the kernel
    drops it under pressure — it is not what competes with an encoder."""

    monkeypatch.delenv(media_gate.ENV_SLOTS, raising=False)
    monkeypatch.setattr(media_gate, "container_memory_mb", lambda: 4096.0)
    monkeypatch.setattr(media_gate, "cgroup_used_mb", lambda: 0.0)
    assert media_gate.slot_count() == media_gate.MAX_SLOTS
    monkeypatch.setattr(media_gate, "cgroup_used_mb", lambda: 3900.0)
    assert media_gate.slot_count() == media_gate.MIN_SLOTS


def test_cgroup_used_mb_excludes_page_cache(tmp_path, monkeypatch) -> None:
    """Healthy reads must not shrink the gate: only non-reclaimable bytes
    count against the ceiling."""

    current = tmp_path / "memory.current"
    stat = tmp_path / "memory.stat"
    current.write_text(f"{6000 * 1024 * 1024}\n", encoding="ascii")
    stat.write_text(
        f"anon {2000 * 1024 * 1024}\n"
        f"file {4000 * 1024 * 1024}\n"
        f"slab {100 * 1024 * 1024}\n",
        encoding="ascii",
    )
    monkeypatch.setattr(
        media_gate,
        "_read_cgroup_text",
        lambda path: (
            current.read_text(encoding="ascii")
            if path.endswith("memory.current")
            else stat.read_text(encoding="ascii")
        ),
    )
    # 6000 MiB used minus 4000 MiB reclaimable cache.
    assert media_gate.cgroup_used_mb() == pytest.approx(2000.0)

    monkeypatch.setattr(media_gate, "_read_cgroup_text", lambda path: "")
    assert media_gate.cgroup_used_mb() is None


def test_cpu_budget_reads_a_cgroup_quota(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    v2 = tmp_path / "cpu.max"
    v2.write_text("250000 100000", encoding="ascii")
    missing = str(tmp_path / "absent")
    monkeypatch.setattr(media_gate, "_CGROUP_V2_CPU_MAX", str(v2))
    monkeypatch.setattr(media_gate, "_CGROUP_V1_QUOTA", missing)
    monkeypatch.setattr(media_gate, "_CGROUP_V1_PERIOD", missing)

    assert media_gate.cpu_budget() == 2

    # "max" is no ceiling, so the affinity-aware count decides.
    v2.write_text("max", encoding="ascii")
    assert media_gate.cpu_budget() >= 1


def test_cpu_budget_falls_back_to_the_cgroup_v1_pair(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quota = tmp_path / "cpu.cfs_quota_us"
    period = tmp_path / "cpu.cfs_period_us"
    quota.write_text("400000", encoding="ascii")
    period.write_text("100000", encoding="ascii")
    v2_absent = str(tmp_path / "none")
    monkeypatch.setattr(media_gate, "_CGROUP_V2_CPU_MAX", v2_absent)
    monkeypatch.setattr(media_gate, "_CGROUP_V1_QUOTA", str(quota))
    monkeypatch.setattr(media_gate, "_CGROUP_V1_PERIOD", str(period))

    assert media_gate.cpu_budget() == 4


def test_thread_ceiling_follows_the_cores_a_container_owns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(media_gate.ENV_ENCODE_THREADS, raising=False)
    monkeypatch.setattr(media_gate, "cpu_budget", lambda: 16)
    limit = media_gate.MAX_THREADS_PER_PROCESS
    assert media_gate.threads_per_process() == limit
    monkeypatch.setattr(media_gate, "cpu_budget", lambda: 1)
    floor = media_gate.MIN_THREADS_PER_PROCESS
    assert media_gate.threads_per_process() == floor
    monkeypatch.setenv(media_gate.ENV_ENCODE_THREADS, "0")
    assert media_gate.threads_per_process() == 0


def test_thread_limit_lands_on_the_encoder_not_the_decoder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(media_gate, "threads_per_process", lambda: 3)
    media_gate.reset_gate()
    argv = media_gate.thread_limited_argv(
        [
            "/opt/bin/ffmpeg-macos-aarch64-v7.1",
            "-y",
            "-i",
            "/tmp/a.mp4",
            "-i",
            "/tmp/b.mp4",
            "-c:v",
            "libx264",
            "/tmp/out.mp4",
        ],
    )

    assert argv[argv.index("-threads") + 1] == "3"
    # Before the inputs it would bind to the decoder and only slow the read.
    assert argv.index("-threads") > argv.index("/tmp/b.mp4")


def test_thread_limit_leaves_other_programs_and_explicit_choices_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(media_gate, "threads_per_process", lambda: 3)
    media_gate.reset_gate()
    probe = ["ffprobe", "-i", "/tmp/a.mp4"]
    pinned = ["ffmpeg", "-i", "a.mp4", "-threads", "1", "out.mp4"]

    assert media_gate.thread_limited_argv(probe) == probe
    assert media_gate.thread_limited_argv(pinned) == pinned


def test_run_spawns_with_the_thread_cap_applied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate is the funnel: call sites never spell out ``-threads``."""

    seen: list[list[str]] = []

    class _FakeProcess:
        def __init__(self, args, **_options: object) -> None:
            seen.append(list(args))
            self.args = args
            self.returncode = 0
            self.pid = os.getpid()

        def __enter__(self) -> "_FakeProcess":
            return self

        def __exit__(self, *_exc: object) -> None:
            self.returncode = 0

        def communicate(
            self,
            *_args: object,
            **_kwargs: object,
        ) -> tuple[str, str]:
            return ("", "")

    monkeypatch.setattr(media_gate, "threads_per_process", lambda: 2)
    media_gate.reset_gate()
    monkeypatch.setattr(subprocess, "Popen", _FakeProcess)

    media_gate.run(["ffmpeg", "-y", "-i", "a.mp4", "-an", "out.mp4"])

    assert seen == [
        ["ffmpeg", "-y", "-i", "a.mp4", "-threads", "2", "-an", "out.mp4"],
    ]


def _spawn_gated_runs(runs: int, ledger) -> None:
    """Run *runs* fake media processes through the gate from own threads."""

    results: list[str] = []

    def one(index: int) -> None:
        try:
            media_gate.run(
                _child_script(_LEDGER_BODY)
                + [str(ledger), str(FAKE_SLEEP_SECONDS), str(index)],
                timeout=30,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001 - reported through results
            results.append(f"{type(exc).__name__}: {exc}")

    threads = [
        threading.Thread(target=one, args=(index,)) for index in range(runs)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert not results, results
