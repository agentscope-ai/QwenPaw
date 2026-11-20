import type { LoginResponse } from "./modules/auth";

export type SessionEvent =
  | { type: "renewed"; session: LoginResponse }
  | { type: "cleared"; sessionId?: string };

export function withSessionRefreshLock<T>(
  refresh: () => Promise<T>,
): Promise<T> {
  if (typeof navigator !== "undefined" && navigator.locks) {
    return navigator.locks.request("qwenpaw-session-refresh", refresh);
  }
  return refresh();
}

export function createSessionChannel(receive: (event: SessionEvent) => void) {
  const channel =
    typeof BroadcastChannel !== "undefined"
      ? new BroadcastChannel("qwenpaw-access-session")
      : null;
  if (channel)
    channel.onmessage = (event: MessageEvent<SessionEvent>) => {
      if (
        event.data?.type === "cleared" ||
        (event.data?.type === "renewed" &&
          typeof event.data.session?.token === "string")
      ) {
        receive(event.data);
      }
    };
  return {
    publish: (event: SessionEvent) => channel?.postMessage(event),
    close: () => channel?.close(),
  };
}
