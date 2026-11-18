# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from domain.enums import CreatorGoalStatus, CreatorSessionStatus
from services.project_files import Project, ProjectStore
from services.runtime_files import (
    AtomicJsonRecordStore,
    MessageChannel,
    MessageClassification,
    MessagePayloadConflict,
    OutboxState,
    ProjectRuntimeSessionStore,
    QueuedMessageState,
    RequestAdmissionConflict,
    ReviewPolicy,
    RuntimeProjectState,
    SessionStateConflict,
)
from services.runtime_files.jsonl_store import DurableJsonlStore

pytestmark = pytest.mark.unit


PROJECT_ID = "project-1"
SESSION_ID = "session-1"
CONVERSATION_ID = "conversation-1"


def _runtime(tmp_path: Path):
    root = tmp_path.resolve()
    project_snapshot = ProjectStore(root).create(
        Project.new(project_id=PROJECT_ID, name="Project"),
    )
    store = ProjectRuntimeSessionStore(root)
    bootstrap = store.create_project_runtime(
        PROJECT_ID,
        session_id=SESSION_ID,
        conversation_id=CONVERSATION_ID,
    )
    return root, project_snapshot, store, bootstrap


def _text(value: str) -> list[dict[str, str]]:
    return [{"type": "text", "text": value}]


def _append(store, role: str, text: str, **kwargs):
    return store.append_message(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        role=role,
        content_parts=_text(text),
        **kwargs,
    )


def _admit(store, request_id: str, text: str = "change it", **overrides):
    kwargs = {
        "client_message_id": f"client-{request_id}",
        "channel": MessageChannel.AGENTDOCK,
        "classification": MessageClassification.MUTATION_INSTRUCTION,
    }
    kwargs.update(overrides)
    return store.admit_user_request(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        request_id=request_id,
        content_parts=_text(text),
        **kwargs,
    )


def _seed_runtime_state(root: Path, snapshot) -> RuntimeProjectState:
    state = RuntimeProjectState(
        project_id=PROJECT_ID,
        last_project_generation=snapshot.generation,
        last_project_etag=snapshot.etag,
        accepted_generation=snapshot.generation,
        accepted_etag=snapshot.etag,
    )
    AtomicJsonRecordStore(
        root / PROJECT_ID / "runtime" / "state.json",
        RuntimeProjectState,
    ).write(state)
    return state


def _activate_runtime(root: Path, snapshot, store) -> None:
    root_message = _append(
        store,
        "user",
        "initial objective",
        client_message_id="initial-message",
        source="initial_creation",
        channel=MessageChannel.COMPOSER,
        classification=MessageClassification.MUTATION_INSTRUCTION,
    ).message
    store.create_goal(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        goal_id="goal-1",
        root_message_seq=root_message.message_seq,
        intent="Create the Project",
    )
    store.activate_run(
        PROJECT_ID,
        SESSION_ID,
        goal_id="goal-1",
        run_id="run-1",
    )
    _seed_runtime_state(root, snapshot)


def _pending_review(root: Path, snapshot, store) -> None:
    _activate_runtime(root, snapshot, store)
    store.set_goal_status(
        PROJECT_ID,
        "goal-1",
        CreatorGoalStatus.WAITING_REVIEW,
        expected_status=CreatorGoalStatus.ACTIVE,
    )
    store.clear_active_run(
        PROJECT_ID,
        SESSION_ID,
        expected_run_id="run-1",
        status=CreatorSessionStatus.PENDING_REVIEW,
    )


def _boundary_file(store, request_id: str) -> Path:
    return store.review_boundary_path(PROJECT_ID, SESSION_ID, request_id)


def test_bootstrap_atomically_creates_session_and_default_conversation_only(
    tmp_path,
):
    root, _snapshot, store, bootstrap = _runtime(tmp_path)
    runtime_root = root / PROJECT_ID / "runtime"
    session_root = runtime_root / "sessions" / SESSION_ID

    assert bootstrap.session.status is CreatorSessionStatus.IDLE
    assert bootstrap.default_conversation.is_default is True
    assert (session_root / "session.json").is_file()
    assert (
        session_root / "conversations" / f"{CONVERSATION_ID}.json"
    ).is_file()
    assert all(
        (session_root / name).is_file()
        for name in (
            "messages.jsonl",
            "events.jsonl",
            "queued-messages.jsonl",
            "outbox.jsonl",
        )
    )
    assert not list((runtime_root / "goals").glob("*.json"))

    retry = store.create_project_runtime(
        PROJECT_ID,
        session_id=SESSION_ID,
        conversation_id=CONVERSATION_ID,
    )
    assert retry.session.session_id == SESSION_ID
    assert retry.default_conversation.conversation_id == CONVERSATION_ID

    with pytest.raises(SessionStateConflict, match="another session_id"):
        store.create_project_runtime(PROJECT_ID, session_id="session-other")


