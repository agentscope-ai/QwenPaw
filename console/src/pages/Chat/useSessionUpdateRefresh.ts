import {
  useEffect,
  type Dispatch,
  type RefObject,
  type SetStateAction,
} from "react";
import {
  SESSION_UPDATED_EVENT,
  type SessionUpdatedEventDetail,
} from "../../events/sessionUpdate";

export function useSessionUpdateRefresh(
  chatIdRef: RefObject<string | null | undefined>,
  setRefreshKey: Dispatch<SetStateAction<number>>,
) {
  useEffect(() => {
    const handler = (e: Event) => {
      const { sessionId } = (e as CustomEvent<SessionUpdatedEventDetail>)
        .detail;
      if (sessionId && sessionId === chatIdRef.current) {
        setRefreshKey((k) => k + 1);
      }
    };
    window.addEventListener(SESSION_UPDATED_EVENT, handler);
    return () => window.removeEventListener(SESSION_UPDATED_EVENT, handler);
  }, [chatIdRef, setRefreshKey]);
}
