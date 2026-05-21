import { describe, it, expect, beforeEach, vi } from "vitest";

const tauriMocks = vi.hoisted(() => ({
  invoke: vi.fn(),
  isTauri: vi.fn(() => false),
}));

vi.mock("@tauri-apps/api/core", () => ({
  invoke: tauriMocks.invoke,
  isTauri: tauriMocks.isTauri,
}));

import { restartBackend } from "./backendRuntime";

const setViteBase = (v: string) => {
  (globalThis as any).VITE_API_BASE_URL = v;
  (globalThis as any).__QWENPAW_CONFIGURED_API_BASE_URL__ = v;
};
const clearRuntimeApiBaseUrl = () => {
  delete (globalThis as any).__QWENPAW_API_BASE_URL__;
};

describe("restartBackend", () => {
  beforeEach(() => {
    setViteBase("");
    clearRuntimeApiBaseUrl();
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
