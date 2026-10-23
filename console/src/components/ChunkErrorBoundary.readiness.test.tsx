import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChunkErrorBoundary } from "./ChunkErrorBoundary";
import {
  getFrontendBuildId,
  reloadAfterChunkError,
} from "../utils/chunkRecovery";
import { readChunkDiagnostic } from "../utils/chunkDiagnostics";
import { hubApi } from "../api/modules/hub";

vi.mock("../i18n", () => ({ default: { t: (key: string) => key } }));
vi.mock("../api/modules/hub", () => ({
  hubApi: { restartOwnRuntime: vi.fn() },
}));
vi.mock("../utils/chunkRecovery", async (original) => ({
  ...(await original<typeof import("../utils/chunkRecovery")>()),
  reloadAfterChunkError: vi.fn(() => true),
}));

const reloadKey = "qwenpaw:chunk-reload-build";
const originalUrl = location.href;
let guard: string;

function FailedPage(): ReactElement {
  throw new TypeError(
    `Failed to fetch dynamically imported module: ${location.origin}/assets/failed.js`,
  );
}

function serverResponse(input: RequestInfo | URL): Response {
  const path = new URL(String(input), location.href).pathname;
  if (path === "/api/version") {
    return Response.json({ version: "2.2.2" });
  }
  if (path === "/console/chat") {
    return new Response(
      '<script type="module" src="/assets/new-entry.js"></script>',
      {
        headers: { "content-type": "text/html" },
      },
    );
  }
  if (path === "/assets/new-entry.js") {
    return new Response("export default 42;", {
      headers: { "content-type": "text/javascript" },
    });
  }
  throw new TypeError("Failed to fetch");
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  vi.mocked(reloadAfterChunkError).mockImplementation((persist) => {
    persist?.({ reason: "reload", attempts: 2, maxAttempts: 2 });
    return true;
  });
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  history.replaceState(null, "", "/console/chat");
  sessionStorage.clear();
  guard = JSON.stringify({ build: getFrontendBuildId(), attempts: 1 });
  sessionStorage.setItem(reloadKey, guard);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  history.replaceState(null, "", originalUrl);
});

