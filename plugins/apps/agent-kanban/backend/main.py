# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches,too-many-statements,too-many-nested-blocks
"""Agent Kanban — PawApp backend.

A Kanban board where issues are created, assigned to agents, and
auto-run through the assigned agent via ``ctx.chat``. Agents can query
their own assigned issues through the ``list_my_kanban_issues`` tool.

Persistence: a shared JSON file (``<app_dir>/data/issues.json``) so both
the HTTP API and the agent tool read/write the exact same data.
"""

import asyncio
import dataclasses
import json
import logging
import os
import tempfile
import time
import uuid
from pathlib import Path

try:  # POSIX advisory file locking (macOS/Linux) for cross-process safety.
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback (single-process).
    fcntl = None
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from qwenpaw.pawapp import PawApp, get_ctx
from qwenpaw.pawapp.task import SSEBroadcast
from qwenpaw.identity.runtime import is_multi_user_enabled
from qwenpaw.plugins.http_scope import current_plugin_scope

logger = logging.getLogger(__name__)

# ── Storage (shared by HTTP routes and agent tools) ──────────────────
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DATA_FILE = _DATA_DIR / "issues.json"
_LOCK = asyncio.Lock()
# issue_id -> the in-flight agent run task, so /stop can cancel it.
_RUNNING: Dict[str, "asyncio.Task"] = {}

_CHANNELS: Dict[str, SSEBroadcast] = {}

# In-memory trace buffer for running issues.
_LIVE_TRACE: Dict[str, List[Dict[str, str]]] = {}

# In-memory issues cache (reduces I/O)
_ISSUES_CACHE: Optional[List[Dict[str, Any]]] = None
_CACHE_DIRTY = False  # Track if cache needs persisting
_CACHE_VERSION = 0  # Monotonic version counter to prevent race conditions

# Background dispatcher task (started on launch)
_DISPATCHER_TASK: Optional["asyncio.Task"] = None
_DISPATCHER_RUNNING = False

# Background persistence task (started on launch)
_PERSIST_TASK: Optional["asyncio.Task"] = None
_PERSIST_RUNNING = False

VALID_STATUS = ["backlog", "todo", "in_progress", "review", "done"]
STATUS_LABEL = {
    "backlog": "待规划",
    "todo": "等待调度",
    "in_progress": "进行中",
    "review": "审核中",
    "done": "已完成",
}


def _board_file() -> Path:
    scope = current_plugin_scope.get()
    if scope is None:
        if is_multi_user_enabled():
            raise HTTPException(403, "Kanban requires a user workspace")
        return _DATA_FILE
    from qwenpaw.constant import WORKING_DIR
    return Path(WORKING_DIR).joinpath("plugin-data", "agent-kanban", *scope.storage_parts, "issues.json")


def _load_from_disk() -> List[Dict[str, Any]]:
    """Load issues from disk (only called on startup or cache miss).

    Returns ``[]`` only when the file genuinely does not exist. If the
    file exists but cannot be parsed, retry briefly and then raise.
    """
    path = _board_file()
    if not path.exists():
        return []
    last_err: Optional[Exception] = None
    for _ in range(5):
        try:
            text = path.read_text(encoding="utf-8")
            if not text.strip():
                return []
            return json.loads(text)
        except FileNotFoundError:
            return []
        except (json.JSONDecodeError, ValueError) as e:  # noqa: PERF203
            last_err = e
            time.sleep(0.05)
    raise RuntimeError(
        f"issues.json unreadable: {last_err}",
    )


def _read_all() -> List[Dict[str, Any]]:
    """Read issues from in-memory cache.

    NOTE: This is a synchronous function. The cache is initialized
    by on_launch and kept in sync by _write_all.
    """
    global _ISSUES_CACHE
    if is_multi_user_enabled():
        return _load_from_disk()
    if _ISSUES_CACHE is None:
        # Cache not initialized yet, load from disk
        _ISSUES_CACHE = _load_from_disk()
    return _ISSUES_CACHE


def _persist_to_disk(issues: List[Dict[str, Any]]) -> None:
    """Persist the board atomically to disk (temp file + os.replace).

    Atomic replace guarantees every reader sees either the old or the new
    complete file — never a truncated one — even when other backend
    processes read concurrently.
    """
    path = _board_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(issues, ensure_ascii=False, indent=2)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=".issues.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _write_all(issues: List[Dict[str, Any]]) -> None:
    """Update in-memory cache (no immediate disk I/O).

    The cache is persisted periodically by background task and
    on shutdown by on_terminate.
    """
    global _ISSUES_CACHE, _CACHE_DIRTY, _CACHE_VERSION
    if is_multi_user_enabled():
        _persist_to_disk(issues)
        return
    _ISSUES_CACHE = issues
    _CACHE_DIRTY = True
    _CACHE_VERSION += 1


