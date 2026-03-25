# -*- coding: utf-8 -*-
"""Agent Teams tools for CoPaw.

Provides tools for agents to manage teams, tasks, mailbox, and relationships
through the standard tool interface.
"""
import json
import logging
from pathlib import Path

from agentscope.tool import ToolResponse

logger = logging.getLogger(__name__)


def _text(s: str) -> dict:
    """Create a text content block with proper type field."""
    return {"type": "text", "text": s}


def create_teams_tools(workspace_dir: Path, wake_agent=None):
    """Create teams tool functions bound to a workspace directory.

    Args:
        workspace_dir: The agent's workspace directory.
        wake_agent: Optional async callback to wake a target agent.
            Signature: async def wake_agent(agent_id: str, message: str) -> None

    Returns:
        List of tool functions to register.
    """
    workspaces_dir = workspace_dir.parent

    # Lazy init to avoid import errors if teams package not ready
    def _get_team_manager():
        from ...teams import TeamManager
        return TeamManager(workspaces_dir)

    def _get_mailbox():
        from ...teams import Mailbox
        return Mailbox(workspace_dir)

    def _get_relationships():
        from ...teams import RelationshipStore
        return RelationshipStore(workspace_dir)

    def _get_room_manager():
        from ...teams.mailbox import RoomManager
        return RoomManager(workspaces_dir)

    # ── Team Management ─────────────────────────────────

    async def team_manage(
        action: str,
        team_name: str = "",
        lead_agent_id: str = "",
        teammates_json: str = "",
        agent_id: str = "",
        role: str = "",
    ) -> ToolResponse:
        """Manage agent teams: create, list, get status, add/remove teammates, disband.

        Args:
            action (`str`):
                Action to perform. One of: "create", "list", "status",
                "add_teammate", "remove_teammate", "disband", "complete".
            team_name (`str`):
                Team name. Required for all actions except "list".
            lead_agent_id (`str`):
                Lead agent ID. Required for "create".
            teammates_json (`str`):
                JSON array of teammate specs for "create".
                Each item: {"agent_id": "...", "role": "..."}.
            agent_id (`str`):
                Agent ID for "add_teammate" / "remove_teammate".
            role (`str`):
                Role description for "add_teammate".

        Returns:
            `ToolResponse`: Result of the team operation.
        """
        try:
            tm = _get_team_manager()

            if action == "create":
                if not team_name or not lead_agent_id:
                    return ToolResponse(
                        content=[_text("team_name and lead_agent_id are required")],
                                            )
                teammates = json.loads(teammates_json) if teammates_json else []
                config = tm.create_team(team_name, lead_agent_id, teammates)
                return ToolResponse(content=[_text(f"Team '{team_name}' created. Lead: {lead_agent_id}, "
                         f"Teammates: {[t.agent_id for t in config.teammates]}")])

            elif action == "list":
                teams = tm.list_teams()
                if not teams:
                    return ToolResponse(content=[_text("No teams found.")])
                lines = [f"- {t.name} (lead={t.lead_agent_id}, status={t.status})" for t in teams]
                return ToolResponse(content=[_text("\n".join(lines))])

            elif action == "status":
                if not team_name:
                    return ToolResponse(content=[_text("team_name is required")])
                status = tm.get_team_status(team_name)
                if not status:
                    return ToolResponse(content=[_text(f"Team '{team_name}' not found")])
                return ToolResponse(content=[_text(json.dumps(status, ensure_ascii=False, indent=2))])

            elif action == "add_teammate":
                if not team_name or not agent_id:
                    return ToolResponse(content=[_text("team_name and agent_id are required")])
                config = tm.add_teammate(team_name, agent_id, role=role)
                if not config:
                    return ToolResponse(content=[_text(f"Team '{team_name}' not found")])
                return ToolResponse(content=[_text(f"Added {agent_id} to team '{team_name}'")])

            elif action == "remove_teammate":
                if not team_name or not agent_id:
                    return ToolResponse(content=[_text("team_name and agent_id are required")])
                tm.remove_teammate(team_name, agent_id)
                return ToolResponse(content=[_text(f"Removed {agent_id} from team '{team_name}'")])

            elif action == "disband":
                if not team_name:
                    return ToolResponse(content=[_text("team_name is required")])
                tm.disband_team(team_name)
                return ToolResponse(content=[_text(f"Team '{team_name}' disbanded")])

            elif action == "complete":
                if not team_name:
                    return ToolResponse(content=[_text("team_name is required")])
                tm.complete_team(team_name)
                return ToolResponse(content=[_text(f"Team '{team_name}' marked as completed")])

            else:
                return ToolResponse(
                    content=[_text(f"Unknown action: {action}. Use: create/list/status/add_teammate/remove_teammate/disband/complete")],
                                    )

        except Exception as e:
            return ToolResponse(content=[_text(f"Error: {e}")])

    # ── Task Board ──────────────────────────────────────

    async def team_task(
        action: str,
        team_name: str,
        task_id: str = "",
        title: str = "",
        description: str = "",
        assigned_to: str = "",
        created_by: str = "",
        depends_on_json: str = "",
        result_summary: str = "",
        review_note: str = "",
        approve: bool = True,
        status_filter: str = "",
        priority: str = "normal",
        required_skills_json: str = "",
        agent_skills_json: str = "",
        thread_id: str = "",
    ) -> ToolResponse:
        """Manage tasks on a team's shared task board.

        Args:
            action (`str`):
                Action to perform. One of: "add", "list", "claim",
                "start", "submit", "review", "complete", "summary".
            team_name (`str`):
                Team name. Required for all actions.
            task_id (`str`):
                Task ID. Required for "claim", "start", "submit", "review", "complete".
            title (`str`):
                Task title. Required for "add".
            description (`str`):
                Task description. Used with "add".
            assigned_to (`str`):
                Agent ID to assign to. Empty = public task. Used with "add".
            created_by (`str`):
                Creator agent ID. Used with "add".
            depends_on_json (`str`):
                JSON array of task IDs this task depends on. Used with "add".
            result_summary (`str`):
                Summary of results. Used with "submit" or "complete".
            review_note (`str`):
                Review comment. Used with "review".
            approve (`bool`):
                Review decision. Used with "review" (true=approved, false=rework).
            status_filter (`str`):
                Filter tasks by status. Used with "list".
            priority (`str`):
                Task priority: "urgent", "high", "normal", "low". Used with "add".
            required_skills_json (`str`):
                JSON array of skill names required to claim. Used with "add".
            agent_skills_json (`str`):
                JSON array of skills the claiming agent has. Used with "claim".
            thread_id (`str`):
                Optional conversation thread ID used for submit/review mailbox notifications.
                Empty means fallback to task_id.

        Returns:
            `ToolResponse`: Result of the task operation.
        """
        try:
            tm = _get_team_manager()
            board = tm.get_task_board(team_name)
            if not board:
                return ToolResponse(content=[_text(f"Team '{team_name}' not found")])

            if action == "add":
                if not title:
                    return ToolResponse(content=[_text("title is required")])
                depends_on = json.loads(depends_on_json) if depends_on_json else []
                required_skills = json.loads(required_skills_json) if required_skills_json else []
                task = board.add_task(
                    title=title,
                    description=description,
                    created_by=created_by,
                    assigned_to=assigned_to or None,
                    depends_on=depends_on,
                    priority=priority,
                    required_skills=required_skills,
                )
                return ToolResponse(content=[_text(f"Task added: {task.title} (id={task.id}, priority={priority})")])

            elif action == "list":
                tasks = board.list_tasks(
                    status=status_filter or None,
                    assigned_to=assigned_to or None,
                )
                if not tasks:
                    return ToolResponse(content=[_text("No tasks found.")])
                # Sort by priority
                prio_order = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
                tasks.sort(key=lambda t: prio_order.get(t.priority, 2))
                lines = []
                for t in tasks:
                    prio_tag = "🔴" if t.priority == "urgent" else "🟡" if t.priority == "high" else ""
                    scope = "公共" if t.assigned_to is None else f"→ {t.assigned_to}"
                    line = f"- {prio_tag}[{t.status}] {t.title} (id={t.id}) {scope}"
                    if t.claimed_by:
                        line += f" (claimed by {t.claimed_by})"
                    if t.required_skills:
                        line += f" [需要: {', '.join(t.required_skills)}]"
                    lines.append(line)
                return ToolResponse(content=[_text("\n".join(lines))])

            elif action == "claim":
                if not task_id or not created_by:
                    return ToolResponse(content=[_text("task_id and created_by (as claimer) are required")])
                agent_skills = json.loads(agent_skills_json) if agent_skills_json else None
                task = board.claim_task(task_id, created_by, agent_skills=agent_skills)
                if not task:
                    return ToolResponse(content=[_text(f"Cannot claim task {task_id} (already claimed, blocked, wrong assignee, or missing skills)")])
                return ToolResponse(content=[_text(f"Task {task_id} claimed by {created_by}")])

            elif action == "start":
                if not task_id or not created_by:
                    return ToolResponse(content=[_text("task_id and created_by are required")])
                task = board.start_task(task_id, created_by)
                if not task:
                    return ToolResponse(content=[_text(f"Cannot start task {task_id}")])
                return ToolResponse(content=[_text(f"Task {task_id} started")])

            elif action == "submit":
                if not task_id:
                    return ToolResponse(content=[_text("task_id is required")])
                t = board.submit_task(task_id=task_id, agent_id=created_by, result_summary=result_summary)
                if not t:
                    return ToolResponse(content=[_text("Cannot submit task")])

                # notify team lead for review
                try:
                    cfg = tm.get_team(team_name)
                    if cfg and cfg.lead_agent_id and cfg.lead_agent_id != created_by:
                        mb = _get_mailbox()
                        note = (
                            f"Task submitted for review: {t.title} (id={t.id}) by {created_by}. "
                            f"Summary: {(result_summary or '')[:200]}"
                        )
                        mb.send(
                            to_agent=cfg.lead_agent_id,
                            from_agent=created_by or "unknown",
                            content=note,
                            msg_type="notify",
                            thread_id=thread_id or t.id,
                            task_id=t.id,
                            msg_kind="submit",
                            need_reply=True,
                        )
                        if wake_agent:
                            import asyncio
                            asyncio.ensure_future(wake_agent(
                                cfg.lead_agent_id,
                                f"📬 Task submit from {created_by}: {t.title} (id={t.id})"
                            ))
                except Exception as e:
                    logger.debug("submit notify failed: %s", e)

                return ToolResponse(content=[_text(f"Task submitted: {t.title} (id={t.id})")])

            elif action == "review":
                if not task_id:
                    return ToolResponse(content=[_text("task_id is required")])
                reviewer = created_by or assigned_to or "reviewer"
                t = board.review_task(task_id=task_id, reviewer_id=reviewer, approve=approve, review_note=review_note)
                if not t:
                    return ToolResponse(content=[_text("Cannot review task (status must be submitted)")])
                decision = "approved" if approve else "rework"

                # notify assignee/claimer with review result
                try:
                    target = t.claimed_by or t.assigned_to
                    if target and target != reviewer:
                        mb = _get_mailbox()
                        note = (
                            f"Task review result: {t.title} (id={t.id}) => {decision}. "
                            f"Note: {(review_note or '')[:200]}"
                        )
                        mb.send(
                            to_agent=target,
                            from_agent=reviewer,
                            content=note,
                            msg_type="notify",
                            thread_id=thread_id or t.id,
                            task_id=t.id,
                            msg_kind="review",
                            need_reply=not approve,
                        )
                        if wake_agent:
                            import asyncio
                            asyncio.ensure_future(wake_agent(
                                target,
                                f"📬 Task review from {reviewer}: {t.title} => {decision}"
                            ))

                    # Always wake team lead as final decision owner
                    cfg = tm.get_team(team_name)
                    lead = cfg.lead_agent_id if cfg else ""
                    if wake_agent and lead and lead != reviewer:
                        import asyncio
                        asyncio.ensure_future(wake_agent(
                            lead,
                            f"📣 Review decided by {reviewer}: {t.title} (id={t.id}) => {decision}"
                        ))
                except Exception as e:
                    logger.debug("review notify failed: %s", e)

                return ToolResponse(content=[_text(f"Task reviewed: {t.title} (id={t.id}, decision={decision})")])

            elif action == "complete":
                if not task_id or not created_by:
                    return ToolResponse(content=[_text("task_id and created_by are required")])
                task = board.complete_task(task_id, created_by, result_summary)
                if not task:
                    return ToolResponse(content=[_text(f"Cannot complete task {task_id}")])

                # E3: distill task knowledge into agent memory
                try:
                    from copaw.agents.memory.distiller import distill_task
                    distill_task(task=task, agent_id=created_by, workspace_dir=workspace_dir)
                except Exception as e:
                    logger.debug("E3 distill failed: %s", e)

                # C1: auto-resume blocked tasks that depended on this task
                try:
                    resumed = board.check_blocked_tasks()
                    if resumed:
                        logger.info(
                            "C1: auto-resumed %d blocked task(s) after completing %s",
                            len(resumed), task_id,
                        )
                except Exception as e:
                    logger.debug("C1 check_blocked failed: %s", e)

                # Wake team lead on completion for fast aggregation/next-step planning
                try:
                    cfg = tm.get_team(team_name)
                    lead = cfg.lead_agent_id if cfg else ""
                    if wake_agent and lead and lead != created_by:
                        import asyncio
                        asyncio.ensure_future(wake_agent(
                            lead,
                            f"✅ Task completed by {created_by}: {task.title} (id={task.id})"
                        ))
                except Exception as e:
                    logger.debug("complete wake failed: %s", e)

                return ToolResponse(content=[_text(f"Task {task_id} completed")])

            elif action == "summary":
                summary = board.get_summary()
                workflow_summary = board.get_workflow_summary()
                result = {
                    "total": summary["total"],
                    "by_status": summary["by_status"],
                    "workflows": workflow_summary,
                }
                return ToolResponse(content=[_text(json.dumps(result, ensure_ascii=False, indent=2))])

            else:
                return ToolResponse(
                    content=[_text(f"Unknown action: {action}. Use: add/list/claim/start/complete/summary")],
                                    )

        except Exception as e:
            return ToolResponse(content=[_text(f"Error: {e}")])

    # ── Mailbox ─────────────────────────────────────────

    async def agent_mailbox(
        action: str,
        to_agent: str = "",
        content: str = "",
        msg_type: str = "notify",
        from_agent: str = "",
        reply_to: str = "",
        thread_id: str = "",
        task_id: str = "",
        msg_kind: str = "general",
        need_reply: bool = False,
        queue_mode: str = "",
        room_name: str = "",
        room_id: str = "",
        target_agent: str = "",
        topic: str = "",
        members_json: str = "",
        max_rounds: int = 10,
        round_timeout_sec: int = 300,
        limit: int = 50,
        since_round: int = 0,
        conclusion: str = "",
        status_filter: str = "",
    ) -> ToolResponse:
        """Send and receive messages between agents.

        Args:
            action (`str`):
                Action to perform. One of: "send", "receive", "peek", "broadcast",
                "create_room", "room_send", "room_pass", "room_timeout",
                "room_timeout_due", "room_prompt_member", "room_next_round_prompt",
                "room_history", "room_list", "room_info", "room_join",
                "room_leave", "room_conclude".
            to_agent (`str`):
                Target agent ID. Required for "send".
            content (`str`):
                Message content. Required for "send", "broadcast", "room_send".
            msg_type (`str`):
                Message type: "delegate", "consult", "notify", "broadcast".
                Default: "notify".
            from_agent (`str`):
                Sender agent ID. Used with "send", "broadcast", and room actions.
            reply_to (`str`):
                Message ID being replied to. Used with "send".
            thread_id (`str`):
                Conversation thread ID for continuous collaboration.
                Used with "send" and "broadcast". Empty = auto-generate on send.
            task_id (`str`):
                Related task ID for this message.
            msg_kind (`str`):
                Semantic type: assign/progress/blocker/submit/review/rework/done/general.
            need_reply (`bool`):
                Whether receiver should reply in the same thread.
            queue_mode (`str`):
                Delivery mode hint for AutoPoll: "steer", "collect", or "followup".
                Empty means auto-resolve from msg_kind/priority.
            room_name (`str`):
                Room name. Required for "create_room".
            room_id (`str`):
                Room ID. Required for room_send/room_pass/room_timeout/
                room_timeout_due/room_prompt_member/room_next_round_prompt/
                room_history/room_info/room_join/room_leave/room_conclude.
            target_agent (`str`):
                Target agent ID. Required for "room_prompt_member".
            topic (`str`):
                Discussion topic. Used with "create_room".
            members_json (`str`):
                JSON array of member agent_ids. Required for "create_room".
            max_rounds (`int`):
                Max discussion rounds. Used with "create_room". Default: 10.
            round_timeout_sec (`int`):
                Round timeout in seconds. Used with "create_room". Default: 300.
            limit (`int`):
                Max messages to return. Used with "room_history". Default: 50.
            since_round (`int`):
                Only return messages from this round onwards. Used with "room_history".
            conclusion (`str`):
                Conclusion text. Required for "room_conclude".
            status_filter (`str`):
                Filter rooms by status ("active"/"closed"). Used with "room_list".

        Returns:
            `ToolResponse`: Result of the mailbox operation.
        """
        try:
            mb = _get_mailbox()

            if action == "send":
                if not to_agent or not content:
                    return ToolResponse(content=[_text("to_agent and content are required")])
                msg = mb.send(
                    to_agent=to_agent,
                    content=content,
                    msg_type=msg_type,
                    from_agent=from_agent,
                    reply_to=reply_to or None,
                    thread_id=thread_id,
                    task_id=task_id,
                    msg_kind=msg_kind,
                    need_reply=need_reply,
                    queue_mode=queue_mode or None,
                )
                # Wake target agent
                if wake_agent:
                    try:
                        import asyncio
                        asyncio.ensure_future(wake_agent(
                            to_agent,
                            f"📬 New {msg_type} message from {from_agent}: {content[:100]}"
                        ))
                    except Exception as e:
                        logger.debug("Failed to wake agent %s: %s", to_agent, e)
                return ToolResponse(content=[_text(
                    f"Message sent to {to_agent} (id={msg.id}, type={msg_type}, thread={msg.thread_id}, task={msg.task_id or '-'}, kind={msg.msg_kind}, mode={msg.queue_mode}, need_reply={msg.need_reply})"
                )])

            elif action == "receive":
                msgs = mb.receive()
                if not msgs:
                    return ToolResponse(content=[_text("No new messages.")])
                lines = []
                for m in msgs:
                    lines.append(
                        f"- [{m.msg_type}/{m.msg_kind}] from {m.from_agent}: {m.content[:200]} "
                        f"(thread={m.thread_id}, task={m.task_id or '-'}, need_reply={m.need_reply})"
                    )
                return ToolResponse(content=[_text("\n".join(lines))])

            elif action == "peek":
                count = mb.peek()
                return ToolResponse(content=[_text(f"{count} unread message(s)")])

            elif action == "broadcast":
                if not content:
                    return ToolResponse(content=[_text("content is required")])
                msgs = mb.broadcast(
                    content=content,
                    from_agent=from_agent,
                    thread_id=thread_id,
                    task_id=task_id,
                    msg_kind=msg_kind,
                    need_reply=need_reply,
                )
                # Wake all target agents
                if wake_agent:
                    import asyncio
                    for m in msgs:
                        try:
                            asyncio.ensure_future(wake_agent(
                                m.to_agent,
                                f"📬 Broadcast from {from_agent}: {content[:100]}"
                            ))
                        except Exception as e:
                            logger.debug("Failed to wake agent %s: %s", m.to_agent, e)
                return ToolResponse(content=[_text(f"Broadcast sent to {len(msgs)} agent(s)")])

            # -- Room actions -----------------------------------------------

            elif action == "create_room":
                if not room_name:
                    return ToolResponse(content=[_text("room_name is required")])
                if not members_json:
                    return ToolResponse(content=[_text("members_json is required")])
                if not from_agent:
                    return ToolResponse(content=[_text("from_agent is required")])
                try:
                    members = json.loads(members_json)
                except json.JSONDecodeError:
                    return ToolResponse(content=[_text("members_json must be a valid JSON array")])
                rm = _get_room_manager()
                room = rm.create_room(
                    host=from_agent,
                    name=room_name,
                    topic=topic,
                    members=members,
                    max_rounds=max_rounds,
                    round_timeout_sec=round_timeout_sec,
                )
                lines = [
                    f"Room created: {room.name} (id={room.room_id})",
                    f"Topic: {room.topic or '(none)'}",
                    f"Host: {room.host}",
                    f"Members: {', '.join(room.members)}",
                    f"Rules: non-host members must respond each round via speak/pass; timeout can be auto-marked",
                    f"Max rounds: {room.max_rounds}",
                    f"Round timeout: {room.round_timeout_sec}s",
                ]
                return ToolResponse(content=[_text("\n".join(lines))])

            elif action == "room_send":
                if not room_id:
                    return ToolResponse(content=[_text("room_id is required")])
                if not content:
                    return ToolResponse(content=[_text("content is required")])
                if not from_agent:
                    return ToolResponse(content=[_text("from_agent is required")])
                rm = _get_room_manager()
                room = rm.get_room(room_id)
                if not room:
                    return ToolResponse(content=[_text(f"Room {room_id} not found")])
                msg = rm.send_message(
                    room_id=room_id,
                    from_agent=from_agent,
                    content=content,
                    msg_type="speak",
                )
                if not msg:
                    return ToolResponse(
                        content=[_text("Failed to send. Check: room exists, active, you are a member, and you have not already responded this round.")],
                                            )
                if wake_agent:
                    import asyncio
                    updated_room = rm.get_room(room_id) or room
                    round_status = rm.get_round_status(room_id) or {}
                    pending = set(round_status.get("pending_agents", []))
                    notify_targets = set(pending)
                    notify_targets.add(updated_room.host)
                    notify_targets.discard(from_agent)
                    for member in sorted(notify_targets):
                        try:
                            asyncio.ensure_future(wake_agent(
                                member,
                                f"💬 Room [{updated_room.name}] round {msg.round} has a new message from {from_agent}. "
                                f"Current pending members: {', '.join(round_status.get('pending_agents', [])) or 'none'}. "
                                f"Please call agent_mailbox(action='room_history', room_id='{room_id}') to read full context, then reply with room_send or room_pass."
                            ))
                        except Exception as e:
                            logger.debug("Failed to wake %s: %s", member, e)
                updated_room = rm.get_room(room_id) or room
                extra = ""
                if updated_room.needs_conclusion:
                    extra = "\n⚠️ Max rounds reached. Host should conclude."
                return ToolResponse(content=[_text(
                    f"Sent speak message to room {room_id} at round {msg.round}.{extra}"
                )])

            elif action == "room_pass":
                if not room_id:
                    return ToolResponse(content=[_text("room_id is required")])
                if not from_agent:
                    return ToolResponse(content=[_text("from_agent is required")])
                rm = _get_room_manager()
                msg = rm.send_message(
                    room_id=room_id,
                    from_agent=from_agent,
                    content="已阅读，本轮无补充",
                    msg_type="pass",
                )
                if not msg:
                    return ToolResponse(
                        content=[_text("Failed to pass. Check membership / room status / duplicate response in same round.")],
                                            )
                room = rm.get_room(room_id)
                return ToolResponse(content=[_text(
                    f"Pass recorded for room {room_id} at round {msg.round}. Current round now: {room.current_round if room else msg.round}"
                )])

            elif action == "room_timeout":
                if not room_id:
                    return ToolResponse(content=[_text("room_id is required")])
                rm = _get_room_manager()
                count = rm.mark_timeout_skips(room_id)
                room = rm.get_room(room_id)
                extra = ""
                if room and room.needs_conclusion:
                    extra = " Host should conclude now."
                return ToolResponse(content=[_text(
                    f"Marked {count} timeout_skip response(s) in room {room_id}.{extra}"
                )])

            elif action == "room_timeout_due":
                if not room_id:
                    return ToolResponse(content=[_text("room_id is required")])
                rm = _get_room_manager()
                due = rm.is_round_timeout_due(room_id)
                if not due:
                    return ToolResponse(content=[_text(f"Room {room_id} timeout is not due yet")])
                count = rm.mark_timeout_skips(room_id)
                room = rm.get_room(room_id)
                extra = ""
                if room and room.needs_conclusion:
                    extra = " Host should conclude now."
                return ToolResponse(content=[_text(
                    f"Timeout due. Marked {count} timeout_skip response(s) in room {room_id}.{extra}"
                )])

            elif action == "room_prompt_member":
                if not room_id:
                    return ToolResponse(content=[_text("room_id is required")])
                if not from_agent:
                    return ToolResponse(content=[_text("from_agent is required")])
                if not target_agent:
                    return ToolResponse(content=[_text("target_agent is required")])
                if not content:
                    return ToolResponse(content=[_text("content is required")])
                rm = _get_room_manager()
                msg = rm.prompt_member(room_id=room_id, host=from_agent, target_agent=target_agent, content=content)
                if not msg:
                    return ToolResponse(content=[_text("Failed to prompt member. Only host can prompt a non-host member in an active room.")])
                if wake_agent:
                    import asyncio
                    try:
                        asyncio.ensure_future(wake_agent(
                            target_agent,
                            f"📣 Host {from_agent} prompted you in room {room_id}: {content} "
                            f"Please call room_history first, then reply with room_send or room_pass."
                        ))
                    except Exception as e:
                        logger.debug("Failed to wake %s: %s", target_agent, e)
                return ToolResponse(content=[_text(
                    f"Prompt sent to {target_agent} in room {room_id}."
                )])

            elif action == "room_next_round_prompt":
                if not room_id:
                    return ToolResponse(content=[_text("room_id is required")])
                if not from_agent:
                    return ToolResponse(content=[_text("from_agent is required")])
                if not content:
                    return ToolResponse(content=[_text("content is required")])
                rm = _get_room_manager()
                msg = rm.next_round_prompt(room_id=room_id, host=from_agent, content=content)
                if not msg:
                    return ToolResponse(content=[_text("Failed to send next-round prompt. Only host can do this in an active room.")])
                room = rm.get_room(room_id)
                rs = rm.get_round_status(room_id) or {}
                pending = rs.get('pending_agents', [])
                if wake_agent:
                    import asyncio
                    for member in pending:
                        try:
                            asyncio.ensure_future(wake_agent(
                                member,
                                f"🧭 Host {from_agent} started/steered round {msg.round} in room {room_id}: {content} "
                                f"Please call room_history first, then reply with room_send or room_pass."
                            ))
                        except Exception as e:
                            logger.debug("Failed to wake %s: %s", member, e)
                return ToolResponse(content=[_text(
                    f"Next-round prompt posted in room {room_id}. Pending members: {', '.join(pending) or '(none)'}"
                )])

            elif action == "room_history":
                if not room_id:
                    return ToolResponse(content=[_text("room_id is required")])
                rm = _get_room_manager()
                sr = since_round if since_round > 0 else None
                room = rm.get_room(room_id)
                if not room:
                    return ToolResponse(content=[_text(f"Room {room_id} not found")])
                messages = rm.get_history(room_id=room_id, limit=limit, since_round=sr)
                round_status = rm.get_round_status(room_id) or {}
                lines = [
                    f"Room: {room.name} (id={room.room_id})",
                    f"Topic: {room.topic or '(none)'}",
                    f"Status: {room.status}",
                    f"Host: {room.host}",
                    f"Members: {', '.join(room.members)}",
                    f"Round: {room.current_round}/{room.max_rounds}",
                    f"Responded: {', '.join(round_status.get('responded_agents', [])) or '(none)'}",
                    f"Pending: {', '.join(round_status.get('pending_agents', [])) or '(none)'}",
                    f"Needs conclusion: {room.needs_conclusion}",
                    f"Round timeout: {room.round_timeout_sec}s",
                    "---",
                ]
                if not messages:
                    lines.append("No messages found")
                else:
                    for m in messages:
                        label = {
                            "speak": "speak",
                            "pass": "pass",
                            "timeout_skip": "timeout",
                            "conclude": "conclude",
                        }.get(m.msg_type, m.msg_type)
                        lines.append(f"[R{m.round}] {m.from_agent} [{label}]: {m.content}")
                return ToolResponse(content=[_text("\n".join(lines))])

            elif action == "room_list":
                rm = _get_room_manager()
                agent_filter = from_agent if from_agent else None
                sf = status_filter if status_filter else None
                rooms = rm.list_rooms(agent_id=agent_filter, status_filter=sf)
                if not rooms:
                    return ToolResponse(content=[_text("No rooms found")])
                lines = []
                for r in rooms:
                    status_icon = "🟢" if r.status == "active" else "🔴"
                    rs = rm.get_round_status(r.room_id) or {}
                    pending = ', '.join(rs.get('pending_agents', [])) or '(none)'
                    lines.append(
                        f"{status_icon} {r.name} (id={r.room_id}) round={r.current_round}/{r.max_rounds} "
                        f"needs_conclusion={r.needs_conclusion} pending=[{pending}] members=[{', '.join(r.members)}]"
                    )
                return ToolResponse(content=[_text("\n".join(lines))])

            elif action == "room_info":
                if not room_id:
                    return ToolResponse(content=[_text("room_id is required")])
                rm = _get_room_manager()
                room = rm.get_room(room_id)
                if not room:
                    return ToolResponse(content=[_text(f"Room {room_id} not found")])
                lines = [
                    f"Name: {room.name}",
                    f"ID: {room.room_id}",
                    f"Status: {room.status}",
                    f"Host: {room.host}",
                    f"Members: {', '.join(room.members)}",
                    f"Round: {room.current_round}/{room.max_rounds}",
                    f"Round timeout: {room.round_timeout_sec}s",
                    f"Needs conclusion: {room.needs_conclusion}",
                ]
                rs = rm.get_round_status(room_id) or {}
                lines.append(f"Responded: {', '.join(rs.get('responded_agents', [])) or '(none)'}")
                lines.append(f"Pending: {', '.join(rs.get('pending_agents', [])) or '(none)'}")
                if room.topic:
                    lines.append(f"Topic: {room.topic}")
                if room.conclusion:
                    lines.append(f"Conclusion: {room.conclusion}")
                if room.closed_at:
                    lines.append(f"Closed at: {room.closed_at}")
                return ToolResponse(content=[_text("\n".join(lines))])

            elif action == "room_join":
                if not room_id:
                    return ToolResponse(content=[_text("room_id is required")])
                if not from_agent:
                    return ToolResponse(content=[_text("from_agent is required")])
                rm = _get_room_manager()
                room = rm.join_room(room_id=room_id, agent_id=from_agent)
                if not room:
                    return ToolResponse(content=[_text(f"Failed to join room {room_id}")])
                return ToolResponse(content=[_text(
                    f"{from_agent} joined room {room.name}. Members: {', '.join(room.members)}"
                )])

            elif action == "room_leave":
                if not room_id:
                    return ToolResponse(content=[_text("room_id is required")])
                if not from_agent:
                    return ToolResponse(content=[_text("from_agent is required")])
                rm = _get_room_manager()
                room = rm.leave_room(room_id=room_id, agent_id=from_agent)
                if not room:
                    return ToolResponse(
                        content=[_text(f"Failed to leave room {room_id}. Host cannot leave.")],
                                            )
                return ToolResponse(content=[_text(
                    f"{from_agent} left room {room.name}. Members: {', '.join(room.members)}"
                )])

            elif action == "room_conclude":
                if not room_id:
                    return ToolResponse(content=[_text("room_id is required")])
                if not from_agent:
                    return ToolResponse(content=[_text("from_agent (host) is required")])
                if not conclusion:
                    return ToolResponse(content=[_text("conclusion is required")])
                rm = _get_room_manager()
                room = rm.conclude_room(room_id=room_id, host=from_agent, conclusion=conclusion)
                if not room:
                    return ToolResponse(
                        content=[_text(f"Failed to conclude room {room_id}. Only the host can conclude.")],
                                            )
                return ToolResponse(content=[_text(
                    f"Room {room.name} concluded.\nConclusion: {conclusion}"
                )])

            else:
                return ToolResponse(
                    content=[_text(
                        f"Unknown action: {action}. Use: send/receive/peek/broadcast/"
                        "create_room/room_send/room_pass/room_timeout/room_timeout_due/"
                        "room_prompt_member/room_next_round_prompt/room_history/room_list/room_info/"
                        "room_join/room_leave/room_conclude"
                    )],
                                    )

        except Exception as e:
            return ToolResponse(content=[_text(f"Error: {e}")])

    # ── Relationships ───────────────────────────────────

    async def agent_relationships(
        action: str,
        target_type: str = "human",
        user_id: str = "",
        agent_id: str = "",
        name: str = "",
        relation: str = "other",
        note: str = "",
    ) -> ToolResponse:
        """Manage relationships with humans and other agents.

        Args:
            action (`str`):
                Action to perform. One of: "add", "remove", "list", "prompt".
            target_type (`str`):
                "human" or "agent". Default: "human".
            user_id (`str`):
                User ID. Required for human add/remove.
            agent_id (`str`):
                Agent ID. Required for agent add/remove.
            name (`str`):
                Display name.
            relation (`str`):
                Relationship type.
                For humans: "creator", "direct_leader", "collaborator",
                    "stakeholder", "team_member", "mentor", "other".
                For agents: "peer", "supervisor", "assistant",
                    "subordinate", "other".
            note (`str`):
                Additional note about the relationship.

        Returns:
            `ToolResponse`: Result of the relationship operation.
        """
        try:
            rs = _get_relationships()

            if action == "add":
                if target_type == "human":
                    if not user_id:
                        return ToolResponse(content=[_text("user_id is required")])
                    rel = rs.add_human(user_id, name=name, relation=relation, note=note)
                    return ToolResponse(content=[_text(f"Human relationship added: {rel.name or rel.user_id} ({rel.relation})")])
                else:
                    if not agent_id:
                        return ToolResponse(content=[_text("agent_id is required")])
                    rel = rs.add_agent(agent_id, name=name, relation=relation, note=note)
                    return ToolResponse(content=[_text(f"Agent relationship added: {rel.name or rel.agent_id} ({rel.relation})")])

            elif action == "remove":
                if target_type == "human":
                    ok = rs.remove_human(user_id)
                else:
                    ok = rs.remove_agent(agent_id)
                return ToolResponse(content=[_text("Removed" if ok else "Not found")])

            elif action == "list":
                if target_type == "human":
                    rels = rs.list_humans()
                    if not rels:
                        return ToolResponse(content=[_text("No human relationships.")])
                    lines = [f"- {r.name or r.user_id} ({r.relation})" + (f" — {r.note}" if r.note else "") for r in rels]
                else:
                    rels = rs.list_agents()
                    if not rels:
                        return ToolResponse(content=[_text("No agent relationships.")])
                    lines = [f"- {r.name or r.agent_id} ({r.relation})" + (f" — {r.note}" if r.note else "") for r in rels]
                return ToolResponse(content=[_text("\n".join(lines))])

            elif action == "prompt":
                section = rs.build_prompt_section()
                return ToolResponse(content=[_text(section if section else "No relationships configured.")])

            else:
                return ToolResponse(
                    content=[_text(f"Unknown action: {action}. Use: add/remove/list/prompt")],
                                    )

        except Exception as e:
            return ToolResponse(content=[_text(f"Error: {e}")])

    return [team_manage, team_task, agent_mailbox, agent_relationships]