describe("page recovery waits for local readiness", () => {
  it("keeps loading until reload when the failed module rechecks successfully", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) =>
        String(input).endsWith("/assets/failed.js")
          ? new Response("export default 42;", {
              headers: { "content-type": "application/javascript" },
            })
          : serverResponse(input),
      ),
    );
    await act(async () => {
      render(
        <ChunkErrorBoundary>
          <FailedPage />
        </ChunkErrorBoundary>,
      );
    });
    expect(screen.getByText("common.loading")).toBeVisible();
    expect(screen.queryByText("chunkError.title")).not.toBeInTheDocument();
    expect(readChunkDiagnostic()).toMatchObject({
      recheck: { outcome: "available", status: 200 },
    });
    await act(() => vi.advanceTimersByTimeAsync(2000));
    expect(reloadAfterChunkError).toHaveBeenCalledOnce();
    expect(screen.getByText("common.loading")).toBeVisible();
    expect(screen.queryByText("chunkError.title")).not.toBeInTheDocument();
  });

  it("invalidates an unfinished resource recheck when a runtime restart fails", async () => {
    let finish!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise<Response>((resolve) => {
            finish = resolve;
          }),
      ),
    );
    vi.mocked(hubApi.restartOwnRuntime).mockRejectedValueOnce(
      new Error("restart failed"),
    );
    await act(async () => {
      render(
        <ChunkErrorBoundary canRestartRuntime>
          <FailedPage />
        </ChunkErrorBoundary>,
      );
    });
    const diagnostic = readChunkDiagnostic();
    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: "account.runtimeRestart" }),
      );
    });
    finish(new Response(null, { status: 404 }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(35_000);
    });
    expect(readChunkDiagnostic()).toEqual(diagnostic);
    expect(screen.getByText("restart failed")).toBeVisible();
    expect(
      screen.queryByText("chunkError.serverReadiness.checking"),
    ).not.toBeInTheDocument();
    expect(reloadAfterChunkError).not.toHaveBeenCalled();
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("keeps the allowance while refused connections recover, then reloads once", async () => {
    let probes = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        if (String(input).endsWith("/api/version") && probes++ < 2) {
          return Promise.reject(new TypeError("Failed to fetch"));
        }
        return Promise.resolve().then(() => serverResponse(input));
      }),
    );
    await act(async () => {
      render(
        <ChunkErrorBoundary>
          <FailedPage />
        </ChunkErrorBoundary>,
      );
    });
    expect(reloadAfterChunkError).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(reloadKey)).toBe(guard);
    expect(screen.getByText("common.loading")).toBeVisible();
    expect(screen.queryByText("chunkError.title")).not.toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3999);
    });
    expect(reloadAfterChunkError).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(reloadAfterChunkError).toHaveBeenCalledOnce();
    expect(screen.queryByText("chunkError.title")).not.toBeInTheDocument();
    expect(readChunkDiagnostic()).toMatchObject({
      recheck: { outcome: "request-failed" },
      serverReadiness: {
        outcome: "ready",
        attempts: 5,
        consecutiveSuccesses: 3,
      },
    });
  });

  it("retains manual recovery without consuming allowance when the server stays down", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    await act(async () => {
      render(
        <ChunkErrorBoundary>
          <FailedPage />
        </ChunkErrorBoundary>,
      );
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(reloadAfterChunkError).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(reloadKey)).toBe(guard);
    expect(screen.queryByText("common.loading")).not.toBeInTheDocument();
    expect(screen.getByText("chunkError.title")).toBeVisible();
    expect(
      screen.getByRole("button", { name: "chunkError.reload" }),
    ).toBeVisible();
    expect(readChunkDiagnostic()).toMatchObject({
      automaticReloadAttempted: false,
      serverReadiness: { outcome: "timeout", elapsedMs: 30_000 },
    });
  });

  it.each(["navigation", "unmount"])(
    "cancels a hanging probe on %s and ignores its late response",
    async (action) => {
      let finish!: (response: Response) => void;
      let pendingSignal!: AbortSignal;
      vi.stubGlobal(
        "fetch",
        vi.fn((input: RequestInfo | URL, options?: RequestInit) => {
          if (String(input).endsWith("/api/version")) {
            pendingSignal = options!.signal!;
            return new Promise<Response>((resolve) => {
              finish = resolve;
            });
          }
          return Promise.resolve().then(() => serverResponse(input));
        }),
      );
      let view!: ReturnType<typeof render>;
      await act(async () => {
        view = render(
          <ChunkErrorBoundary resetKey="failed">
            <FailedPage />
          </ChunkErrorBoundary>,
        );
      });
      const diagnostic = readChunkDiagnostic();
      await act(async () => {
        if (action === "unmount") view.unmount();
        else
          view.rerender(
            <ChunkErrorBoundary resetKey="healthy">
              <div>healthy page</div>
            </ChunkErrorBoundary>,
          );
      });
      expect(pendingSignal.aborted).toBe(true);
      finish(Response.json({ version: "2.2.2" }));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(35_000);
      });
      expect(reloadAfterChunkError).not.toHaveBeenCalled();
      expect(readChunkDiagnostic()).toEqual(diagnostic);
      if (action === "navigation")
        expect(screen.getByText("healthy page")).toBeVisible();
    },
  );

  it("keeps an exhausted allowance after readiness succeeds", async () => {
    const actual = await vi.importActual<
      typeof import("../utils/chunkRecovery")
    >("../utils/chunkRecovery");
    vi.mocked(reloadAfterChunkError).mockImplementation(
      actual.reloadAfterChunkError,
    );
    guard = JSON.stringify({ build: getFrontendBuildId(), attempts: 2 });
    sessionStorage.setItem(reloadKey, guard);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => serverResponse(input)),
    );
    await act(async () => {
      render(
        <ChunkErrorBoundary>
          <FailedPage />
        </ChunkErrorBoundary>,
      );
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(readChunkDiagnostic()).toMatchObject({
      automaticReloadAttempted: false,
      automaticReload: { reason: "limit-reached", attempts: 2, maxAttempts: 2 },
      serverReadiness: { outcome: "ready" },
    });
    expect(sessionStorage.getItem(reloadKey)).toBe(guard);
    expect(screen.queryByText("common.loading")).not.toBeInTheDocument();
    expect(screen.getByText("chunkError.title")).toBeVisible();
  });
});
