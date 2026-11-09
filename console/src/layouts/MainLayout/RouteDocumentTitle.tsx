import { useLayoutEffect } from "react";
import { useSessionListStore } from "../../stores/sessionListStore";

export function RouteDocumentTitle({
  title,
  sessionId,
}: {
  title: string;
  sessionId?: string;
}) {
  const sessionName = useSessionListStore((state) =>
    sessionId && sessionId !== "new"
      ? state.sessions
          .find(
            (session) =>
              session.id === sessionId ||
              session.realId === sessionId ||
              session.sessionId === sessionId,
          )
          ?.name?.trim()
      : undefined,
  );

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