def test_activate_run_rejects_a_second_cross_process_owner(tmp_path):
    root, snapshot, store, _bootstrap = _runtime(tmp_path)
    _activate_runtime(root, snapshot, store)

    with pytest.raises(SessionStateConflict, match="already owns"):
        store.activate_run(
            PROJECT_ID,
            SESSION_ID,
            goal_id="goal-1",
            run_id="run-from-another-process",
        )

    assert store.get_project_session(PROJECT_ID).active_run_id == "run-1"


def test_staged_project_bootstrap_can_include_initial_goal(tmp_path):
    root = tmp_path.resolve()
    store = ProjectRuntimeSessionStore(root)
    holder = []

    def initialize(staged_root):
        holder.append(
            store.initialize_staged_project(
                staged_root,
                PROJECT_ID,
                session_id=SESSION_ID,
                conversation_id=CONVERSATION_ID,
                initial_goal="Create the initial Project",
                goal_id="goal-initial",
                initial_message_id="message-initial",
                initial_client_message_id="client-initial",
            ),
        )

    ProjectStore(root).create(
        Project.new(project_id=PROJECT_ID, name="Project"),
        initialize_staged_project=initialize,
    )

    assert holder[0].session.active_goal_id == "goal-initial"
    assert store.get_goal(PROJECT_ID, "goal-initial").intent == (
        "Create the initial Project"
    )
    messages = store.list_messages(PROJECT_ID, SESSION_ID)
    assert [item.message_id for item in messages] == ["message-initial"]
    assert messages[0].source == "initial_goal"


def test_message_jsonl_sequence_and_client_id_payload_drift(tmp_path):
    _root, _snapshot, store, _bootstrap = _runtime(tmp_path)
    idempotent = {
        "client_message_id": "client-1",
        "source": "agentdock",
        "channel": MessageChannel.AGENTDOCK,
        "classification": MessageClassification.READ_ONLY_QUESTION,
    }

    first = _append(store, "user", "hello", **idempotent)
    replay = _append(store, "user", "hello", **idempotent)
    second = _append(store, "assistant", "answer")

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.message.message_id == first.message.message_id
    assert second.message.message_seq == 2
    assert [
        item.message_seq
        for item in store.list_messages(PROJECT_ID, SESSION_ID)
    ] == [1, 2]

    with pytest.raises(MessagePayloadConflict, match="payload drift"):
        _append(store, "user", "changed", **idempotent)


def test_current_state_and_all_session_streams_are_durable(tmp_path):
    _root, _snapshot, store, _bootstrap = _runtime(tmp_path)
    root_message = _append(store, "user", "objective").message
    session = store.set_session_status(
        PROJECT_ID,
        SESSION_ID,
        CreatorSessionStatus.WAITING_RUNTIME,
        expected_status=CreatorSessionStatus.IDLE,
    )
    for name in ("runtime.started", "runtime.waiting"):
        store.append_event(PROJECT_ID, SESSION_ID, event_type=name)
    queued = store.append_queued_message(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        client_message_id="queued-client-1",
        content_parts=_text("next instruction"),
    )
    store.transition_queued_message(
        PROJECT_ID,
        SESSION_ID,
        queued.queued_message_id,
        state=QueuedMessageState.APPENDED,
        appended_message_id=root_message.message_id,
    )
    outbox = store.append_outbox(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        outbox_id="outbox-1",
        content_parts=_text("manual edit"),
    )
    store.transition_outbox(
        PROJECT_ID,
        SESSION_ID,
        outbox.outbox_id,
        state=OutboxState.APPENDED,
        linked_message_id=root_message.message_id,
    )

    assert session.status is CreatorSessionStatus.WAITING_RUNTIME
    assert [
        item.event_seq for item in store.list_events(PROJECT_ID, SESSION_ID)
    ] == [1, 2]
    assert [
        item.queue_seq
        for item in store.list_queued_messages(PROJECT_ID, SESSION_ID)
    ] == [1, 2]
    assert [
        item.outbox_seq for item in store.list_outbox(PROJECT_ID, SESSION_ID)
    ] == [1, 2]
    assert (
        store.get_session(PROJECT_ID, SESSION_ID).queued_user_message_count
        == 0
    )

    with pytest.raises(SessionStateConflict, match="Session status conflict"):
        store.set_session_status(
            PROJECT_ID,
            SESSION_ID,
            CreatorSessionStatus.RUNNING,
            expected_status=CreatorSessionStatus.IDLE,
        )