class _Txn:
    """Serialize a read-modify-write across coroutines AND processes.

    ``_LOCK`` guards coroutines in this event loop; the ``fcntl`` advisory
    lock on ``.issues.lock`` guards other ``qwenpaw app`` processes sharing
    the same app directory (all read/write the same ``data/issues.json``).
    Without it, concurrent writes lose updates.
    """

    def __init__(self) -> None:
        self._fh = None

    async def __aenter__(self) -> "_Txn":
        await _LOCK.acquire()
        if fcntl is None:
            return self
        try:
            lock_path = _board_file().with_name(".issues.lock")
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(  # pylint: disable=consider-using-with
                lock_path,
                "a+",
                encoding="utf-8",
            )
            # Run blocking flock in thread pool to avoid blocking event loop
            await asyncio.to_thread(
                fcntl.flock,
                self._fh.fileno(),
                fcntl.LOCK_EX,
            )
        except BaseException:
            if self._fh is not None:
                self._fh.close()
                self._fh = None
            _LOCK.release()
            raise
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        try:
            if fcntl is not None and self._fh is not None:
                # Run blocking flock unlock in thread pool
                await asyncio.to_thread(
                    fcntl.flock,
                    self._fh.fileno(),
                    fcntl.LOCK_UN,
                )
                self._fh.close()
                self._fh = None
        finally:
            _LOCK.release()
        return False


def _txn() -> "_Txn":
    """Cross-process + cross-coroutine lock for read-modify-write blocks."""
    return _Txn()


def _now() -> float:
    return time.time()


def _find(
    issues: List[Dict[str, Any]],
    issue_id: str,
) -> Optional[Dict[str, Any]]:
    for i in issues:
        if i.get("id") == issue_id:
            return i
    return None


def _agent_has_running(
    agent_id: str,
    issues: List[Dict[str, Any]],
) -> bool:
    """Check whether *agent_id* owns an in_progress issue."""
    for iss in issues:
        if (
            iss.get("assignee") == agent_id
            and iss.get("status") == "in_progress"
        ):
            if is_multi_user_enabled():
                # The durable claim may belong to another process, or may
                # need an operator's decision after an interrupted run.
                return True
            iid = iss.get("id", "")
            task = _RUNNING.get(iid)
            if task is not None and not task.done():
                return True
    return False


# ── Schemas ──────────────────────────────────────────────────────────
class IssueCreate(BaseModel):
    title: str
    description: str = ""
    status: str = "backlog"
    assignee: str = ""


class IssuePatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    assignee: Optional[str] = None


# ── HTTP router ──────────────────────────────────────────────────────
router = APIRouter()


@router.get("/issues")
async def list_issues(ctx=Depends(get_ctx)) -> Dict[str, Any]:
    """List every issue on the board."""
    issues = await asyncio.to_thread(_read_all)

    # Cache ctx for agents (needed by background dispatcher)
    if not is_multi_user_enabled():
        for issue in issues:
            if issue.get("assignee"):
                _LAST_CTX.setdefault(issue["assignee"], ctx)

    return {"issues": issues, "agent_id": ctx.agent_id}


@router.post("/issues")
async def create_issue(
    body: IssueCreate,
    ctx=Depends(get_ctx),
) -> Dict[str, Any]:
    """Create a new issue.

    Creating directly into ``todo`` requires a non-empty assignee.
    If the assigned agent is idle, auto-dispatches immediately.
    """
    status = body.status if body.status in VALID_STATUS else "backlog"
    assignee = body.assignee or ""
    if is_multi_user_enabled() and assignee and assignee != ctx.agent_id:
        raise HTTPException(403, "Select this board's agent")

    if status == "todo" and not assignee:
        raise HTTPException(
            status_code=400,
            detail="Creating in todo requires an assignee",
        )

    trigger_agent: Optional[str] = None
    async with _txn():
        issues = _read_all()
        issue = {
            "id": str(uuid.uuid4()),
            "title": body.title.strip() or "Untitled",
            "description": body.description,
            "status": status,
            "assignee": assignee,
            # No result field - results are stored in session
            "created_at": _now(),
            "updated_at": _now(),
        }
        issues.append(issue)
        _write_all(issues)

        if (
            status == "todo"
            and assignee
            and not _agent_has_running(assignee, issues)
        ):
            trigger_agent = assignee

    if trigger_agent:
        if is_multi_user_enabled():
            return await run_issue(issue["id"], ctx)
        _LAST_CTX.setdefault(trigger_agent, ctx)
        # Background dispatcher will pick up this task automatically

    return issue


