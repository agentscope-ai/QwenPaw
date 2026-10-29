"""案件仓库：组织/场站隔离、乐观版本、提交与关闭幂等。"""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any

from airport_sms.domain.case import (
    AuditEntry,
    Case,
    CaseId,
    CaseState,
    RiskLevel,
)
from airport_sms.domain.roles import Role
from airport_sms.domain.transitions import transition
from airport_sms.session.principal import Principal
from airport_sms.session.store import init_schema, utcnow


class VersionConflict(Exception):
    """乐观锁冲突。"""


class CaseNotFound(Exception):
    """案件不存在，或调用方不在同一组织/场站。"""


class CaseRepo:
    """案件是系统真源。读路径强制 org 与 site 隔离。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.RLock()
        init_schema(conn)

    def save_new(self, principal: Principal, case: Case) -> Case:
        """插入新案件，归属调用方组织与场站。"""
        with self._lock:
            self._conn.execute(
                "INSERT INTO cases(id, org_id, site_id, version, state, payload,"
                " deleted_at) VALUES(?,?,?,?,?,?,NULL)",
                (
                    str(case.id),
                    principal.org_id,
                    principal.site_id,
                    case.version,
                    case.state.value,
                    _dump(case),
                ),
            )
            self._conn.commit()
        return case

    def get(self, principal: Principal, case_id: CaseId) -> Case:
        """按组织与场站读取。跨租户表现为不存在。"""
        row = self._scope_row(principal, case_id)
        if row is None:
            raise CaseNotFound(str(case_id))
        return _load(row["payload"])

    def list_by_site(self, principal: Principal) -> list[Case]:
        """列出调用方场站下未删除案件。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload FROM cases"
                " WHERE org_id=? AND site_id=? AND deleted_at IS NULL",
                (principal.org_id, principal.site_id),
            ).fetchall()
        return [_load(r["payload"]) for r in rows]

    def write(
        self, principal: Principal, case: Case, *, expected_version: int
    ) -> Case:
        """按期望版本写入。零行更新视为冲突或缺失。"""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE cases SET version=?, state=?, payload=?"
                " WHERE id=? AND org_id=? AND site_id=? AND version=?"
                " AND deleted_at IS NULL",
                (
                    case.version,
                    case.state.value,
                    _dump(case),
                    str(case.id),
                    principal.org_id,
                    principal.site_id,
                    expected_version,
                ),
            )
            if cur.rowcount != 1:
                raise VersionConflict(str(case.id))
            self._conn.commit()
        return case

    def soft_delete(self, principal: Principal, case_id: CaseId) -> None:
        """软删除。行保留，deleted_at 置位。"""
        now = utcnow().isoformat()
        with self._lock:
            cur = self._conn.execute(
                "UPDATE cases SET deleted_at=?"
                " WHERE id=? AND org_id=? AND site_id=? AND deleted_at IS NULL",
                (now, str(case_id), principal.org_id, principal.site_id),
            )
            if cur.rowcount != 1:
                raise CaseNotFound(str(case_id))
            self._conn.commit()

    def deleted_at(self, case_id: CaseId) -> str | None:
        """读取软删除时间戳，测试与运维用。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT deleted_at FROM cases WHERE id=?",
                (str(case_id),),
            ).fetchone()
        if row is None:
            return None
        return row["deleted_at"]

    def apply_idempotent(
        self,
        principal: Principal,
        case_id: CaseId,
        to_state: CaseState,
        actor: Role,
        reason: str,
        *,
        command: str,
        idempotency_key: str,
        alarp: bool = False,
        new_evidence: bool = False,
    ) -> Case:
        """按幂等键提交或关闭。重复键返回已落地的案件，不再迁移。"""
        with self._lock:
            existing = self._conn.execute(
                "SELECT case_id FROM idempotency"
                " WHERE org_id=? AND site_id=? AND command=? AND key=?",
                (principal.org_id, principal.site_id, command, idempotency_key),
            ).fetchone()
            if existing is not None:
                return self.get(principal, CaseId(existing["case_id"]))
            case = self.get(principal, case_id)
            expected = case.version
            updated = transition(
                case,
                to_state,
                actor,
                reason,
                alarp=alarp,
                new_evidence=new_evidence,
            )
            self.write(principal, updated, expected_version=expected)
            self._conn.execute(
                "INSERT INTO idempotency(org_id, site_id, command, key, case_id)"
                " VALUES(?,?,?,?,?)",
                (
                    principal.org_id,
                    principal.site_id,
                    command,
                    idempotency_key,
                    str(case_id),
                ),
            )
            self._conn.commit()
            return updated

    def _scope_row(
        self, principal: Principal, case_id: CaseId
    ) -> sqlite3.Row | None:
        """在调用方 org/site 范围内取未删除行。"""
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM cases"
                " WHERE id=? AND org_id=? AND site_id=? AND deleted_at IS NULL",
                (str(case_id), principal.org_id, principal.site_id),
            ).fetchone()


def _dump(case: Case) -> str:
    """把案件编码为 JSON 载荷。"""
    payload: dict[str, Any] = {
        "id": str(case.id),
        "state": case.state.value,
        "hazard": case.hazard,
        "location": case.location,
        "severity": case.severity,
        "likelihood": case.likelihood,
        "risk_level": case.risk_level.value,
        "owner_role": case.owner_role.value,
        "evidence_refs": list(case.evidence_refs),
        "cited_clauses": list(case.cited_clauses),
        "audit": [
            {
                "from_state": a.from_state.value,
                "to_state": a.to_state.value,
                "actor": a.actor.value,
                "reason": a.reason,
            }
            for a in case.audit
        ],
        "resume_from": case.resume_from.value if case.resume_from else None,
        "version": case.version,
    }
    return json.dumps(payload, ensure_ascii=False)


def _load(raw: str) -> Case:
    """从 JSON 载荷解析案件。"""
    data = json.loads(raw)
    audit = tuple(
        AuditEntry(
            from_state=CaseState(item["from_state"]),
            to_state=CaseState(item["to_state"]),
            actor=Role(item["actor"]),
            reason=item["reason"],
        )
        for item in data["audit"]
    )
    resume = data["resume_from"]
    return Case(
        id=CaseId(data["id"]),
        state=CaseState(data["state"]),
        hazard=data["hazard"],
        location=data["location"],
        severity=data["severity"],
        likelihood=data["likelihood"],
        risk_level=RiskLevel(data["risk_level"]),
        owner_role=Role(data["owner_role"]),
        evidence_refs=tuple(data["evidence_refs"]),
        cited_clauses=tuple(data["cited_clauses"]),
        audit=audit,
        resume_from=CaseState(resume) if resume else None,
        version=data["version"],
    )


__all__ = ["CaseNotFound", "CaseRepo", "VersionConflict"]