def test_review_resolution_reuses_event_after_final_session_write_failure(
    tmp_path,
    monkeypatch,
):
    root, snapshot, store, _bootstrap = _runtime(tmp_path)
    _pending_review(root, snapshot, store)
    original_write = store._write_session_unlocked
    failed = False

    def fail_first_idle_write(session):
        nonlocal failed
        if session.status is CreatorSessionStatus.IDLE and not failed:
            failed = True
            raise OSError("injected final Session write failure")
        return original_write(session)

    monkeypatch.setattr(
        store,
        "_write_session_unlocked",
        fail_first_idle_write,
    )
    with pytest.raises(OSError, match="injected final Session write failure"):
        store.resolve_pending_review(PROJECT_ID, SESSION_ID)

    assert store.get_project_session(PROJECT_ID).status is (
        CreatorSessionStatus.PENDING_REVIEW
    )
    recovered = store.resolve_pending_review(PROJECT_ID, SESSION_ID)
    replay = store.resolve_pending_review(PROJECT_ID, SESSION_ID)

    assert recovered.status is CreatorSessionStatus.IDLE
    assert replay.status is CreatorSessionStatus.IDLE
    assert (
        store.get_goal(PROJECT_ID, "goal-1").status
        is CreatorGoalStatus.COMPLETED
    )
    assert [
        item.event_type for item in store.list_events(PROJECT_ID, SESSION_ID)
    ] == [
        "agent.review.resolved",
    ]


def test_only_active_agentdock_mutation_persists_review_boundary(tmp_path):
    root, snapshot, store, _bootstrap = _runtime(tmp_path)
    _activate_runtime(root, snapshot, store)

    review = _admit(store, "request-review", "change the active project")
    with pytest.raises(RequestAdmissionConflict, match="request_id"):
        _admit(
            store,
            "request-review",
            "another change",
            client_message_id="client-other",
        )
    read_only = _admit(
        store,
        "request-read",
        "what changed?",
        classification=MessageClassification.READ_ONLY_QUESTION,
    )
    hard_stop = _admit(
        store,
        "request-stop",
        "stop",
        hard_stop=True,
        classification=MessageClassification.WORKSPACE_COMMAND,
    )
    approval = _admit(
        store,
        "request-approval",
        "用户已保留当前产物",
        source="review_approval_resume",
        classification=MessageClassification.REVIEW_REVISE,
    )
    assert (
        _admit(
            store,
            "request-approval",
            "用户已保留当前产物",
            source="review_approval_resume",
            classification=MessageClassification.REVIEW_REVISE,
        ).message
        == approval.message
    )
    assert store.get_project_session(PROJECT_ID).active_run_id == "run-1"
    store.set_session_status(
        PROJECT_ID,
        SESSION_ID,
        CreatorSessionStatus.IDLE,
    )
    idle = _admit(store, "request-idle", "new idle objective")

    assert review.review_policy is ReviewPolicy.REQUIRE_REVIEW
    assert review.review_boundary is not None
    assert review.review_boundary.request_message_seq == 2
    assert review.review_boundary.interrupted_run_id == "run-1"
    assert review.message.review_boundary == review.review_boundary
    assert _boundary_file(store, "request-review").is_file()
    assert idle.review_policy is ReviewPolicy.REQUIRE_REVIEW
    assert idle.review_boundary is not None
    assert idle.message.review_boundary == idle.review_boundary
    for result in (read_only, hard_stop, approval):
        assert result.review_policy is ReviewPolicy.AUTO_FIX
        assert result.review_boundary is None
        assert result.message.review_boundary is None


