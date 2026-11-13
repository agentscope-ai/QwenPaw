import { useLayoutEffect, useMemo } from "react";
import { useSessionAttention } from "../../hooks/useSessionAttention";
import { useSessionFavicon } from "../../hooks/useSessionFavicon";
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
  const running = session?.generating === true || session?.status === "running";
  useSessionFavicon(running, unread);

  useLayoutEffect(() => {
    const nextTitle = sessionName
      ? `${sessionName} · QwenPaw`
      : title === "QwenPaw"
      ? title
      : `${title} · QwenPaw`;
    document.title = nextTitle;
    document.dispatchEvent(
      new CustomEvent("qwenpaw:document-title-change", {
        detail: nextTitle,
      }),
    );
  }, [title, sessionName]);

  return null;
}
