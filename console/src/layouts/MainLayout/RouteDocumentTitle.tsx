import { useLayoutEffect, useMemo } from "react";
import { useSessionAttention } from "../../hooks/useSessionAttention";
import { useAgentStore } from "../../stores/agentStore";
import {
  findSessionByReference,
  useSessionListStore,
} from "../../stores/sessionListStore";

export function RouteDocumentTitle({
  title,
  sessionId,
}: {
  title: string;
  sessionId?: string;
}) {
  const agentId = useAgentStore((state) => state.selectedAgent);
  const session = useSessionListStore((state) =>
    sessionId && sessionId !== "new"
      ? findSessionByReference(
          state.sessions,
          sessionId,
          state.resolvedRouteSession,
        )
      : undefined,
  );
  const sessions = useMemo(() => (session ? [session] : []), [session]);
  const unseenSessionIds = useSessionAttention(agentId, sessions, session?.id);
  const unread = !!session && unseenSessionIds.has(session.id);
  const sessionName = session?.name?.trim();

  useLayoutEffect(() => {
    const baseTitle = sessionName
      ? `${sessionName} · QwenPaw`
      : title === "QwenPaw"
      ? title
      : `${title} · QwenPaw`;
    const nextTitle = unread ? `• ${baseTitle}` : baseTitle;
    document.title = nextTitle;
    document.dispatchEvent(
      new CustomEvent("qwenpaw:document-title-change", {
        detail: nextTitle,
      }),
    );
  }, [title, sessionName, unread]);

  return null;
}
