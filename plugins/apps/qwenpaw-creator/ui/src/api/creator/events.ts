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
  const path = `/projects/${encodeURIComponent(
    projectId,
  )}/events?after=${Math.max(0, after)}`;
  const source = new EventSource(creatorAuthenticatedUrl(path), {
    withCredentials: true,
  });
  let closed = false;
  const consume = (message: MessageEvent<string>) => {
    if (closed) return;
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
  source.onopen = () => {
    if (!closed) onOpen?.();
  };
  source.onerror = () => {
    if (!closed) onError?.();
  };
  return {
    close: () => {
      closed = true;
      source.close();
    },
  };
}
