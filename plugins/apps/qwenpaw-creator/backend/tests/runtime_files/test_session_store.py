# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading

import pytest

from domain.enums import CreatorGoalStatus, CreatorSessionStatus
from services.project_files import Project, ProjectStore
from services.project_files.commit import ProjectCommitBoundary
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
    root_message = store.append_message(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        role="user",
        content_parts=_text("initial objective"),
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

    session = store.get_project_session(PROJECT_ID)
    assert session.active_run_id == "run-1"


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
    assert store.get_project_session(PROJECT_ID).last_message_seq == 1
    assert store.get_goal(PROJECT_ID, "goal-initial").intent == (
        "Create the initial Project"
    )
    messages = store.list_messages(PROJECT_ID, SESSION_ID)
    assert [item.message_id for item in messages] == ["message-initial"]
    assert messages[0].source == "initial_goal"


def test_message_jsonl_sequence_and_client_id_payload_drift(tmp_path):
    _root, _snapshot, store, _bootstrap = _runtime(tmp_path)

    first = store.append_message(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        role="user",
        content_parts=_text("hello"),
        client_message_id="client-1",
        source="agentdock",
        channel=MessageChannel.AGENTDOCK,
        classification=MessageClassification.READ_ONLY_QUESTION,
    )
    replay = store.append_message(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        role="user",
        content_parts=_text("hello"),
        client_message_id="client-1",
        source="agentdock",
        channel=MessageChannel.AGENTDOCK,
        classification=MessageClassification.READ_ONLY_QUESTION,
    )
    second = store.append_message(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        role="assistant",
        content_parts=_text("answer"),
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.message.message_id == first.message.message_id
    assert second.message.message_seq == 2
    assert [
        item.message_seq
        for item in store.list_messages(PROJECT_ID, SESSION_ID)
    ] == [1, 2]

    with pytest.raises(MessagePayloadConflict, match="payload drift"):
        store.append_message(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            role="user",
            content_parts=_text("changed"),
            client_message_id="client-1",
            source="agentdock",
            channel=MessageChannel.AGENTDOCK,
            classification=MessageClassification.READ_ONLY_QUESTION,
        )


def test_current_state_and_all_session_streams_are_durable(tmp_path):
    _root, _snapshot, store, _bootstrap = _runtime(tmp_path)
    root_message = store.append_message(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        role="user",
        content_parts=_text("objective"),
    ).message
    goal = store.create_goal(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        goal_id="goal-1",
        root_message_seq=root_message.message_seq,
        intent="Finish work",
    )
    updated_goal = store.set_goal_status(
        PROJECT_ID,
        goal.goal_id,
        CreatorGoalStatus.RESUME_REQUIRED,
        expected_status=CreatorGoalStatus.ACTIVE,
    )
    session = store.set_session_status(
        PROJECT_ID,
        SESSION_ID,
        CreatorSessionStatus.WAITING_RUNTIME,
        expected_status=CreatorSessionStatus.IDLE,
    )
    event_1 = store.append_event(
        PROJECT_ID,
        SESSION_ID,
        event_type="runtime.started",
    )
    event_2 = store.append_event(
        PROJECT_ID,
        SESSION_ID,
        event_type="runtime.waiting",
    )
    queued = store.append_queued_message(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        client_message_id="queued-client-1",
        content_parts=_text("next instruction"),
    )
    consumed = store.transition_queued_message(
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
    linked = store.transition_outbox(
        PROJECT_ID,
        SESSION_ID,
        outbox.outbox_id,
        state=OutboxState.APPENDED,
        linked_message_id=root_message.message_id,
    )

    assert updated_goal.status is CreatorGoalStatus.RESUME_REQUIRED
    assert session.status is CreatorSessionStatus.WAITING_RUNTIME
    assert (event_1.event_seq, event_2.event_seq) == (1, 2)
    assert consumed.queue_seq == 2
    assert consumed.state is QueuedMessageState.APPENDED
    assert linked.outbox_seq == 2
    assert linked.state is OutboxState.APPENDED
    assert [
        item.event_seq for item in store.list_events(PROJECT_ID, SESSION_ID)
    ] == [
        1,
        2,
    ]
    assert [
        item.queue_seq
        for item in store.list_queued_messages(PROJECT_ID, SESSION_ID)
    ] == [1, 2]
    assert [
        item.outbox_seq for item in store.list_outbox(PROJECT_ID, SESSION_ID)
    ] == [
        1,
        2,
    ]
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


def test_review_resolution_event_is_published_before_idle_and_is_idempotent(
    tmp_path,
    monkeypatch,
):
    root, snapshot, store, _bootstrap = _runtime(tmp_path)
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

    original_write = store._write_session_unlocked

    def assert_event_precedes_idle(session):
        if session.status is CreatorSessionStatus.IDLE:
            events = store._event_records_unlocked(PROJECT_ID, SESSION_ID)
            assert events[-1].event_type == "agent.review.resolved"
        return original_write(session)

    monkeypatch.setattr(
        store,
        "_write_session_unlocked",
        assert_event_precedes_idle,
    )
    first = store.resolve_pending_review(PROJECT_ID, SESSION_ID)
    replay = store.resolve_pending_review(PROJECT_ID, SESSION_ID)

    events = store.list_events(PROJECT_ID, SESSION_ID)
    assert first.status is CreatorSessionStatus.IDLE
    assert replay.status is CreatorSessionStatus.IDLE
    assert (
        store.get_goal(PROJECT_ID, "goal-1").status
        is CreatorGoalStatus.COMPLETED
    )
    assert [item.event_type for item in events] == ["agent.review.resolved"]
    assert first.last_event_seq == events[0].event_seq
    assert replay.last_event_seq == events[0].event_seq


def test_competing_review_resolution_supervisors_emit_one_event(tmp_path):
    root, snapshot, store, _bootstrap = _runtime(tmp_path)
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

    stores = [
        ProjectRuntimeSessionStore(root),
        ProjectRuntimeSessionStore(root),
    ]
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda candidate: candidate.resolve_pending_review(
                    PROJECT_ID,
                    SESSION_ID,
                ),
                stores,
            ),
        )

    assert all(item.status is CreatorSessionStatus.IDLE for item in results)
    assert [
        item.event_type for item in store.list_events(PROJECT_ID, SESSION_ID)
    ] == ["agent.review.resolved"]


def test_event_append_and_poll_skip_full_aggregate_recovery_on_consistent_head(
    tmp_path,
    monkeypatch,
):
    root, snapshot, store, _bootstrap = _runtime(tmp_path)
    _activate_runtime(root, snapshot, store)
    first = store.append_event(
        PROJECT_ID,
        SESSION_ID,
        event_type="agent.message_delta",
    )

    def unexpected_full_recovery(*_args, **_kwargs):
        raise AssertionError(
            "consistent event operations must not recover all streams",
        )

    monkeypatch.setattr(
        store,
        "_recover_session_unlocked",
        unexpected_full_recovery,
    )

    second = store.append_event(
        PROJECT_ID,
        SESSION_ID,
        event_type="agent.message_delta",
    )
    events = store.list_events(
        PROJECT_ID,
        SESSION_ID,
        after_seq=first.event_seq,
    )

    assert second.event_seq == 2
    assert [event.event_seq for event in events] == [2]


def test_event_append_recovers_a_stale_aggregate_head_after_a_crash(tmp_path):
    root, snapshot, store, _bootstrap = _runtime(tmp_path)
    _activate_runtime(root, snapshot, store)
    first = store.append_event(
        PROJECT_ID,
        SESSION_ID,
        event_type="runtime.started",
    )
    session_path = (
        root
        / PROJECT_ID
        / "runtime"
        / "sessions"
        / SESSION_ID
        / "session.json"
    )
    stale = store.get_session(PROJECT_ID, SESSION_ID).model_copy(
        update={"last_event_seq": 0},
    )
    AtomicJsonRecordStore(session_path, type(stale)).write(stale)

    second = store.append_event(
        PROJECT_ID,
        SESSION_ID,
        event_type="runtime.continued",
    )

    assert first.event_seq == 1
    assert second.event_seq == 2
    assert store.get_session(PROJECT_ID, SESSION_ID).last_event_seq == 2


def test_review_resolution_reuses_event_after_final_session_write_failure(
    tmp_path,
    monkeypatch,
):
    root, snapshot, store, _bootstrap = _runtime(tmp_path)
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

    assert recovered.status is CreatorSessionStatus.IDLE
    assert [
        item.event_type for item in store.list_events(PROJECT_ID, SESSION_ID)
    ] == ["agent.review.resolved"]


def test_only_active_agentdock_mutation_persists_review_boundary(tmp_path):
    root, snapshot, store, _bootstrap = _runtime(tmp_path)
    _activate_runtime(root, snapshot, store)

    review = store.admit_user_request(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        request_id="request-review",
        client_message_id="client-review",
        content_parts=_text("change the active project"),
        channel=MessageChannel.AGENTDOCK,
        classification=MessageClassification.MUTATION_INSTRUCTION,
    )
    with pytest.raises(RequestAdmissionConflict, match="request_id"):
        store.admit_user_request(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            request_id="request-review",
            client_message_id="client-other",
            content_parts=_text("another change"),
            channel=MessageChannel.AGENTDOCK,
            classification=MessageClassification.MUTATION_INSTRUCTION,
        )
    read_only = store.admit_user_request(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        request_id="request-read",
        client_message_id="client-read",
        content_parts=_text("what changed?"),
        channel=MessageChannel.AGENTDOCK,
        classification=MessageClassification.READ_ONLY_QUESTION,
    )
    hard_stop = store.admit_user_request(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        request_id="request-stop",
        client_message_id="client-stop",
        content_parts=_text("stop"),
        channel=MessageChannel.AGENTDOCK,
        classification=MessageClassification.WORKSPACE_COMMAND,
        hard_stop=True,
    )
    initial = store.admit_user_request(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        request_id="request-initial",
        client_message_id="client-initial",
        content_parts=_text("initial creation"),
        channel=MessageChannel.AGENTDOCK,
        classification=MessageClassification.MUTATION_INSTRUCTION,
        initial_creation=True,
    )
    store.set_session_status(
        PROJECT_ID,
        SESSION_ID,
        CreatorSessionStatus.IDLE,
    )
    idle = store.admit_user_request(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        request_id="request-idle",
        client_message_id="client-idle",
        content_parts=_text("new idle objective"),
        channel=MessageChannel.AGENTDOCK,
        classification=MessageClassification.MUTATION_INSTRUCTION,
    )

    assert review.review_policy is ReviewPolicy.REQUIRE_REVIEW
    assert review.review_boundary is not None
    assert review.review_boundary.request_message_seq == 2
    assert review.review_boundary.interrupted_run_id == "run-1"
    assert review.message.review_boundary == review.review_boundary
    assert store.review_boundary_path(
        PROJECT_ID,
        SESSION_ID,
        "request-review",
    ).is_file()
    # Post-run feedback on a settled Session is still a review boundary: the
    # user is commenting on completed work, so its related changes must be
    # gated behind a review exactly like an interrupt.
    assert idle.review_policy is ReviewPolicy.REQUIRE_REVIEW
    assert idle.review_boundary is not None
    assert idle.message.review_boundary == idle.review_boundary
    assert store.review_boundary_path(
        PROJECT_ID,
        SESSION_ID,
        "request-idle",
    ).is_file()
    for result in (read_only, hard_stop, initial):
        assert result.review_policy is ReviewPolicy.AUTO_FIX
        assert result.review_boundary is None
        assert result.message.review_boundary is None


def test_idle_agentdock_mutation_without_run_captures_feedback_boundary(
    tmp_path,
):
    """Feedback sent after a run settles must still gate behind a review."""

    root, snapshot, store, _bootstrap = _runtime(tmp_path)
    _activate_runtime(root, snapshot, store)
    store.clear_active_run(
        PROJECT_ID,
        SESSION_ID,
        expected_run_id="run-1",
        status=CreatorSessionStatus.IDLE,
    )

    idle = store.admit_user_request(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        request_id="request-idle-feedback",
        client_message_id="client-idle-feedback",
        content_parts=_text("把第二个分镜改成夜景"),
        channel=MessageChannel.AGENTDOCK,
        classification=MessageClassification.MUTATION_INSTRUCTION,
    )

    assert idle.review_policy is ReviewPolicy.REQUIRE_REVIEW
    assert idle.review_boundary is not None
    assert idle.review_boundary.interrupted_run_id is None
    assert idle.review_boundary.request_id == "request-idle-feedback"
    assert idle.message.review_boundary == idle.review_boundary
    assert store.review_boundary_path(
        PROJECT_ID,
        SESSION_ID,
        "request-idle-feedback",
    ).is_file()


def test_cancelled_session_feedback_still_captures_review_boundary(tmp_path):
    """Feedback sent after the user stopped the Agent (CANCELLED, shown as
    standing by in the frontend) still targets already-produced work, so an
    idle-goal review boundary must be captured."""

    root, snapshot, store, _bootstrap = _runtime(tmp_path)
    _activate_runtime(root, snapshot, store)
    store.clear_active_run(
        PROJECT_ID,
        SESSION_ID,
        expected_run_id="run-1",
        status=CreatorSessionStatus.CANCELLED,
    )

    feedback = store.admit_user_request(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        request_id="request-cancelled-feedback",
        client_message_id="client-cancelled-feedback",
        content_parts=_text("把视频 Prompt 写得更丰富一点"),
        channel=MessageChannel.AGENTDOCK,
        classification=MessageClassification.MUTATION_INSTRUCTION,
    )

    assert feedback.review_policy is ReviewPolicy.REQUIRE_REVIEW
    assert feedback.review_boundary is not None
    assert feedback.review_boundary.interrupted_run_id is None


def test_review_revise_interrupts_the_active_run(tmp_path):
    root, snapshot, store, _bootstrap = _runtime(tmp_path)
    _activate_runtime(root, snapshot, store)

    feedback = store.admit_user_request(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        request_id="request-review-regenerate",
        client_message_id="client-review-regenerate",
        content_parts=_text("按审阅意见重做目标"),
        channel=MessageChannel.AGENTDOCK,
        classification=MessageClassification.REVIEW_REVISE,
        source="review_rejection_feedback",
    )

    assert feedback.review_policy is ReviewPolicy.REQUIRE_REVIEW
    assert feedback.review_boundary is not None
    assert feedback.review_boundary.interrupted_run_id == "run-1"


def test_first_mainline_request_without_goal_skips_review_boundary(tmp_path):
    """A Session with no Goal yet is receiving its mainline kick-off.

    The first AgentDock instruction (e.g. after an attachment-driven Project
    creation) starts the mainline; everything it produces is auto-applied
    without capturing a ReviewBoundary.
    """

    root, snapshot, store, _bootstrap = _runtime(tmp_path)
    _seed_runtime_state(root, snapshot)

    kickoff = store.admit_user_request(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        request_id="request-mainline-kickoff",
        client_message_id="client-mainline-kickoff",
        content_parts=_text("根据已导入的剧本生成完整短片"),
        channel=MessageChannel.AGENTDOCK,
        classification=MessageClassification.MUTATION_INSTRUCTION,
    )

    assert kickoff.review_policy is ReviewPolicy.AUTO_FIX
    assert kickoff.review_boundary is None
    assert kickoff.message.review_boundary is None
    assert not store.review_boundary_path(
        PROJECT_ID,
        SESSION_ID,
        "request-mainline-kickoff",
    ).is_file()


def test_active_review_admission_requires_durable_project_baseline(tmp_path):
    root, snapshot, store, _bootstrap = _runtime(tmp_path)
    _activate_runtime(root, snapshot, store)
    (root / PROJECT_ID / "runtime" / "state.json").unlink()

    with pytest.raises(RequestAdmissionConflict, match="state.json"):
        store.admit_user_request(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            request_id="request-review",
            client_message_id="client-review",
            content_parts=_text("change it"),
            channel=MessageChannel.AGENTDOCK,
            classification=MessageClassification.MUTATION_INSTRUCTION,
        )

    assert len(store.list_messages(PROJECT_ID, SESSION_ID)) == 1


def test_concurrent_admission_has_one_message_and_one_boundary(tmp_path):
    root, snapshot, store, _bootstrap = _runtime(tmp_path)
    _activate_runtime(root, snapshot, store)

    def admit(_index: int):
        independent_store = ProjectRuntimeSessionStore(root)
        return independent_store.admit_user_request(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            request_id="request-concurrent",
            client_message_id="client-concurrent",
            content_parts=_text("change once"),
            channel=MessageChannel.AGENTDOCK,
            classification=MessageClassification.MUTATION_INSTRUCTION,
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(admit, range(4)))

    assert sum(result.replayed for result in results) == 3
    assert len({result.message.message_id for result in results}) == 1
    assert len(store.list_messages(PROJECT_ID, SESSION_ID)) == 2
    boundary_root = (
        root
        / PROJECT_ID
        / "runtime"
        / "sessions"
        / SESSION_ID
        / "review-boundaries"
    )
    assert len(list(boundary_root.glob("*.json"))) == 1


def test_review_admission_waits_for_project_commit_baseline_finalization(
    tmp_path,
    monkeypatch,
):
    root, snapshot, session_store, _bootstrap = _runtime(tmp_path)
    _activate_runtime(root, snapshot, session_store)
    project_store = ProjectStore(root)
    boundary = ProjectCommitBoundary(project_store)
    candidate = snapshot.project.model_dump(mode="json")
    candidate["name"] = "Initial work published"
    project_replaced = threading.Event()
    release_finalization = threading.Event()
    admission_done = threading.Event()
    errors: list[BaseException] = []
    admitted = []
    original_update_state = boundary._update_runtime_state

    def delayed_update_state(**kwargs):
        project_replaced.set()
        assert release_finalization.wait(timeout=2)
        return original_update_state(**kwargs)

    monkeypatch.setattr(
        boundary,
        "_update_runtime_state",
        delayed_update_state,
    )

    def commit_initial_work() -> None:
        try:
            boundary.commit(
                base=snapshot,
                candidate=candidate,
                origin="initial_creation",
            )
        except BaseException as exc:  # pragma: no cover - assertion reports it
            errors.append(exc)

    def admit_interrupt() -> None:
        try:
            admitted.append(
                session_store.admit_user_request(
                    PROJECT_ID,
                    SESSION_ID,
                    CONVERSATION_ID,
                    request_id="request-after-commit",
                    client_message_id="client-after-commit",
                    content_parts=_text("change the newly published work"),
                    channel=MessageChannel.AGENTDOCK,
                    classification=MessageClassification.MUTATION_INSTRUCTION,
                ),
            )
        except BaseException as exc:  # pragma: no cover - assertion reports it
            errors.append(exc)
        finally:
            admission_done.set()

    commit_thread = threading.Thread(target=commit_initial_work)
    admission_thread = threading.Thread(target=admit_interrupt)
    commit_thread.start()
    assert project_replaced.wait(timeout=2)
    admission_thread.start()
    assert not admission_done.wait(timeout=0.1)
    release_finalization.set()
    commit_thread.join(timeout=2)
    admission_thread.join(timeout=2)

    assert not errors
    assert admitted[0].review_boundary is not None
    assert admitted[0].review_boundary.accepted_generation == 1
    assert (
        admitted[0].review_boundary.accepted_etag
        == project_store.read(
            PROJECT_ID,
        ).etag
    )


def test_restart_repairs_heads_and_restores_missing_boundary(tmp_path):
    root, snapshot, store, _bootstrap = _runtime(tmp_path)
    _activate_runtime(root, snapshot, store)
    admitted = store.admit_user_request(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        request_id="request-review",
        client_message_id="client-review",
        content_parts=_text("change"),
        channel=MessageChannel.AGENTDOCK,
        classification=MessageClassification.MUTATION_INSTRUCTION,
    )
    store.append_event(
        PROJECT_ID,
        SESSION_ID,
        event_type="review.boundary_captured",
    )
    store.append_queued_message(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        client_message_id="queued-1",
        content_parts=_text("later"),
    )
    session_path = (
        root
        / PROJECT_ID
        / "runtime"
        / "sessions"
        / SESSION_ID
        / "session.json"
    )
    stale = store.get_session(PROJECT_ID, SESSION_ID).model_copy(
        update={
            "last_message_seq": 0,
            "last_event_seq": 0,
            "queued_user_message_count": 0,
        },
    )
    AtomicJsonRecordStore(session_path, type(stale)).write(stale)
    boundary_path = store.review_boundary_path(
        PROJECT_ID,
        SESSION_ID,
        "request-review",
    )
    boundary_path.unlink()

    restarted = ProjectRuntimeSessionStore(root)
    recovered = restarted.get_session(PROJECT_ID, SESSION_ID)
    replay = restarted.admit_user_request(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        request_id="request-review",
        client_message_id="client-review",
        content_parts=_text("change"),
        channel=MessageChannel.AGENTDOCK,
        classification=MessageClassification.MUTATION_INSTRUCTION,
    )
    next_message = restarted.append_message(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        role="assistant",
        content_parts=_text("continued"),
    ).message
    next_event = restarted.append_event(
        PROJECT_ID,
        SESSION_ID,
        event_type="runtime.continued",
    )

    assert recovered.last_message_seq == 2
    assert recovered.last_event_seq == 1
    assert recovered.queued_user_message_count == 1
    assert boundary_path.is_file()
    assert replay.replayed is True
    assert replay.review_boundary == admitted.review_boundary
    assert next_message.message_seq == 3
    assert next_event.event_seq == 2
