import { describe, it, expect, beforeEach, vi } from "vitest";

const tauriMocks = vi.hoisted(() => ({
  invoke: vi.fn(),
  isTauri: vi.fn(() => false),
}));

vi.mock("@tauri-apps/api/core", () => ({
  invoke: tauriMocks.invoke,
  isTauri: tauriMocks.isTauri,
}));

import {
  AUTH_TOKEN_KEY,
  clearAuthToken,
  getApiToken,
  getApiUrl,
  restartBackend,
  setAuthToken,
} from "./config";

// VITE_API_BASE_URL / TOKEN are declared globals in config.ts — set via globalThis
const setViteBase = (v: string) => {
  (globalThis as any).VITE_API_BASE_URL = v;
};
const setToken = (v: string) => {
  (globalThis as any).TOKEN = v;
};

describe("getApiUrl", () => {
  beforeEach(() => {
    setViteBase("");
    tauriMocks.invoke.mockReset();
    tauriMocks.isTauri.mockReturnValue(false);
  });

  it("prepends /api prefix when base is empty", () => {
    expect(getApiUrl("/models")).toBe("/api/models");
  });

  it("auto-prepends / when path does not start with /", () => {
    expect(getApiUrl("models")).toBe("/api/models");
  });

  it("correctly concatenates when base URL is set", () => {
    setViteBase("http://localhost:8088");
    expect(getApiUrl("/models")).toBe("http://localhost:8088/api/models");
  });

  it("correctly handles nested paths", () => {
    expect(getApiUrl("/models/openai/config")).toBe(
      "/api/models/openai/config",
    );
  });
});

describe("getApiToken", () => {
  beforeEach(() => {
    localStorage.clear();
    setToken("");
  });

  it("returns token from localStorage when present", () => {
    localStorage.setItem(AUTH_TOKEN_KEY, "stored-token");
    expect(getApiToken()).toBe("stored-token");
  });

  it("falls back to TOKEN global variable when localStorage has no token", () => {
    setToken("build-time-token");
    expect(getApiToken()).toBe("build-time-token");
  });

  it("returns empty string when neither is set", () => {
    expect(getApiToken()).toBe("");
  });
});

describe("setAuthToken / clearAuthToken", () => {
  beforeEach(() => localStorage.clear());

  it("setAuthToken writes to localStorage", () => {
    setAuthToken("my-token");
    expect(localStorage.getItem(AUTH_TOKEN_KEY)).toBe("my-token");
  });

  it("clearAuthToken removes token from localStorage", () => {
    localStorage.setItem(AUTH_TOKEN_KEY, "my-token");
    clearAuthToken();
    expect(localStorage.getItem(AUTH_TOKEN_KEY)).toBeNull();
  });

  it("getApiToken returns empty string after clearAuthToken", () => {
    setToken("");
    setAuthToken("my-token");
    clearAuthToken();
    expect(getApiToken()).toBe("");
  });
});

describe("restartBackend", () => {
  beforeEach(() => {
    setViteBase("");
    tauriMocks.invoke.mockReset();
    tauriMocks.isTauri.mockReturnValue(false);
  });

  it("returns configured base URL in Tauri without invoking sidecar restart", async () => {
    setViteBase("http://localhost:9000");
    tauriMocks.isTauri.mockReturnValue(true);

    await expect(restartBackend()).resolves.toBe("http://localhost:9000");

    expect(tauriMocks.invoke).not.toHaveBeenCalled();
  });

  it("invokes sidecar restart when no base URL is configured", async () => {
    tauriMocks.isTauri.mockReturnValue(true);
    tauriMocks.invoke.mockResolvedValue(8090);

    await expect(restartBackend()).resolves.toBe("http://127.0.0.1:8090");

    expect(tauriMocks.invoke).toHaveBeenCalledWith("restart_backend");
  });
});
