import { useEffect, useState } from "react";
import { GitFork } from "lucide-react";
import { IconButton } from "@agentscope-ai/design";
import { chatApi } from "../../api/modules/chat";
import { extractTranscriptTurnId, type CopyableResponse } from "./utils";

export function TurnForkAction({
  data,
  chatId,
  agentId,
  onFork,
  title,
}: {
  data: CopyableResponse;
  chatId?: string;
  agentId: string;
  onFork: (data: CopyableResponse) => void;
  title: string;
}) {
  const hasOutput = (data.output || []).some(
    (message) =>
      message.role !== "user" &&
      message.type !== "heartbeat" &&
      (typeof message.content === "string"
        ? Boolean(message.content.trim())
        : message.content?.some((part) =>
            part.type === "text"
              ? Boolean(part.text?.trim())
              : Boolean(part.type),
          )),
  );
  const turnId = extractTranscriptTurnId(data);
  const [available, setAvailable] = useState<string>();
  const status = (data as { status?: string }).status;
  const history =
    Boolean(data.metadata?.qwenpaw_history) &&
    data.metadata?.fork_capability_status !== "in_progress";
  const key = `${agentId}:${chatId}:${turnId}:${status}`;
  useEffect(() => {
    setAvailable(undefined);
    if (!hasOutput || history) return;
    if (!status || status === "in_progress" || !chatId || !turnId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const check = async (attempt = 0) => {
      try {
        const result = await chatApi.forkCapability(chatId, turnId, agentId);
        if (cancelled) return;
        if (result.can_fork) setAvailable(key);
        // Local stop can precede the final persistence acknowledgement.
        else if (status === "canceled" && attempt < 5)
          timer = setTimeout(() => void check(attempt + 1), 500);
      } catch {
        // Unconfirmed capability stays hidden.
      }
    };
    void check();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [chatId, agentId, turnId, key, status, history, hasOutput]);
  if (
    !hasOutput ||
    (history ? data.metadata?.can_fork !== true : available !== key)
  )
    return null;
  return (
    <IconButton
      bordered={false}
      size="small"
      aria-label={title}
      icon={
        <span title={title}>
          <GitFork size={16} />
        </span>
      }
      onClick={() => onFork(data)}
    />
  );
}