def test_hard_stop_consumes_only_existing_input_and_leaves_restart_pending(
    tmp_path,
) -> None:
    root, snapshot, store, _bootstrap = _runtime(tmp_path)
    _activate_runtime(root, snapshot, store)

    stopped = store.hard_stop_session(PROJECT_ID, SESSION_ID)
    restarted = store.admit_user_request(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        request_id="request-restart-after-stop",
        client_message_id="client-restart-after-stop",
        content_parts=_text("继续刚才的任务"),
        channel=MessageChannel.AGENTDOCK,
        classification=MessageClassification.READ_ONLY_QUESTION,
    )
    current = store.get_project_session(PROJECT_ID)

    assert stopped.status is CreatorSessionStatus.CANCELLED
    assert stopped.active_run_id is None
    assert stopped.last_consumed_message_seq == stopped.last_message_seq
    assert restarted.message.message_seq == stopped.last_message_seq + 1
    assert (
        current.last_consumed_message_seq == stopped.last_consumed_message_seq
    )
    assert current.last_message_seq == restarted.message.message_seq


def test_first_mainline_request_without_goal_skips_review_boundary(tmp_path):
    root, snapshot, store, _bootstrap = _runtime(tmp_path)
    _seed_runtime_state(root, snapshot)

    kickoff = _admit(store, "request-kickoff", "根据已导入的剧本生成完整短片")

    assert kickoff.review_policy is ReviewPolicy.AUTO_FIX
    assert kickoff.review_boundary is None
    assert kickoff.message.review_boundary is None
    assert not _boundary_file(store, "request-kickoff").is_file()


def test_active_review_admission_requires_durable_project_baseline(tmp_path):
    root, snapshot, store, _bootstrap = _runtime(tmp_path)
    _activate_runtime(root, snapshot, store)
    (root / PROJECT_ID / "runtime" / "state.json").unlink()

    with pytest.raises(RequestAdmissionConflict, match="state.json"):
        _admit(store, "request-review")

    assert len(store.list_messages(PROJECT_ID, SESSION_ID)) == 1


def test_concurrent_admission_has_one_message_and_one_boundary(tmp_path):
    root, snapshot, store, _bootstrap = _runtime(tmp_path)
    _activate_runtime(root, snapshot, store)

    def admit(_index: int):
        candidate = ProjectRuntimeSessionStore(root)
        return _admit(candidate, "request-concurrent", "change once")

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(admit, range(4)))

    assert sum(result.replayed for result in results) == 3
    assert len(store.list_messages(PROJECT_ID, SESSION_ID)) == 2
    boundary_root = _boundary_file(store, "request-concurrent").parent
    assert len(list(boundary_root.glob("*.json"))) == 1


def test_restart_repairs_heads_and_restores_missing_boundary(tmp_path):
    root, snapshot, store, _bootstrap = _runtime(tmp_path)
    _activate_runtime(root, snapshot, store)
    admitted = _admit(store, "request-review", "change")
    store.append_queued_message(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        client_message_id="queued-1",
        content_parts=_text("later"),
    )
    session_root = root / PROJECT_ID / "runtime" / "sessions" / SESSION_ID
    stale = store.get_session(PROJECT_ID, SESSION_ID).model_copy(
        update={
            "last_message_seq": 0,
            "queued_user_message_count": 0,
        },
    )
    AtomicJsonRecordStore(session_root / "session.json", type(stale)).write(
        stale,
    )
    boundary_path = _boundary_file(store, "request-review")
    boundary_path.unlink()

    restarted = ProjectRuntimeSessionStore(root)
    recovered = restarted.get_session(PROJECT_ID, SESSION_ID)
    replay = _admit(restarted, "request-review", "change")
    next_message = _append(restarted, "assistant", "continued").message

    assert recovered.last_message_seq == 2
    assert recovered.queued_user_message_count == 1
    assert boundary_path.is_file()
    assert replay.replayed is True
    assert replay.review_boundary == admitted.review_boundary
    assert next_message.message_seq == 3


def _spy_full_reads(monkeypatch) -> list[str]:
    """Record whole-stream reads, so a paging test can prove it skipped one."""

    reads: list[str] = []
    original = DurableJsonlStore._read_bytes_unlocked

    def spy(self):  # type: ignore[no-untyped-def]
        reads.append(self.path.name)
        return original(self)

    monkeypatch.setattr(DurableJsonlStore, "_read_bytes_unlocked", spy)
    return reads