@router.patch("/issues/{issue_id:path}")
async def patch_issue(
    issue_id: str,
    body: IssuePatch,
    ctx=Depends(get_ctx),
) -> Dict[str, Any]:
    """Update an issue's title/description/status/assignee.

    Rules enforced:
    - Moving to ``todo`` requires a non-empty assignee.
    - Setting an assignee on a ``backlog`` issue auto-promotes
      it to ``todo``; if that agent is idle the issue is
      auto-dispatched to ``in_progress``.
    """
    if is_multi_user_enabled() and body.assignee and body.assignee != ctx.agent_id:
        raise HTTPException(403, "Select this board's agent")
    trigger_agent: Optional[str] = None
    async with _txn():
        issues = _read_all()
        issue = _find(issues, issue_id)
        if issue is None:
            raise HTTPException(
                status_code=404,
                detail="Issue not found",
            )
        if body.title is not None:
            issue["title"] = body.title
        if body.description is not None:
            issue["description"] = body.description
        if is_multi_user_enabled() and issue["status"] == "in_progress":
            if body.status not in (None,"in_progress") or body.assignee not in (None, issue["assignee"]):
                raise HTTPException(409, "Stop the running issue before changing its assignment or state")

        # Apply assignee first so the status check below sees it.
        old_assignee = issue.get("assignee") or ""
        if body.assignee is not None:
            issue["assignee"] = body.assignee

        new_assignee = issue.get("assignee") or ""

        if body.status is not None:
            if body.status not in VALID_STATUS:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid status",
                )
            if body.status == "todo" and not new_assignee:
                raise HTTPException(
                    status_code=400,
                    detail="Moving to todo requires an assignee",
                )
            # Only allow moving to review from done status
            if body.status == "review" and issue.get("status") != "done":
                raise HTTPException(
                    status_code=400,
                    detail="Only done issues can be moved to review",
                )
            issue["status"] = body.status
            if body.status == "backlog":
                # Clear error and in-memory trace when moving to backlog
                issue.pop("error", None)
                _LIVE_TRACE.pop(issue_id, None)

        # Auto-promote: assigning an agent to a backlog issue
        # moves it to todo automatically.
        if (
            not old_assignee
            and new_assignee
            and issue.get("status") == "backlog"
        ):
            issue["status"] = "todo"

        # If the issue just became todo with an assignee and
        # that agent is idle, schedule auto-dispatch after the
        # txn releases the lock.
        if (
            issue.get("status") == "todo"
            and new_assignee
            and not _agent_has_running(new_assignee, issues)
        ):
            trigger_agent = new_assignee

        issue["updated_at"] = _now()
        _write_all(issues)

    if trigger_agent:
        if is_multi_user_enabled():
            return await run_issue(issue_id, ctx)
        _LAST_CTX.setdefault(trigger_agent, ctx)
        # Background dispatcher will pick up this task automatically

    return issue


@router.delete("/issues/{issue_id:path}")
async def delete_issue(
    issue_id: str,
    ctx=Depends(get_ctx),
) -> Dict[str, Any]:
    """Remove an issue from the board and its session data."""
    issue = None
    async with _txn():
        issues = _read_all()
        issue = _find(issues, issue_id)
        if issue is None:
            raise HTTPException(status_code=404, detail="Issue not found")
        issues = [i for i in issues if i.get("id") != issue_id]
        _write_all(issues)

    # Delete the session file for this issue
    if issue and issue.get("assignee"):
        try:
            # Use the assignee's agent_id to find the correct workspace
            from dataclasses import replace

            agent_ctx = replace(ctx, agent_id=issue["assignee"])
            # pylint: disable=protected-access
            workspace = await agent_ctx._get_workspace()
            if workspace and hasattr(workspace, "session"):
                session_mgr = workspace.session
                # pylint: disable=protected-access
                session_path = session_mgr._get_save_path(
                    session_id=issue_id,
                    user_id=agent_ctx.user_id,
                    channel=agent_ctx.channel,
                )
                try:
                    os.remove(session_path)
                    logger.info(
                        "[kanban] Deleted session file for issue %s",
                        issue_id,
                    )
                except FileNotFoundError:
                    pass  # Already deleted or never existed
        except Exception:  # noqa: BLE001
            logger.warning(
                "[kanban] Failed to delete session for issue %s",
                issue_id,
                exc_info=True,
            )

    return {"ok": True}


