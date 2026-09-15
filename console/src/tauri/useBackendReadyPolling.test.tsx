import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import useBackendReadyPolling from "./useBackendReadyPolling";

vi.mock("./backendRuntime", () => ({
  backendConsoleUrl: (origin: string) => `${origin}/console`,
  getBackendStartupError: vi.fn(async () => ""),
  initRuntimeApiBaseUrl: vi.fn(async () => "http://127.0.0.1:8765"),
  restartBackend: vi.fn(),
  shouldUseTauriStartupGate: () => true,
}));

afterEach(() => vi.unstubAllGlobals());

it("probes the public console before leaving the Desktop bootstrap origin", async () => {
  const fetch = vi.fn(async () => new Response("console"));
  vi.stubGlobal("fetch", fetch);
  const { result, unmount } = renderHook(() => useBackendReadyPolling());
  await waitFor(() => expect(result.current.status).toBe("ready"));
  expect(fetch).toHaveBeenCalledWith(
    "http://127.0.0.1:8765/console",
    expect.objectContaining({ cache: "no-store" }),
  );
  expect(result.current.readyUrl).toBe("http://127.0.0.1:8765/console");
  unmount();
});
