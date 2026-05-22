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
  backendConsoleUrl,
  restartBackend,
  shouldUseTauriStartupGate,
} from "./backendRuntime";

const setViteBase = (v: string) => {
  (globalThis as any).VITE_API_BASE_URL = v;
};

describe("backendRuntime", () => {
  beforeEach(() => {
    setViteBase("");
    tauriMocks.invoke.mockReset();
    tauriMocks.isTauri.mockReturnValue(false);
    window.history.replaceState(null, "", "/");
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

  it("builds the backend-hosted console URL", () => {
    expect(backendConsoleUrl("http://127.0.0.1:8090/")).toBe(
      "http://127.0.0.1:8090/console",
    );
  });

  it("uses the startup gate for the initial Tauri page", () => {
    tauriMocks.isTauri.mockReturnValue(true);
    window.history.replaceState(null, "", "/");

    expect(shouldUseTauriStartupGate()).toBe(true);
  });

  it("does not gate after Tauri has navigated to the backend console", () => {
    tauriMocks.isTauri.mockReturnValue(true);
    window.history.replaceState(null, "", "/console");

    expect(shouldUseTauriStartupGate()).toBe(false);
  });
});