async def _execute_run(
    ctx: Any,
    issue_id: str,
    prompt: str,
    assignee: str = "",
) -> None:
    """Background worker: run the agent and persist the outcome.

    Detached from the HTTP request so ``/stop`` can cancel it.
    On ``CancelledError`` (user pressed stop) the status/log is
    handled by the stop handler, so we re-raise without writing
    a result.

    After completion (success or failure), auto-dispatches the
    next queued issue for the same *assignee* via
    ``_try_dispatch_next``.
    """
    # Shallow-copy ctx so we don't mutate the cached _LAST_CTX
    # instance, and set agent_id to the assignee so the correct
    # tool execution policy (approval_level) is applied.
    if assignee:
        ctx = dataclasses.replace(ctx, agent_id=assignee)

    error = ""
    _LIVE_TRACE[issue_id] = []
    trace = _LIVE_TRACE[issue_id]

    def _ch() -> Any:
        return _CHANNELS.get(issue_id)

    try:
        logger.info(
            "[kanban] _execute_run started for %s (agent=%s)",
            issue_id,
            assignee,
        )
        # Clear session to avoid context pollution across runs
        async for ev in ctx.chat_stream(
            "/clear",
            session_id=issue_id,
        ):
            pass  # Consume clear events
        async for ev in ctx.chat_stream(
            prompt,
            session_id=issue_id,
        ):
            logger.debug(
                "[kanban] ev type=%s delta=%s",
                getattr(ev, "type", "?"),
                getattr(ev, "delta", "?"),
            )
            # Skip delta=True events
            # (no live streaming, only show complete messages)
            if getattr(ev, "delta", False):
                continue

            # Store complete event (delta=False) to in-memory trace
            try:
                if hasattr(ev, "model_dump"):
                    ev_dict = ev.model_dump()
                elif hasattr(ev, "dict"):
                    ev_dict = ev.dict()
                elif dataclasses.is_dataclass(ev):
                    ev_dict = dataclasses.asdict(ev)
                else:
                    ev_dict = {"raw": str(ev)}
                trace.append(ev_dict)
            except Exception:  # noqa: BLE001
                pass

            # Send SSE notifications
            raw_type = getattr(ev, "type", None)
            if hasattr(raw_type, "value"):
                raw_type = raw_type.value
            msg_type = str(raw_type) if raw_type else ""

            # Tool call start
            if "_output" not in msg_type and any(
                k in msg_type
                for k in ("plugin_call", "function_call", "mcp_tool_call")
            ):
                name = ""
                content = getattr(ev, "content", None)
                if isinstance(content, list):
                    for blk in content:
                        data = getattr(blk, "data", None)
                        if isinstance(data, dict):
                            name = data.get("name", "")
                        elif data:
                            name = getattr(data, "name", "")
                        if name:
                            break
                if not name:
                    name = getattr(ev, "name", "")
                # Skip internal tools like "assistant"
                if name and name != "assistant":
                    ch = _ch()
                    if ch is not None:
                        await ch.send_event(
                            {"type": "tool_start", "name": name},
                        )

            # Tool call completion
            elif any(
                k in msg_type
                for k in (
                    "plugin_call_output",
                    "function_call_output",
                    "mcp_tool_call_output",
                )
            ):
                name = ""
                content = getattr(ev, "content", None)
                if isinstance(content, list):
                    for blk in content:
                        data = getattr(blk, "data", None)
                        if isinstance(data, dict):
                            name = data.get("name", "")
                        elif data:
                            name = getattr(data, "name", "")
                        if name:
                            break
                if not name:
                    name = getattr(ev, "name", "")
                # Skip internal tools
                if name and name != "assistant":
                    ch = _ch()
                    if ch is not None:
                        await ch.send_event(
                            {"type": "tool_done", "name": name},
                        )

            elif msg_type in {"reasoning", "message"} and getattr(ev, "status", "") == "completed":
                channel = _ch()
                if channel is not None:
                    for block in getattr(ev, "content", []):
                        text = getattr(block, "text", None)
                        if text:
                            await channel.send_event({"type": "message", "text": text})

        logger.info(
            "[kanban] stream done for %s: %d trace entries",
            issue_id,
            len(trace),
        )
    except asyncio.CancelledError:  # pylint: disable=try-except-raise
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("[kanban] _execute_run error for %s", issue_id)
        error = str(e)

    async with _txn():
        issues = _read_all()
        issue = _find(issues, issue_id)
        if issue is None:
            ch = _ch()
            if ch is not None:
                ch.close()
            return
        # Clear in-memory trace (result is in session now)
        _LIVE_TRACE.pop(issue_id, None)
        if error:
            issue["status"] = "todo"
            # Only store error in issue
            issue["error"] = error
        else:
            issue["status"] = "review"
            # Remove error if previous run had one
            issue.pop("error", None)
        issue["updated_at"] = _now()
        _write_all(issues)

    ch = _ch()
    if ch is not None:
        if error:
            await ch.send_event(
                {"type": "error", "message": error},
            )
        else:
            await ch.send_event(
                {"type": "done"},
            )
        ch.close()

    # Background dispatcher will pick up the next task automatically
    if is_multi_user_enabled():
        queued = next((item for item in issues if item["status"] == "todo"
                       and not item.get("error") and item["assignee"] == assignee), None)
        if queued:
            await run_issue(queued["id"], ctx)


