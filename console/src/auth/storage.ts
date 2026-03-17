import type { AuthState } from "./types";

declare const TOKEN: string;

const AUTH_STORAGE_KEY = "boostclaw.console.auth";

function getEnvToken(): string {
  return TOKEN;
}

export function loadAuthState(): AuthState {
  if (typeof window === "undefined") {
    return { token: getEnvToken(), user: null };
  }

  try {
    const raw = window.localStorage.getItem(AUTH_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<AuthState>;
      if (typeof parsed.token === "string") {
        return {
          token: parsed.token,
          user: parsed.user ?? null,
        };
      }
    }
  } catch {
    // Ignore malformed storage and fallback to env token.
  }

  return { token: getEnvToken(), user: null };
}

export function saveAuthState(state: AuthState): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(state));
}

export function clearAuthState(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(AUTH_STORAGE_KEY);
}

export function getStoredAuthToken(): string {
  if (typeof window === "undefined") return "";

  try {
    const raw = window.localStorage.getItem(AUTH_STORAGE_KEY);
    if (!raw) return "";
    const parsed = JSON.parse(raw) as Partial<AuthState>;
    return typeof parsed.token === "string" ? parsed.token : "";
  } catch {
    return "";
  }
}



