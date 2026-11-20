"""PostgreSQL dispatch leases. User content is read in an owner-scoped transaction."""

import json
import re
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import text

from .database import database_session, set_request_user


@dataclass(frozen=True)
class TaskClaim:
    task_id: str
    owner_id: UUID
    token: UUID


class ConsoleTaskRepository:
    def __init__(self, schema: str, session_factory=database_session, *, lease_seconds=45):
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
            raise ValueError("invalid_database_schema")
        self.queue = f'"{schema}".console_task_queue'
        self.contents = f'"{schema}".console_task_contents'
        self.runs = f'"{schema}".runs'
        self.session = session_factory
        self.lease_seconds = lease_seconds

    async def enqueue(
        self,
        *,
        task_id,
        owner_id,
        agent_id,
        parent_agent_id,
        conversation_id,
        parent_conversation_id,
        run_id,
        envelope,
    ):
        async with self.session() as db:
            await set_request_user(db, owner_id)
            await db.execute(
                text(f"INSERT INTO {self.queue} (id, owner_user_id) VALUES (:id, :uid)"),
                {"id": task_id, "uid": owner_id},
            )
            await db.execute(
                text(
                    f"""
                INSERT INTO {self.contents}
                (id, owner_user_id, agent_id, parent_agent_id, conversation_id, parent_conversation_id, run_id, envelope)
                VALUES (:id,:uid,:agent,:parent,:chat,:root,:run,CAST(:envelope AS jsonb))
            """
                ),
                {
                    "id": task_id,
                    "uid": owner_id,
                    "agent": agent_id,
                    "parent": parent_agent_id,
                    "chat": UUID(conversation_id),
                    "root": UUID(parent_conversation_id),
                    "run": UUID(run_id),
                    "envelope": json.dumps(envelope, ensure_ascii=False),
                },
            )

    async def claim(self) -> TaskClaim | None:
        token = uuid4()
        async with self.session() as db:
            result = await db.execute(
                text(
                    f"""
                WITH candidate AS (
                    SELECT id FROM {self.queue}
                    WHERE state = 'pending' OR (state = 'claimed' AND lease_until <= now())
                    ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED
                )
                UPDATE {self.queue} q SET state='claimed', claim=:token,
                    lease_until=now() + make_interval(secs => :seconds)
                FROM candidate WHERE q.id=candidate.id RETURNING q.id, q.owner_user_id
            """
                ),
                {"token": token, "seconds": self.lease_seconds},
            )
            row = result.first()
        return TaskClaim(row.id, row.owner_user_id, token) if row else None

    async def begin(self, claim: TaskClaim) -> dict | None:
        # Commit the execution boundary before permitting any tool or model to run.
        async with self.session() as db:
            started = await db.execute(
                text(
                    f"""
                UPDATE {self.queue} SET state='running', started_at=now(),
                    lease_until=now()+make_interval(secs => :seconds)
                WHERE id=:id AND claim=:token AND owner_user_id=:uid
                  AND state='claimed' AND lease_until>now() RETURNING id
            """
                ),
                {
                    "id": claim.task_id,
                    "token": claim.token,
                    "uid": claim.owner_id,
                    "seconds": self.lease_seconds,
                },
            )
            if started.scalar_one_or_none() is None:
                return None
            await set_request_user(db, claim.owner_id)
            row = (
                (
                    await db.execute(
                        text(
                            f"""
                SELECT envelope, agent_id, parent_agent_id, conversation_id, parent_conversation_id, run_id
                FROM {self.contents} WHERE id=:id AND owner_user_id=:uid
            """
                        ),
                        {"id": claim.task_id, "uid": claim.owner_id},
                    )
                )
                .mappings()
                .one()
            )
            return dict(row)

    async def renew(self, claim: TaskClaim) -> bool:
        async with self.session() as db:
            row = await db.execute(
                text(
                    f"""
                UPDATE {self.queue} SET lease_until=now()+make_interval(secs => :seconds)
                WHERE id=:id AND claim=:token AND state='running' AND lease_until>now()
                RETURNING id
            """
                ),
                {"id": claim.task_id, "token": claim.token, "seconds": self.lease_seconds},
            )
            return row.scalar_one_or_none() is not None

    async def finish(self, claim: TaskClaim, result: dict) -> bool:
        async with self.session() as db:
            updated = await db.execute(
                text(
                    f"""
                UPDATE {self.queue} SET state='finished', finished_at=now(), claim=NULL, lease_until=NULL
                WHERE id=:id AND claim=:token AND state='running' AND lease_until>now()
                RETURNING id
            """
                ),
                {"id": claim.task_id, "token": claim.token},
            )
            if updated.scalar_one_or_none() is None:
                return False
            await set_request_user(db, claim.owner_id)
            await db.execute(
                text(
                    f"""
                UPDATE {self.contents} SET envelope=NULL, result=CAST(:result AS jsonb)
                WHERE id=:id AND owner_user_id=:uid
            """
                ),
                {
                    "id": claim.task_id,
                    "uid": claim.owner_id,
                    "result": json.dumps(result, ensure_ascii=False),
                },
            )
            error = result.get("error")
            code = error.get("code") if isinstance(error, dict) else None
            if result.get("status") == "failed" and code in (
                "task_admission_timeout",
                "task_execution_timeout",
            ):
                await self._fail_run(db, claim.task_id, claim.owner_id, code)
        return True

    async def _fail_run(self, db, task_id, owner_id, code):
        # The stream finalizer may already have recorded the deadline cancellation.
        await db.execute(
            text(
                f"""
                UPDATE {self.runs} r SET status='failed', finished_at=now(), error_summary=:code
                FROM {self.contents} c WHERE c.id=:id AND c.owner_user_id=:uid
                  AND r.id=c.run_id AND r.initiated_by=c.owner_user_id AND r.conversation_id=c.conversation_id
                  AND (r.status IN ('queued','running','waiting_input','waiting_approval')
                       OR (:timeout AND r.status IN ('cancelled','failed')))
            """
            ),
            {
                "id": task_id,
                "uid": owner_id,
                "code": code,
                "timeout": code != "task_execution_interrupted",
            },
        )

    async def maintain(self):
        async with self.session() as db:
            interrupted = await db.execute(
                text(
                    f"""
                UPDATE {self.queue} SET state='interrupted', finished_at=now(), claim=NULL, lease_until=NULL
                WHERE state='running' AND lease_until<=now()
                RETURNING id, owner_user_id
            """
                )
            )
            for row in interrupted:
                await set_request_user(db, row.owner_user_id)
                await self._fail_run(db, row.id, row.owner_user_id, "task_execution_interrupted")
            await db.execute(
                text(f"DELETE FROM {self.queue} WHERE finished_at < now() - interval '7 days'")
            )

    async def lookup(self, task_id: str, owner_id: UUID) -> dict | None:
        async with self.session() as db:
            await set_request_user(db, owner_id)
            row = (
                (
                    await db.execute(
                        text(
                            f"""
                SELECT q.state, q.started_at, c.agent_id, c.parent_agent_id, c.conversation_id,
                       c.parent_conversation_id, c.run_id, c.result
                FROM {self.contents} c JOIN {self.queue} q ON c.id=q.id
                WHERE c.id=:id AND c.owner_user_id=:uid
            """
                        ),
                        {"id": task_id, "uid": owner_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row else None