def _launch_run(
    ctx: Any,
    issue_id: str,
    prompt: str,
    assignee: str,
) -> "asyncio.Task":
    """Create SSE channel + background task for a single run."""
    old_ch = _CHANNELS.pop(issue_id, None)
    if old_ch is not None:
        old_ch.close()
    _CHANNELS[issue_id] = SSEBroadcast()

    old = _RUNNING.pop(issue_id, None)
    if old is not None and not old.done():
        old.cancel()

    task = asyncio.create_task(
        _execute_run(ctx, issue_id, prompt, assignee),
    )
    _RUNNING[issue_id] = task

    def _cleanup(
        t: "asyncio.Task",
        _id: str = issue_id,
    ) -> None:
        if _RUNNING.get(_id) is t:
            _RUNNING.pop(_id, None)
            channel = _CHANNELS.get(_id)
            if channel:
                channel.close()
                def expire():
                    if _CHANNELS.get(_id) is channel and not channel.subscribers:
                        _CHANNELS.pop(_id, None)
                asyncio.get_running_loop().call_later(60, expire)

    task.add_done_callback(_cleanup)
    return task


# Stored reference to ctx from the most recent run so that
# Cached PawAppContext per agent (populated by HTTP requests and
# used by background dispatcher). PawAppContext is lightweight and
# the workspace registry it holds is a long-lived singleton.
_LAST_CTX: Dict[str, Any] = {}


@router.post("/issues/{issue_id:path}/run")
async def run_issue(
    issue_id: str,
    ctx=Depends(get_ctx),
) -> Dict[str, Any]:
    """Dispatch the issue to its assigned agent (non-blocking).

    If the agent is busy, the issue is queued as ``todo`` and will
    be auto-dispatched when the agent becomes idle.
    """
    async with _txn():
        issues = _read_all()
        issue = _find(issues, issue_id)
        if issue is None:
            raise HTTPException(
                status_code=404,
                detail="Issue not found",
            )
        assignee = issue.get("assignee")
        if not assignee:
            raise HTTPException(
                status_code=400,
                detail="Cannot run issue without assignee",
            )

        if issue.get("status") == "in_progress" and is_multi_user_enabled():
            return issue
        if _agent_has_running(assignee, issues):
            issue["status"] = "todo"
            issue["updated_at"] = _now()
            _write_all(issues)
            if not is_multi_user_enabled():
                _LAST_CTX.setdefault(assignee, ctx)
            return issue

        issue["status"] = "in_progress"
        # Clear error when starting a new run
        issue.pop("error", None)
        issue["updated_at"] = _now()
        _write_all(issues)
        title = issue["title"]
        description = issue.get("description") or "(无描述)"

    prompt = (
        "你被指派处理以下看板任务(Issue):\n"
        f"标题: {title}\n"
        f"描述: {description}\n\n"
        "请完成该任务，并用简洁的中文汇报你的处理结果。"
    )

    if not is_multi_user_enabled():
        _LAST_CTX[assignee] = ctx
    _launch_run(ctx, issue_id, prompt, assignee)
    return issue


@router.get("/issues/{issue_id:path}/stream")
async def stream_issue(issue_id: str) -> StreamingResponse:
    """SSE stream of the agent's realtime output for an issue.

    The channel is created by ``run_issue`` before the background task starts,
    so deltas emitted before the browser connects are buffered and replayed.
    """
    if is_multi_user_enabled() and _find(await asyncio.to_thread(_read_all), issue_id) is None:
        raise HTTPException(404, "Issue not found")
    channel = _CHANNELS.setdefault(issue_id, SSEBroadcast())

    async def _gen():
        stream = channel.stream()
        try:
            async for chunk in stream:
                yield chunk
        finally:
            await stream.aclose()
            if not channel.subscribers and issue_id not in _RUNNING and _CHANNELS.get(issue_id) is channel:
                _CHANNELS.pop(issue_id, None)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/issues/{issue_id:path}/result")
