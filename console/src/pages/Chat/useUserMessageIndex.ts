import { useCallback, useEffect, useRef, useState } from "react";
import sessionApi from "./sessionApi";
import { mergeNavigationUsers } from "./userMessageNavigation";
import type { HistoryUserMessage } from "./historyMessageWindowStore";

interface IndexPage {
  sessionId: string;
  items: HistoryUserMessage[];
  total: number;
  before?: string;
}

export function useUserMessageIndex(
  sessionId: string | undefined,
  usersKey: string,
) {
  const [page, setPage] = useState<IndexPage>();
  const [loading, setLoading] = useState(false);
  const current = useRef<IndexPage>();
  const controller = useRef<AbortController>();
  const pending = useRef<Promise<IndexPage | undefined>>();
  const publish = useCallback((next: IndexPage) => {
    current.current = next;
    setPage(next);
    return next;
  }, []);

  useEffect(() => {
    const abort = new AbortController();
    controller.current = abort;
    pending.current = undefined;
    setLoading(false);
    if (sessionId) {
      void sessionApi
        .loadUserMessageIndexPage(sessionId, undefined, abort.signal)
        .then((latest) => {
          if (abort.signal.aborted) return;
          const previous = current.current;
          const overlap =
            previous?.items.findIndex(
              (item) => item.messageId === latest.items[0]?.messageId,
            ) ?? -1;
          publish(
            previous?.sessionId === sessionId &&
              latest.total >= previous.total &&
              overlap >= 0
              ? {
                  ...latest,
                  sessionId,
                  items: [...previous.items.slice(0, overlap), ...latest.items],
                  before: previous.before,
                }
              : { ...latest, sessionId },
          );
        })
        .catch(() => {
          /* Keep the usable index; a later refresh can retry. */
        });
    }
    return () => abort.abort();
  }, [sessionId, usersKey, publish]);

  const loadOlder = useCallback((): Promise<IndexPage | undefined> => {
    if (pending.current) return pending.current;
    const previous = current.current;
    const abort = controller.current;
    if (
      !previous ||
      previous.sessionId !== sessionId ||
      !previous.before ||
      !abort
    )
      return Promise.resolve(previous);
    setLoading(true);
    const request = sessionApi
      .loadUserMessageIndexPage(
        previous.sessionId,
        previous.before,
        abort.signal,
      )
      .then((older) => {
        if (abort.signal.aborted) return undefined;
        const latest = current.current;
        if (!latest || latest.before !== previous.before) return latest;
        return publish({
          ...latest,
          items: mergeNavigationUsers(older.items, latest.items),
          before: older.before === previous.before ? undefined : older.before,
        });
      })
      .catch(() => undefined)
      .finally(() => {
        if (pending.current === request) {
          pending.current = undefined;
          setLoading(false);
        }
      });
    pending.current = request;
    return request;
  }, [sessionId, publish]);

  return {
    page: page?.sessionId === sessionId ? page : undefined,
    loading,
    loadOlder,
  };
}
