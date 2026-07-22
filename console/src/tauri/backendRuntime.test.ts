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
  initRuntimeApiBaseUrl,
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

  it("returns without invoking sidecar restart when base URL is configured", async () => {
    setViteBase("http://localhost:9000");
    tauriMocks.isTauri.mockReturnValue(true);

    await expect(restartBackend()).resolves.toBeUndefined();

    expect(tauriMocks.invoke).not.toHaveBeenCalled();
  });

  it("invokes sidecar restart when no base URL is configured", async () => {
    tauriMocks.isTauri.mockReturnValue(true);
    tauriMocks.invoke.mockResolvedValue(undefined);

    await expect(restartBackend()).resolves.toBeUndefined();

    expect(tauriMocks.invoke).toHaveBeenCalledWith("restart_backend");
  });

  it("returns an empty runtime base URL until the sidecar reports its port", async () => {
    tauriMocks.isTauri.mockReturnValue(true);
    tauriMocks.invoke.mockResolvedValue(null);

    await expect(initRuntimeApiBaseUrl()).resolves.toBe("");

    expect(tauriMocks.invoke).toHaveBeenCalledWith("backend_port");
  });

  it("builds the runtime base URL after the sidecar reports its port", async () => {
    tauriMocks.isTauri.mockReturnValue(true);
    tauriMocks.invoke.mockResolvedValue(8090);

    await expect(initRuntimeApiBaseUrl()).resolves.toBe(
      "http://127.0.0.1:8090",
    );

    expect(tauriMocks.invoke).toHaveBeenCalledWith("backend_port");
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
