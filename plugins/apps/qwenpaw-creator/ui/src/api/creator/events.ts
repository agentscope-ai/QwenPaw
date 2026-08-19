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
  "agent.message_delta",
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
  "subagent.completed",
  "subagent.blocked",
  "subagent.failed",
  "subagent.stale",
  "subagent.continuation_started",
  "subagent.continuation_completed",
  "subagent.message_delta",
  "subagent.message_completed",
  "subagent.tool_progress",
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
): CreatorEventStream {
  const path = `/projects/${encodeURIComponent(
    projectId,
  )}/events?after=${Math.max(0, after)}`;
  const source = new EventSource(creatorAuthenticatedUrl(path), {
    withCredentials: true,
  });
  const consume = (message: MessageEvent<string>) => {
    try {
      const event = JSON.parse(message.data) as CreatorEvent;
      if (typeof event.seq === "number" && event.eventId) onEvent(event);
    } catch {
      // Malformed event payloads are ignored; the durable cursor is not advanced.
    }
  };
  source.onmessage = consume;
  CREATOR_EVENT_TYPES.forEach((type) =>
    source.addEventListener(type, consume as EventListener),
  );
  source.onerror = () => onError?.();
  return { close: () => source.close() };
}
