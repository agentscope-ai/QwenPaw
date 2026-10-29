"""会话与案件库隔离、版本与幂等行为。"""

from __future__ import annotations

import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from airport_sms.domain import CaseId, CaseState, Role, new_draft, transition
from airport_sms.session.case_repo import CaseNotFound, CaseRepo, VersionConflict
from airport_sms.session.principal import Principal
from airport_sms.session.store import SessionStore, open_db, open_session


class Clock:
    """测试用可拨时钟。"""

    def __init__(self) -> None:
        self.t = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def now(self) -> datetime:
        """当前冻结时间。"""
        return self.t

    def advance(self, delta: timedelta) -> None:
        """拨快时钟。"""
        self.t = self.t + delta


def _reporter(org: str = "org-a", site: str = "site-1") -> Principal:
    """构造报告人主体。"""
    return Principal("u1", org, Role.REPORTER, site)


def _draft(case_id: str = "C-1"):
    """构造默认草稿。"""
    return new_draft(
        case_id=CaseId(case_id),
        hazard="FOD",
        location="TWY A",
    )


def test_org_isolation_hides_cross_org_case() -> None:
    """跨组织读取表现为不存在。"""
    conn = open_db()
    repo = CaseRepo(conn)
    owner = _reporter()
    repo.save_new(owner, _draft())
    stranger = _reporter(org="org-b")
    with pytest.raises(CaseNotFound):
        repo.get(stranger, CaseId("C-1"))


def test_create_session_for_reporter() -> None:
    """报告人会话落库。"""
    clock = Clock()
    store = SessionStore(open_db(), now=clock.now)
    session = store.create(open_session("s1", _reporter(), "console", now=clock.now))
    loaded = store.get("s1")
    assert loaded is not None
    assert loaded.session_id == "s1"
    assert loaded.principal.role is Role.REPORTER
    assert loaded.closed is False
    assert session.bound_case_id is None


def test_bind_case_cursor_does_not_change_case_state() -> None:
    """会话绑定案件 id 后案件仍为草稿。"""
    conn = open_db()
    store = SessionStore(conn)
    repo = CaseRepo(conn)
    principal = _reporter()
    store.create(open_session("s1", principal, "console"))
    case = repo.save_new(principal, _draft())
    bound = store.bind_case("s1", case.id)
    store.set_conversation_cursor("s1", "msg-0")
    assert bound.bound_case_id == case.id
    assert store.get("s1").conversation_cursor == "msg-0"
    assert repo.get(principal, case.id).state is CaseState.DRAFT


def test_stale_version_write_fails() -> None:
    """旧版本写入失败。"""
    conn = open_db()
    repo = CaseRepo(conn)
    principal = _reporter()
    case = repo.save_new(principal, _draft())
    submitted = transition(case, CaseState.SUBMITTED, Role.REPORTER, "submit")
    repo.write(principal, submitted, expected_version=case.version)
    with pytest.raises(VersionConflict):
        repo.write(principal, submitted, expected_version=case.version)


def test_submit_idempotency_key_replays_once() -> None:
    """同一提交幂等键只落地一次迁移。"""
    conn = open_db()
    repo = CaseRepo(conn)
    principal = _reporter()
    case = repo.save_new(principal, _draft())
    first = repo.apply_idempotent(
        principal,
        case.id,
        CaseState.SUBMITTED,
        Role.REPORTER,
        "submit",
        command="submit",
        idempotency_key="k-submit",
    )
    second = repo.apply_idempotent(
        principal,
        case.id,
        CaseState.SUBMITTED,
        Role.REPORTER,
        "submit",
        command="submit",
        idempotency_key="k-submit",
    )
    assert first.state is CaseState.SUBMITTED
    assert second.version == first.version
    assert len(second.audit) == 1


