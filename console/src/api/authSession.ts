import {
  clearAuthToken,
  getApiAuthMode,
  getApiToken,
  setAuthToken,
} from "./config";
import { isAuthenticationRejected } from "./authErrors";
import { authApi, type LoginResponse } from "./modules/auth";
import {
  createSessionChannel,
  withSessionRefreshLock,
} from "./authSessionSync";

const REFRESH_MARGIN_MS = 60_000;

let accessExpiresAt = 0;
let refreshPromise: Promise<boolean> | null = null;
let refreshTimer: ReturnType<typeof setTimeout> | null = null;
let sessionGeneration = 0;
let sessionUserId = "";
let deviceSessionId = "";
let refreshFailures = 0;
let retryAfter = 0;
let refreshError: unknown;
const generationListeners = new Set<() => void>();
const sessionListeners = new Set<(session: LoginResponse) => void>();

export function subscribeAccessSessionUpdates(
  listener: (session: LoginResponse) => void,
) {
  sessionListeners.add(listener);
  return () => {
    sessionListeners.delete(listener);
  };
}
let sessionChannel: ReturnType<typeof createSessionChannel> | null = null;

function getSessionChannel() {
  if (!sessionChannel)
    sessionChannel = createSessionChannel((event) => {
      if (getApiAuthMode() !== "multi_user") return;
      if (event.type === "cleared") {
        if (!event.sessionId || event.sessionId === deviceSessionId)
          clearAccessSession(false);
      } else adoptAccessSession(event.session, false);
    });
  return sessionChannel;
}

export const getAccessSessionGeneration = () => sessionGeneration;
export const getDeviceSessionId = () => deviceSessionId;
export function subscribeAccessSessionGeneration(listener: () => void) {
  generationListeners.add(listener);
  return () => {
    generationListeners.delete(listener);
  };
}

function parseExpiresAt(value?: string): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function cancelRefreshTimer(): void {
  if (refreshTimer !== null) {
    clearTimeout(refreshTimer);
    refreshTimer = null;
  }
}

function scheduleRefresh(retryDelay?: number): void {
  cancelRefreshTimer();
  if (getApiAuthMode() !== "multi_user" || accessExpiresAt === 0) return;
  const generation = sessionGeneration;
  const delay =
    retryDelay ??
    Math.max(1000, accessExpiresAt - Date.now() - REFRESH_MARGIN_MS);
  refreshTimer = setTimeout(() => {
    refreshTimer = null;
    void refreshAccessSession()
      .then((renewed) => {
        if (!renewed && generation === sessionGeneration) clearAccessSession();
      })
      .catch(() => {
        /* A transient failure schedules its own bounded retry. */
      });
  }, delay);
}

export function adoptAccessSession(
  response: LoginResponse,
  broadcast = true,
): void {
  if (
    sessionUserId &&
    response.user?.id &&
    sessionUserId !== response.user.id
  ) {
    clearAccessSession(false);
  }
  sessionUserId = response.user?.id ?? sessionUserId;
  deviceSessionId = response.session?.id ?? "";
  setAuthToken(response.token);
  refreshFailures = 0;
  retryAfter = 0;
  refreshError = undefined;
  accessExpiresAt = parseExpiresAt(response.access_expires_at);
  scheduleRefresh();
  sessionListeners.forEach((listener) => listener(response));
  if (broadcast && getApiAuthMode() === "multi_user")
    getSessionChannel().publish({ type: "renewed", session: response });
}

export function clearAccessSession(broadcast = true): void {
  const clearedSession = deviceSessionId;
  sessionUserId = "";
  deviceSessionId = "";
  sessionGeneration += 1;
  generationListeners.forEach((listener) => listener());
  accessExpiresAt = 0;
  refreshPromise = null;
  refreshFailures = 0;
  retryAfter = 0;
  refreshError = undefined;
  cancelRefreshTimer();
  clearAuthToken();
  if (broadcast && clearedSession && getApiAuthMode() === "multi_user")
    getSessionChannel().publish({ type: "cleared", sessionId: clearedSession });
}

export async function refreshAccessSession(
  rejectedToken?: string,
): Promise<boolean> {
  if (getApiAuthMode() !== "multi_user") return false;
  if (refreshPromise) return refreshPromise;
  if (Date.now() < retryAfter) throw refreshError;

  const generation = sessionGeneration;
  const previousToken = rejectedToken ?? getApiToken();
  getSessionChannel();
  const currentPromise = withSessionRefreshLock(async () => {
    if (generation !== sessionGeneration)
      throw new Error("Authentication context changed");
    // Another tab may have renewed while this tab waited for the origin lock.
    if (getApiToken() && getApiToken() !== previousToken) return null;
    return authApi.refresh();
  })
    .then((response) => {
      if (generation !== sessionGeneration) return false;
      if (response) adoptAccessSession(response);
      return true;
    })
    .catch((error: unknown) => {
      if (generation !== sessionGeneration || isAuthenticationRejected(error))
        return false;
      refreshError = error;
      const delay = Math.min(
        30_000,
        5_000 * 2 ** Math.min(refreshFailures++, 3),
      );
      retryAfter = Date.now() + delay;
      scheduleRefresh(delay);
      throw error;
    })
    .finally(() => {
      if (refreshPromise === currentPromise) refreshPromise = null;
    });
  refreshPromise = currentPromise;
  return currentPromise;
}

export function restoreAccessSession<T>(identify: () => Promise<T>) {
  getSessionChannel();
  const generation = sessionGeneration;
  return withSessionRefreshLock(async () => {
    if (generation !== sessionGeneration)
      throw new Error("Authentication context changed");
    const response = await authApi.refresh();
    if (generation !== sessionGeneration)
      throw new Error("Authentication context changed");
    adoptAccessSession(response);
    // Keep identity verification inside the same origin lock: another tab's
    // rotation must not invalidate this access token before /me completes.
    const identity = await identify();
    if (generation !== sessionGeneration)
      throw new Error("Authentication context changed");
    return { response, identity };
  });
}

export async function ensureAccessSessionFresh(): Promise<boolean> {
  if (getApiAuthMode() !== "multi_user") return true;
  if (accessExpiresAt === 0) return true;
  if (accessExpiresAt - Date.now() > REFRESH_MARGIN_MS) return true;
  return refreshAccessSession();
}
