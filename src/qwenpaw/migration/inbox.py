"""遗留收件箱事件到通知事实和私人回执的幂等迁移。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from ..access.agent_repository import agent_database_id
from ..constant import WORKING_DIR
from .common import content_hash, file_hash, migration_session, stable_uuid, table
from .report import MigrationExecutionReport, MigrationRejectedItem


async def migrate_inbox(*, working_dir: Path = WORKING_DIR, schema: str = "qwenpaw", session_factory=None) -> MigrationExecutionReport:
    path = working_dir / "inbox_events.json"
    source_hash = file_hash(path)
    try:
        values = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
        if not isinstance(values, list):
            raise ValueError
    except (OSError, UnicodeDecodeError, ValueError):
        values = []
        rejected = [MigrationRejectedItem(code="invalid_inbox_file", source="work/inbox_events.json", detail="收件箱文件无法解析")]
    else:
        rejected = []
    notifications, receipts = table(schema, "notifications"), table(schema, "notification_receipts")
    users, agents = table(schema, "users"), table(schema, "agents")
    inserted = unchanged = 0
    async with migration_session(session_factory) as session:
        user_ids = set((await session.execute(text(f"SELECT id FROM {users}"))).scalars())
        agent_ids = set((await session.execute(text(f"SELECT id FROM {agents}"))).scalars())
        for item in values:
            source = f"work/inbox_events.json#{item.get('id', 'unknown')}" if isinstance(item, dict) else "work/inbox_events.json#unknown"
            try:
                event_id = UUID(str(item["id"])); recipient = UUID(str(item["recipient_user_id"]))
                agent_key = str(item.get("agent_id") or "default")
                target_agent = agent_database_id(agent_key)
                created_at = datetime.fromtimestamp(float(item["created_at"]), tz=UTC)
            except (KeyError, TypeError, ValueError, OverflowError):
                rejected.append(MigrationRejectedItem(code="invalid_inbox_event", source=source, detail="通知缺少合法标识、接收者或时间")); continue
            if recipient not in user_ids or target_agent not in agent_ids:
                rejected.append(MigrationRejectedItem(code="missing_inbox_owner", source=source, detail="通知接收者或智能体不存在")); continue
            payload_ref = json.dumps({"agent_id": agent_key, "source_id": str(item.get("source_id") or ""), "payload": item.get("payload") if isinstance(item.get("payload"), dict) else {}}, ensure_ascii=False, separators=(",", ":"))
            expected = {"recipient_user_id": recipient, "agent_id": target_agent, "source_type": str(item.get("source_type") or "legacy"), "source_id": stable_uuid("notification_source", f"{item.get('source_type')}:{item.get('source_id')}"), "event_type": str(item.get("event_type") or "legacy"), "status": str(item.get("status") or "success"), "severity": str(item.get("severity") or "info"), "title": str(item.get("title") or ""), "body": str(item.get("body") or ""), "payload_ref": payload_ref, "created_at": created_at}
            row = (await session.execute(text(f"SELECT recipient_user_id,agent_id,source_type,source_id,event_type,status,severity,title,body,payload_ref,created_at FROM {notifications} WHERE id=:id"), {"id": event_id})).mappings().one_or_none()
            receipt = (await session.execute(text(f"SELECT read_at,deleted_at FROM {receipts} WHERE notification_id=:id AND user_id=:user"), {"id": event_id, "user": recipient})).mappings().one_or_none()
            expected_read = created_at if bool(item.get("read")) else None
            if row is not None:
                same_row = all(row[key] == value for key, value in expected.items())
                same_receipt = receipt is not None and ((receipt["read_at"] is not None) == (expected_read is not None)) and receipt["deleted_at"] is None
                if same_row and same_receipt: unchanged += 1
                else: rejected.append(MigrationRejectedItem(code="target_notification_conflict", source=source, detail="目标通知或回执不同，已保留目标版本"))
                continue
            await session.execute(text(f"INSERT INTO {notifications} (id,recipient_user_id,agent_id,source_type,source_id,event_type,status,severity,title,body,payload_ref,created_at) VALUES (:id,:recipient_user_id,:agent_id,:source_type,:source_id,:event_type,:status,:severity,:title,:body,:payload_ref,:created_at)"), {"id": event_id, **expected})
            await session.execute(text(f"INSERT INTO {receipts} (notification_id,user_id,read_at,deleted_at) VALUES (:id,:user,:read_at,NULL)"), {"id": event_id, "user": recipient, "read_at": expected_read})
            inserted += 1
    target_count, target_hash = await _target_snapshot(schema, session_factory)
    processed = inserted + unchanged
    status = "completed_with_rejections" if rejected and processed else "rejected" if rejected else "completed" if values else "empty"
    return MigrationExecutionReport(domain="inbox", status=status, execution_order=8, source_count=len(values), target_count=target_count, inserted_count=inserted, unchanged_count=unchanged, source_hash=source_hash, target_hash=target_hash, transaction_committed=bool(values), rejected=rejected)


async def _target_snapshot(schema: str, session_factory):
    notifications, receipts = table(schema, "notifications"), table(schema, "notification_receipts")
    async with migration_session(session_factory) as session:
        rows = (await session.execute(text(f"SELECT n.id,n.recipient_user_id,n.agent_id,n.source_type,n.source_id,n.event_type,n.status,n.severity,n.title,n.body,n.payload_ref,n.created_at,r.read_at,r.deleted_at FROM {notifications} n JOIN {receipts} r ON r.notification_id=n.id AND r.user_id=n.recipient_user_id ORDER BY n.created_at,n.id"))).mappings().all()
    projection = [dict(row) for row in rows]
    return len(projection), content_hash(projection)

