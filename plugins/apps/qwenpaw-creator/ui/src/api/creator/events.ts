import type { CreatorEvent } from "@/contracts/creator";
import { creatorAuthenticatedUrl } from "./client";

export interface CreatorEventStream {
  close(): void;
}

const CREATOR_EVENT_TYPES = [
  "session.created",
  "session.status_changed",
  "session.waiting_runtime",
  "message.accepted",
  "message.queued",
  "message.appended",
  "message.classified",
  "message.completed",
  "command.autosave_admitted",
  "command.queued",
  "creation.checkpoint_required",
  "creation.checkpoint_decided",
  "agent.message_delta",
  "agent.model.rate_limit_retry",
  "agent.model.retry",
  "agent.model.retry_recovered",
  "agent.mainline.resumed",
  "agent.prompt_contract.resumed",
  "agent.yolo.resumed",
  "agent.tool_arguments_checked",
  "agent.tool_progress",
  "assistant.output_rejected",
  "agent.plan",
  "agent.tool_started",
  "agent.tool_completed",
  "agent.run.started",
  "agent.run.completed",
  "agent.run.failed",
  "agent.run.cancelled",
  "agent.assistant_message",
  "agent.tool.started",
  "agent.tool.completed",
  "agent.tool.failed",
  "agent.review.resolved",
  "agent.interrupt.idle",
  "subagent.accepted",
  "subagent.started",
  "subagent.waiting_runtime",
  "subagent.resumed",
  "subagent.completed",
  "subagent.blocked",
  "subagent.failed",
  "subagent.stale",
  "subagent.continuation_started",
  "subagent.continuation_completed",
  "subagent.message_delta",
  "subagent.model.retry",
  "subagent.model.retry_recovered",
  "subagent.message_completed",
  "subagent.tool_progress",
  "subagent.tool_arguments_checked",
  "subagent.tool_started",
  "subagent.tool_completed",
  "task.registered",
  "task.started",
  "task.completed",
  "task.failed",
  "task.cancelled",
  "task.quarantined",
  "task.progress_updated",
  "task.retry_scheduled",
  "creator.yielded",
  "creator.woken",
  "runtime.work_update_appended",
  "workspace.head_changed",
  "workspace.manual_edit_committed",
  "task_progress.updated",
  "task_milestone.completed",
  "transaction.started",
  "transaction.progress",
  "execution.authorization_required",
  "execution.authorization_decided",
  "transaction.completion_check_failed",
  "change_request.completed",
  "transaction.review_available",
  "transaction.pending_review",
  "review.comment_added",
  "review.group_accepted",
  "review.group_applied",
  "review.group_rejected",
  "review.group_revision_requested",
  "review.group_superseded_by_user_edit",
  "review.completed",
  "session.resuming",
  "session.error",
] as const;

/** Durable project stream. `after`: persisted seq cursor for reconnect. */
export function openCreatorEvents(
  projectId: string,
  after: number,
  onEvent: (event: CreatorEvent) => void,
  onError?: () => void,
  onOpen?: () => void,
): CreatorEventStream {
  let closed = false;
  let cursor = Math.max(0, after);
  let source: EventSource | null = null;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;
  let retryDelay = 1000;
  const connect = () => {
    if (closed) return;
    const path = `/projects/${encodeURIComponent(
      projectId,
    )}/events?after=${cursor}`;
    const current = new EventSource(creatorAuthenticatedUrl(path), {
      withCredentials: true,
    });
    source = current;
    const consume = (message: MessageEvent<string>) => {
      if (closed || source !== current) return;
      try {
        const event = JSON.parse(message.data) as CreatorEvent;
        if (
          Number.isInteger(event.seq) &&
          event.seq > cursor &&
          event.eventId
        ) {
          onEvent(event);
          cursor = event.seq;
        }
      } catch {
        // Malformed events do not advance the durable resume cursor.
      }
    };
    current.onmessage = consume;
    CREATOR_EVENT_TYPES.forEach((type) =>
      current.addEventListener(type, consume as EventListener),
    );
    current.onopen = () => {
      if (closed || source !== current) return;
      retryDelay = 1000;
      onOpen?.();
    };
    current.onerror = () => {
      if (closed || source !== current) return;
      onError?.();
      // A temporary 404 while plugin routes are loading permanently closes
      // native EventSource. Own retries for both CLOSED and CONNECTING states
      // so a restart recovers without reloading the page or replaying from 0.
      current.close();
      source = null;
      retryTimer = setTimeout(() => {
        retryTimer = null;
        connect();
      }, retryDelay);
      retryDelay = Math.min(retryDelay * 2, 30000);
    };
  };
  connect();
  return {
    close: () => {
      closed = true;
      if (retryTimer != null) clearTimeout(retryTimer);
      retryTimer = null;
      source?.close();
      source = null;
    },
  };
}