def test_close_idempotency_key_replays_once() -> None:
    """同一关闭幂等键不重复关闭。"""
    conn = open_db()
    repo = CaseRepo(conn)
    principal = Principal("so", "org-a", Role.SAFETY_OFFICE, "site-1")
    case = repo.save_new(principal, _draft())
    submitted = transition(case, CaseState.SUBMITTED, Role.REPORTER, "s")
    triaged = transition(submitted, CaseState.TRIAGED, Role.DEPT_OWNER, "t")
    assessing = transition(triaged, CaseState.ASSESSING, Role.DEPT_OWNER, "a")
    mitigating = transition(assessing, CaseState.MITIGATING, Role.DEPT_OWNER, "m")
    verifying = transition(mitigating, CaseState.VERIFYING, Role.DEPT_OWNER, "v")
    repo.write(principal, verifying, expected_version=case.version)
    first = repo.apply_idempotent(
        principal,
        case.id,
        CaseState.CLOSED,
        Role.SAFETY_OFFICE,
        "close",
        command="close",
        idempotency_key="k-close",
    )
    second = repo.apply_idempotent(
        principal,
        case.id,
        CaseState.CLOSED,
        Role.SAFETY_OFFICE,
        "close",
        command="close",
        idempotency_key="k-close",
    )
    assert first.state is CaseState.CLOSED
    assert second.version == first.version
    assert len(second.audit) == len(first.audit)


def test_list_cases_filtered_by_site() -> None:
    """列表不含其他场站。"""
    conn = open_db()
    repo = CaseRepo(conn)
    site1 = _reporter(site="s1")
    site2 = _reporter(site="s2")
    repo.save_new(site1, _draft("A"))
    repo.save_new(site2, _draft("B"))
    listed = repo.list_by_site(site1)
    assert [c.id for c in listed] == [CaseId("A")]


def test_expire_idle_session_by_ttl() -> None:
    """last_seen 超过 TTL 后会话关闭。"""
    clock = Clock()
    store = SessionStore(open_db(), now=clock.now)
    store.create(open_session("s1", _reporter(), "console", now=clock.now))
    clock.advance(timedelta(hours=9))
    n = store.expire_idle(ttl=timedelta(hours=8))
    assert n == 1
    assert store.get("s1").closed is True


def test_messages_do_not_change_case_state() -> None:
    """三条聊天消息不改案件状态。"""
    conn = open_db()
    store = SessionStore(conn)
    repo = CaseRepo(conn)
    principal = _reporter()
    store.create(open_session("s1", principal, "console"))
    case = repo.save_new(principal, _draft())
    store.add_message("s1", "user", "one")
    store.add_message("s1", "user", "two")
    store.add_message("s1", "assistant", "three")
    assert store.message_count("s1") == 3
    assert repo.get(principal, case.id).state is CaseState.DRAFT


def test_system_principal_accepted_for_scheduler() -> None:
    """system 角色可作为调度来源。"""
    store = SessionStore(open_db())
    principal = Principal("cron", "org-a", Role.SYSTEM, "site-1")
    session = store.create(open_session("job-1", principal, "scheduler"))
    assert session.principal.role is Role.SYSTEM
    assert store.get("job-1").channel == "scheduler"


def test_soft_delete_keeps_row() -> None:
    """删除是软删除，行仍在且 deleted_at 有值。"""
    conn = open_db()
    repo = CaseRepo(conn)
    principal = _reporter()
    case = repo.save_new(principal, _draft())
    repo.soft_delete(principal, case.id)
    with pytest.raises(CaseNotFound):
        repo.get(principal, case.id)
    assert repo.deleted_at(case.id) is not None


def test_100_concurrent_reads_p95_under_100ms() -> None:
    """100 次并发读取 p95 低于 100ms。"""
    conn = open_db()
    repo = CaseRepo(conn)
    principal = _reporter()
    repo.save_new(principal, _draft())
    latencies: list[float] = []

    def _read() -> None:
        start = time.perf_counter()
        repo.get(principal, CaseId("C-1"))
        latencies.append((time.perf_counter() - start) * 1000)

    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(lambda _: _read(), range(100)))
    p95 = statistics.quantiles(latencies, n=20)[-1]
    assert p95 < 100, f"p95 {p95:.1f}ms"