def test_list_recent_messages_reads_only_the_tail_window(
    tmp_path,
    monkeypatch,
):
    # Opening a conversation asks for the newest handful. This used to parse
    # every message the session ever wrote and slice in Python, which on a long
    # session cost hundreds of MB per page.
    _, _, store, _ = _runtime(tmp_path)
    for index in range(30):
        _append(store, "user", f"message {index}")
    reads = _spy_full_reads(monkeypatch)

    page = store.list_recent_messages(
        PROJECT_ID,
        SESSION_ID,
        limit=5,
        conversation_id=CONVERSATION_ID,
    )

    assert [item.message_seq for item in page] == [26, 27, 28, 29, 30]
    assert not reads


def test_message_at_reads_only_the_named_line(tmp_path, monkeypatch):
    # A review follow-up already names the seq of the request it belongs to.
    # Locating that message used to parse every record the session ever wrote,
    # which on the field's long sessions meant hundreds of MB per lookup.
    _, _, store, _ = _runtime(tmp_path)
    for index in range(30):
        _append(store, "user", f"message {index}")
    reads = _spy_full_reads(monkeypatch)

    found = store.message_at(PROJECT_ID, SESSION_ID, message_seq=7)

    assert found is not None
    assert found.message_seq == 7
    assert not reads
    # A seq that names nothing is answered without touching the disk.
    assert store.message_at(PROJECT_ID, SESSION_ID, message_seq=0) is None


def test_find_recent_message_answers_existence_without_the_stream(
    tmp_path,
    monkeypatch,
):
    # "Was this pause notice already filed" is an existence question.  The walk
    # is exhaustive -- a miss really means absent -- but it never materializes
    # the stream, which is what a 606 MB history could not afford.
    _, _, store, _ = _runtime(tmp_path)
    for index in range(20):
        _append(store, "user", f"noise {index}")
    marker = _append(
        store,
        "assistant",
        "filed",
        metadata={"executionPauseKey": "pause-key-1"},
    )
    reads = _spy_full_reads(monkeypatch)

    found = store.find_recent_message(
        PROJECT_ID,
        SESSION_ID,
        where=lambda item: item.metadata.get("executionPauseKey")
        == "pause-key-1",
    )

    assert found is not None
    assert found.message_seq == marker.message.message_seq
    assert (
        store.find_recent_message(
            PROJECT_ID,
            SESSION_ID,
            where=lambda item: item.metadata.get("executionPauseKey")
            == "never-filed",
        )
        is None
    )
    assert not reads


def test_last_message_seq_tracks_the_head_without_reading_the_stream(
    tmp_path,
    monkeypatch,
):
    # The YOLO fuse asks "did anything land since I decided?" once per second.
    # Answering that with list_messages rebuilt the whole history every tick.
    _, _, store, _ = _runtime(tmp_path)
    assert store.last_message_seq(PROJECT_ID, SESSION_ID) == 0
    _append(store, "user", "first")
    _append(store, "assistant", "reply")
    reads = _spy_full_reads(monkeypatch)

    head = store.last_message_seq(PROJECT_ID, SESSION_ID)

    assert head == 2
    assert not reads
    _append(store, "user", "third")
    assert store.last_message_seq(PROJECT_ID, SESSION_ID) == 3


def test_list_recent_messages_pages_backwards_from_a_cursor(tmp_path):
    _, _, store, _ = _runtime(tmp_path)
    for index in range(30):
        _append(store, "user", f"message {index}")

    older = store.list_recent_messages(
        PROJECT_ID,
        SESSION_ID,
        limit=5,
        conversation_id=CONVERSATION_ID,
        before_seq=26,
    )

    assert [item.message_seq for item in older] == [21, 22, 23, 24, 25]


def test_list_recent_messages_filters_conversation_while_scanning(tmp_path):
    # The conversation filter has to live in the scan: a page of one
    # conversation must not be truncated by newer messages of another.
    _, _, store, _ = _runtime(tmp_path)
    other = store.create_conversation(
        PROJECT_ID,
        SESSION_ID,
        conversation_id="conversation-2",
        title="Other",
    )
    for index in range(4):
        _append(store, "user", f"first {index}")
        store.append_message(
            PROJECT_ID,
            SESSION_ID,
            other.conversation_id,
            role="user",
            content_parts=_text(f"second {index}"),
        )

    page = store.list_recent_messages(
        PROJECT_ID,
        SESSION_ID,
        limit=3,
        conversation_id=CONVERSATION_ID,
    )

    # Sequences 1, 3, 5, 7 belong to the default conversation.
    assert [item.message_seq for item in page] == [3, 5, 7]
    assert {item.conversation_id for item in page} == {CONVERSATION_ID}


