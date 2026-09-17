import { clearAuthToken, getApiAuthMode, setAuthToken } from "./config";
import { authApi, type LoginResponse } from "./modules/auth";

const REFRESH_MARGIN_MS = 60_000;

let accessExpiresAt = 0;
let refreshPromise: Promise<boolean> | null = null;
let refreshTimer: ReturnType<typeof setTimeout> | null = null;
let sessionGeneration = 0;
const generationListeners = new Set<() => void>();

export const getAccessSessionGeneration = () => sessionGeneration;
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

function scheduleRefresh(): void {
  cancelRefreshTimer();
  if (getApiAuthMode() !== "multi_user" || accessExpiresAt === 0) return;
  const delay = Math.max(0, accessExpiresAt - Date.now() - REFRESH_MARGIN_MS);
  refreshTimer = setTimeout(() => {
    void refreshAccessSession();
  }, delay);
}

export function adoptAccessSession(response: LoginResponse): void {
  setAuthToken(response.token);
  accessExpiresAt = parseExpiresAt(response.access_expires_at);
  scheduleRefresh();
}

export function clearAccessSession(): void {
  sessionGeneration += 1;
  generationListeners.forEach((listener) => listener());
  accessExpiresAt = 0;
  refreshPromise = null;
  cancelRefreshTimer();
  clearAuthToken();
}

export async function refreshAccessSession(): Promise<boolean> {
  if (getApiAuthMode() !== "multi_user") return false;
  if (refreshPromise) return refreshPromise;

  const generation = sessionGeneration;
  const currentPromise = authApi
    .refresh()
    .then((response) => {
      if (generation !== sessionGeneration) return false;
      adoptAccessSession(response);
      return true;
    })
    .catch(() => false)
    .finally(() => {
      if (refreshPromise === currentPromise) refreshPromise = null;
    });
  refreshPromise = currentPromise;
  return currentPromise;
}

export async function ensureAccessSessionFresh(): Promise<boolean> {
  if (getApiAuthMode() !== "multi_user") return true;
  if (accessExpiresAt === 0) return true;
  if (accessExpiresAt - Date.now() > REFRESH_MARGIN_MS) return true;
  return refreshAccessSession();
}