async def get_issue_result(
    issue_id: str,
    ctx=Depends(get_ctx),
) -> Dict[str, Any]:
    """Get the complete history of an issue from session or trace.

    Returns all assistant messages from the session.
    """
    issues = await asyncio.to_thread(_read_all)
    issue = _find(issues, issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")

    # If there's an error, return it directly
    if "error" in issue:
        return {"error": issue["error"]}

    # Try to get from session first
    # IMPORTANT: Use issue's assignee agent_id to query the correct workspace
    agent_ctx = ctx
    if issue.get("assignee"):
        from dataclasses import replace

        agent_ctx = replace(ctx, agent_id=issue["assignee"])

    try:
        history = await agent_ctx.get_session_history(session_id=issue_id)
        if history:
            # Return all assistant messages
            assistant_messages = [
                msg for msg in history if msg.get("role") == "assistant"
            ]
            if assistant_messages:
                return {"messages": assistant_messages}
    except Exception:  # noqa: BLE001
        logger.exception(
            "[kanban] Failed to get session history for %s (assignee=%s)",
            issue_id,
            issue.get("assignee"),
        )

    # Fallback to in-memory trace if session is empty or failed
    # (only for running tasks)
    trace = _LIVE_TRACE.get(issue_id, [])
    if not trace:
        return {"messages": []}

    # Reconstruct messages from trace events
    messages = []
    current_content = []

    for ev_dict in trace:
        ev_type = ev_dict.get("type", "")
        if isinstance(ev_type, dict):
            ev_type = ev_type.get("value", "")
        ev_type = str(ev_type)

        # Tool call completion - add as content item
        if any(
            k in ev_type
            for k in (
                "plugin_call_output",
                "function_call_output",
                "mcp_tool_call_output",
            )
        ):
            content = ev_dict.get("content", [])
            if isinstance(content, list) and content:
                for item in content:
                    if isinstance(item, dict):
                        data = item.get("data", {})
                        name = (
                            data.get("name", "")
                            if isinstance(
                                data,
                                dict,
                            )
                            else ""
                        )
                        if name and name != "assistant":
                            current_content.append(
                                {
                                    "type": ev_type,
                                    "data": {"name": name},
                                },
                            )

        # Text message - add text content
        elif ev_type == "message" and ev_dict.get("role") == "assistant":
            for c in ev_dict.get("content", []):
                if isinstance(c, dict) and c.get("type") == "text":
                    text = c.get("text", "")
                    if text:
                        current_content.append({"type": "text", "text": text})

    # Create a single synthetic message from all trace content
    if current_content:
        messages.append(
            {
                "role": "assistant",
                "content": current_content,
            },
        )

    return {"messages": messages}


@router.post("/issues/{issue_id:path}/stop")
async def stop_issue(issue_id: str) -> Dict[str, Any]:
    """Stop a running issue: cancel its background task and reset status."""
    if is_multi_user_enabled() and _find(await asyncio.to_thread(_read_all), issue_id) is None:
        raise HTTPException(404, "Issue not found")
    task = _RUNNING.pop(issue_id, None)
    if task is not None and not task.done():
        task.cancel()
    ch = _CHANNELS.pop(issue_id, None)
    if ch is not None:
        ch.close()
    async with _txn():
        issues = _read_all()
        issue = _find(issues, issue_id)
        if issue is None:
            raise HTTPException(
                status_code=404,
                detail="Issue not found",
            )
        if issue.get("status") == "in_progress":
            issue["status"] = "backlog"
            # Clear error when stopping
            issue.pop("error", None)
            issue["updated_at"] = _now()
            _write_all(issues)
            _LIVE_TRACE.pop(issue_id, None)
        # Background dispatcher will pick up next task automatically

    return issue


def _approval_belongs_to_board(pending, issue_ids=None) -> bool:
    if not is_multi_user_enabled():
        return True
    scope = current_plugin_scope.get()
    if scope is None or pending.approval_user_id != str(scope.user_id) or pending.owner_agent_id != scope.agent_id:
        return False
    if issue_ids is None:
        issue_ids = {i["id"] for i in _read_all() if i["status"] == "in_progress"}
    return pending.session_id.rsplit(":", 1)[-1] in issue_ids


@router.get("/approvals")
async def list_kanban_approvals() -> Dict[str, Any]:
    """Return pending approvals for all in_progress kanban issues.

    Queries the global ApprovalService for approvals whose
    ``session_id`` matches ``pawapp:agent-kanban:<issue_id>``.
    """
    try:
        from qwenpaw.app.approvals import get_approval_service
        from qwenpaw.app.approvals.display import (
            approval_display_fields,
        )
    except ImportError:
        return {"approvals": {}}

    svc = get_approval_service()
    issues = await asyncio.to_thread(_read_all)
    running_ids = {
        iss["id"] for iss in issues if iss.get("status") == "in_progress"
    }
    if not running_ids:
        return {"approvals": {}}

    # pylint: disable=protected-access
    result: Dict[str, List[Dict[str, Any]]] = {}
    async with svc._lock:
        for p in svc._pending.values():
            if p.status != "pending" or not _approval_belongs_to_board(p, running_ids):
                continue
            sid = p.session_id or ""
            for iid in running_ids:
                if sid == iid or sid.endswith(f":{iid}"):
                    result.setdefault(iid, []).append(
                        {
                            "request_id": p.request_id,
                            "session_id": p.session_id,
                            "root_session_id": (p.root_session_id),
                            "tool_name": p.tool_name,
                            "agent_id": p.agent_id,
                            "severity": p.severity,
                            **approval_display_fields(p),
                            "created_at": p.created_at,
                        },
                    )
    return {"approvals": result}


@router.post("/approvals/{request_id}/approve")
async def approve_kanban(request_id: str) -> Dict[str, Any]:
    """Approve a pending tool execution from the kanban UI.

    Looks up the pending approval by *request_id* and resolves
    it using its own ``root_session_id``, so the frontend does
    not need to know the session topology.
    """
    try:
        from qwenpaw.app.approvals import get_approval_service
        from qwenpaw.security.tool_guard.approval import (
            ApprovalDecision,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=501,
            detail="Approval service unavailable",
        ) from exc

    svc = get_approval_service()
    pending = await svc.get_request(request_id)
    if pending is None or not _approval_belongs_to_board(pending):
        raise HTTPException(
            status_code=404,
            detail="Approval request not found",
        )
    await svc.resolve_request(
        request_id,
        ApprovalDecision.APPROVED,
    )
    return {"ok": True, "tool_name": pending.tool_name}


@router.post("/approvals/{request_id}/deny")
async def deny_kanban(request_id: str) -> Dict[str, Any]:
    """Deny a pending tool execution from the kanban UI."""
    try:
        from qwenpaw.app.approvals import get_approval_service
        from qwenpaw.security.tool_guard.approval import (
            ApprovalDecision,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=501,
            detail="Approval service unavailable",
        ) from exc

    svc = get_approval_service()
    pending = await svc.get_request(request_id)
    if pending is None or not _approval_belongs_to_board(pending):
        raise HTTPException(
            status_code=404,
            detail="Approval request not found",
        )
    await svc.resolve_request(
        request_id,
        ApprovalDecision.DENIED,
    )
    return {"ok": True, "tool_name": pending.tool_name}


@router.get("/queue/{agent_id:path}")
async def get_agent_queue(agent_id: str) -> Dict[str, Any]:
    """Return the todo queue and running status for *agent_id*."""
    issues = await asyncio.to_thread(_read_all)
    running = None
    queue: List[Dict[str, Any]] = []
    for iss in issues:
        if iss.get("assignee") != agent_id:
            continue
        if iss.get("status") == "in_progress":
            running = {
                "id": iss["id"],
                "title": iss.get("title", ""),
            }
        elif iss.get("status") == "todo":
            queue.append(
                {
                    "id": iss["id"],
                    "title": iss.get("title", ""),
                },
            )
    return {
        "agent_id": agent_id,
        "running": running,
        "queue": queue,
    }


# ── PawApp definition + agent-facing tools ───────────────────────────
app = PawApp(name="Agent Kanban", app_id="agent-kanban")
app.include_router(router)

# ── Background persistence loop ────────────────────────────────────


async def _persist_loop() -> None:
    """Background loop: periodically persist dirty cache to disk.

    Runs every 10 seconds, only writes if cache is dirty.
    """
    global _PERSIST_RUNNING, _CACHE_DIRTY, _CACHE_VERSION
    _PERSIST_RUNNING = True
    logger.info("[kanban] Persistence loop started")

    while _PERSIST_RUNNING:
        try:
            await asyncio.sleep(10)  # Persist every 10 seconds

            if _CACHE_DIRTY and _ISSUES_CACHE is not None:
                # Snapshot version before persisting
                snapshot_version = _CACHE_VERSION
                await asyncio.to_thread(_persist_to_disk, _ISSUES_CACHE[:])
                # Only clear dirty if no new changes occurred during persist
                if _CACHE_VERSION == snapshot_version:
                    _CACHE_DIRTY = False
                    logger.debug("[kanban] Cache persisted to disk")
                else:
                    logger.debug(
                        "[kanban] Cache persisted, but new changes detected",
                    )

        except asyncio.CancelledError:
            logger.info("[kanban] Persistence loop cancelled")
            break
        except Exception:  # noqa: BLE001
            logger.exception("[kanban] Persistence loop error")

    _PERSIST_RUNNING = False
    logger.info("[kanban] Persistence loop stopped")


# ── Background dispatcher loop ────────────────────────────────────


async def _dispatch_loop() -> None:
    """Background loop: auto-dispatch todo/orphaned in_progress tasks.

    Runs continuously after startup. For each agent with queued tasks,
    if the agent is idle, dispatch the next task.
    """
    global _DISPATCHER_RUNNING
    _DISPATCHER_RUNNING = True
    logger.info("[kanban] Dispatcher loop started")

    while _DISPATCHER_RUNNING:
        try:
            await asyncio.sleep(30)  # Check every 30 seconds

            issues = await asyncio.to_thread(_read_all)
            if not issues:
                continue

            # Group issues by agent
            agent_tasks: Dict[str, List[Dict[str, Any]]] = {}
            for issue in issues:
                assignee = issue.get("assignee")
                if not assignee:
                    continue
                status = issue.get("status")
                # Collect in_progress (orphaned) and todo tasks
                if status in ("in_progress", "todo"):
                    agent_tasks.setdefault(assignee, []).append(issue)

            # For each agent with tasks, try to dispatch
            for agent_id, tasks in agent_tasks.items():
                # Get cached ctx for this agent (populated by HTTP requests)
                ctx = _LAST_CTX.get(agent_id)
                if not ctx:
                    # Skip if no ctx cached yet (wait for first HTTP request)
                    continue

                # Check if agent is idle (no running task for this agent)
                agent_running = any(
                    iss["id"] in _RUNNING
                    for iss in issues
                    if iss.get("assignee") == agent_id
                    and iss.get("status") == "in_progress"
                )
                if agent_running:
                    continue

                # Find highest priority task:
                # 1. in_progress (orphaned from restart) - highest priority
                # 2. todo (queued)
                candidate = None
                for task in tasks:
                    if task.get("status") == "in_progress":
                        # Orphaned task - check if it's really not running
                        if task["id"] not in _RUNNING:
                            candidate = task
                            break
                if not candidate:
                    # No orphaned tasks, pick first todo
                    for task in tasks:
                        if task.get("status") == "todo":
                            candidate = task
                            break

                if candidate:
                    # Dispatch the candidate
                    async with _txn():
                        issues_fresh = _read_all()
                        issue_fresh = _find(issues_fresh, candidate["id"])
                        if issue_fresh and issue_fresh.get(
                            "status",
                        ) in (
                            "in_progress",
                            "todo",
                        ):
                            issue_fresh["status"] = "in_progress"
                            issue_fresh.pop("error", None)
                            issue_fresh["updated_at"] = _now()
                            _write_all(issues_fresh)

                            title = issue_fresh["title"]
                            desc = issue_fresh.get("description") or "(无描述)"
                            prompt = (
                                "你被指派处理以下看板任务(Issue):\n"
                                f"标题: {title}\n"
                                f"描述: {desc}\n\n"
                                "请完成该任务，并用简洁的中文汇报你的处理结果。"
                            )
                            logger.info(
                                "[kanban] Dispatcher: "
                                "launching %s for agent %s",
                                candidate["id"],
                                agent_id,
                            )
                            _launch_run(
                                ctx,
                                candidate["id"],
                                prompt,
                                agent_id,
                            )

        except asyncio.CancelledError:
            logger.info("[kanban] Dispatcher loop cancelled")
            break
        except Exception:  # noqa: BLE001
            logger.exception("[kanban] Dispatcher loop error")

    _DISPATCHER_RUNNING = False
    logger.info("[kanban] Dispatcher loop stopped")


# ── Lifecycle: startup and shutdown ────────────────────────────────


@app.on_launch
async def init_kanban():
    """Initialize kanban on app launch.

    1. Load issues from disk into memory cache
    2. Start background dispatcher loop
    3. Start background persistence loop
    """
    global _ISSUES_CACHE, _DISPATCHER_TASK, _PERSIST_TASK
    if is_multi_user_enabled():
        return

    # Load cache from disk
    try:
        _ISSUES_CACHE = await asyncio.to_thread(_load_from_disk)
        logger.info(
            "[kanban] Loaded %d issues from disk into cache",
            len(_ISSUES_CACHE),
        )
    except Exception:  # noqa: BLE001
        logger.exception("[kanban] Failed to load issues from disk")
        _ISSUES_CACHE = []

    # Start dispatcher
    if _DISPATCHER_TASK is None or _DISPATCHER_TASK.done():
        _DISPATCHER_TASK = asyncio.create_task(_dispatch_loop())
        logger.info("[kanban] Dispatcher task started")

    # Start persistence loop
    if _PERSIST_TASK is None or _PERSIST_TASK.done():
        _PERSIST_TASK = asyncio.create_task(_persist_loop())
        logger.info("[kanban] Persistence task started")


@app.on_terminate
async def shutdown_kanban():
    """Shutdown kanban on app terminate.

    1. Stop background loops
    2. Persist cache to disk (critical - ensure no data loss)
    """
    global _DISPATCHER_RUNNING, _PERSIST_RUNNING
    global _DISPATCHER_TASK, _PERSIST_TASK
    if is_multi_user_enabled():
        tasks = list(_RUNNING.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        return

    # Stop dispatcher
    _DISPATCHER_RUNNING = False
    if _DISPATCHER_TASK and not _DISPATCHER_TASK.done():
        _DISPATCHER_TASK.cancel()
        try:
            await _DISPATCHER_TASK
        except asyncio.CancelledError:
            pass
        logger.info("[kanban] Dispatcher task stopped")

    # Stop persistence loop
    _PERSIST_RUNNING = False
    if _PERSIST_TASK and not _PERSIST_TASK.done():
        _PERSIST_TASK.cancel()
        try:
            await _PERSIST_TASK
        except asyncio.CancelledError:
            pass
        logger.info("[kanban] Persistence task stopped")

    # Final persist (critical)
    if _CACHE_DIRTY and _ISSUES_CACHE is not None:
        try:
            await asyncio.to_thread(_persist_to_disk, _ISSUES_CACHE[:])
            logger.info("[kanban] Final cache persist completed")
        except Exception:  # noqa: BLE001
            logger.exception("[kanban] Failed to persist cache on shutdown")


# The 'plugin' variable is what PluginLoader looks for.
plugin = app