def test_list_recent_events_finds_the_admission_in_the_tail_window(
    tmp_path,
    monkeypatch,
):
    _, _, store, _ = _runtime(tmp_path)
    admitted = _admit(store, "request-tail")
    store.append_event(
        PROJECT_ID,
        SESSION_ID,
        event_type="message.accepted",
        actor="user",
        message_id=admitted.message.message_id,
    )
    for index in range(40):
        store.append_event(
            PROJECT_ID,
            SESSION_ID,
            event_type="task.progress_updated",
            payload={"index": index},
        )
    reads = _spy_full_reads(monkeypatch)

    found = store.list_recent_events(
        PROJECT_ID,
        SESSION_ID,
        limit=1,
        event_type="message.accepted",
        message_id=admitted.message.message_id,
        max_scan=200,
    )

    assert [item.message_id for item in found] == [admitted.message.message_id]
    # A window too small answers "not in the tail" rather than walking back to
    # the head: the send route turns that into an explicit full-scan fallback.
    assert (
        store.list_recent_events(
            PROJECT_ID,
            SESSION_ID,
            limit=1,
            event_type="message.accepted",
            message_id=admitted.message.message_id,
            max_scan=5,
        )
        == []
    )
    assert not reads


def test_create_goal_reads_the_root_message_without_a_full_scan(
    tmp_path,
    monkeypatch,
):
    # A goal references exactly one message, but the old code materialized the
    # whole durable stream and indexed it in Python -- inside the exclusive
    # Project lock, where every 10s lock waiter pays for it.
    _, _, store, _ = _runtime(tmp_path)
    root = _append(store, "user", "objective")
    for index in range(30):
        _append(store, "user", f"message {index}")
    reads = _spy_full_reads(monkeypatch)

    goal = store.create_goal(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        goal_id="goal-read",
        root_message_seq=root.message.message_seq,
        intent="Create the Project",
    )

    assert goal.root_message_seq == 1
    # Recovery legitimately walks the (small) queued stream; the message stream
    # is the one that used to be materialized whole, and it must not be read as
    # a whole here.
    assert "messages.jsonl" not in reads


def test_client_id_lookup_reaches_the_head_without_holding_the_stream(
    tmp_path,
    monkeypatch,
):
    _, _, store, _ = _runtime(tmp_path)
    oldest = _append(
        store,
        "user",
        "oldest",
        client_message_id="client-oldest",
    )
    for index in range(30):
        _append(store, "user", f"message {index}")
    reads = _spy_full_reads(monkeypatch)

    found = store._message_by_client_id_unlocked(
        PROJECT_ID,
        SESSION_ID,
        "client-oldest",
    )
    missing = store._message_by_client_id_unlocked(
        PROJECT_ID,
        SESSION_ID,
        "client-never-used",
    )

    assert found is not None
    assert found.message_id == oldest.message.message_id
    # "absent" still means absent everywhere: the replay walks to the head
    # of the stream, it just holds one page at a time instead of the whole
    # history.
    assert missing is None
    assert not reads


def test_recovery_restores_a_boundary_beyond_one_replay_page(
    tmp_path,
    monkeypatch,
):
    # Recovery replays the message stream in pages to re-assert review
    # boundaries. The page window must not decide which history gets seen, so
    # force one record per page while the boundary sits on message 2.
    monkeypatch.setattr(
        "services.runtime_files.session_store._MESSAGE_REPLAY_PAGE",
        1,
    )
    root, snapshot, store, _bootstrap = _runtime(tmp_path)
    _activate_runtime(root, snapshot, store)
    _admit(store, "request-review", "change")
    for index in range(4):
        _append(store, "assistant", f"later {index}")
    boundary_path = _boundary_file(store, "request-review")
    boundary_path.unlink()

    recovered = ProjectRuntimeSessionStore(root).get_session(
        PROJECT_ID,
        SESSION_ID,
    )

    assert recovered.last_message_seq == 6
    assert boundary_path.is_file()
