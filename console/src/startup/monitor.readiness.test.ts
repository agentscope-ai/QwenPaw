import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { installStartupMonitor } from "./monitor";
import {
  getFrontendBuildId,
  reloadAfterChunkError,
} from "../utils/chunkRecovery";
import { readChunkDiagnostic } from "../utils/chunkDiagnostics";
import en from "../locales/en.json";

vi.mock("../utils/chunkRecovery", async (original) => ({
  ...(await original<typeof import("../utils/chunkRecovery")>()),
  reloadAfterChunkError: vi.fn(() => true),
}));

const reloadKey = "qwenpaw:chunk-reload-build";
const originalUrl = location.href;
let stop: () => void;
let entry: HTMLScriptElement;
let guard: string;

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  vi.mocked(reloadAfterChunkError).mockImplementation((persist) => {
    persist?.({ reason: "reload", attempts: 2, maxAttempts: 2 });
    return true;
  });
  history.replaceState(null, "", "/console/chat");
  document.body.innerHTML =
    '<div id="root"><div class="qwenpaw-boot"><div class="qwenpaw-boot__content">Loading</div></div></div>';
  entry = document.createElement("script");
  entry.type = "module";
  entry.src = `${location.origin}/assets/old-entry.js`;
  document.head.append(entry);
  sessionStorage.clear();
  guard = JSON.stringify({ build: getFrontendBuildId(), attempts: 1 });
  sessionStorage.setItem(reloadKey, guard);
  stop = installStartupMonitor({ en: en.chunkError });
});

afterEach(() => {
  stop();
  entry.remove();
  document.body.innerHTML = "";
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  history.replaceState(null, "", originalUrl);
});

describe("startup recovery waits for local readiness", () => {
  it("waits for a stable server and a fresh entry instead of the missing old hash", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = new URL(String(input), location.href).pathname;
        if (path === "/api/version") return Response.json({ version: "2.2.2" });
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
            headers: { "content-type": "application/javascript" },
          });
        }
        return new Response(null, { status: 404 });
      }),
    );
    entry.dispatchEvent(new Event("error"));
    await vi.advanceTimersByTimeAsync(1999);
    expect(reloadAfterChunkError).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(reloadKey)).toBe(guard);
    await vi.advanceTimersByTimeAsync(1);
    expect(reloadAfterChunkError).toHaveBeenCalledOnce();
    expect(readChunkDiagnostic()).toMatchObject({
      frontendBuild: entry.src,
      recheck: { outcome: "missing", status: 404 },
      serverReadiness: { outcome: "ready", attempts: 3 },
    });
  });

  it("leaves startup failure actionable when readiness times out", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    entry.dispatchEvent(new Event("error"));
    await vi.advanceTimersByTimeAsync(30_000);
    expect(reloadAfterChunkError).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(reloadKey)).toBe(guard);
    expect(document.querySelectorAll("button")).toHaveLength(2);
    expect(readChunkDiagnostic()).toMatchObject({
      automaticReloadAttempted: false,
      serverReadiness: { outcome: "timeout", elapsedMs: 30_000 },
    });
  });

  it.each(["mount", "stop"])(
    "cancels readiness on %s and never reloads after a late response",
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
          return Promise.resolve(new Response(null, { status: 404 }));
        }),
      );
      entry.dispatchEvent(new Event("error"));
      await vi.advanceTimersByTimeAsync(0);
      const diagnostic = readChunkDiagnostic();
      if (action === "mount")
        document.getElementById("root")!.innerHTML = "<main>Loaded</main>";
      else stop();
      await vi.advanceTimersByTimeAsync(0);
      expect(pendingSignal.aborted).toBe(true);
      finish(Response.json({ version: "2.2.2" }));
      await vi.advanceTimersByTimeAsync(35_000);
      expect(reloadAfterChunkError).not.toHaveBeenCalled();
      expect(readChunkDiagnostic()).toEqual(diagnostic);
    },
  );

  it("does not grant another reload to an exhausted startup allowance", async () => {
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
      vi.fn(async (input: RequestInfo | URL) => {
        const path = new URL(String(input), location.href).pathname;
        if (path === "/api/version") return Response.json({ version: "2.2.2" });
        if (path === "/console/chat") {
          return new Response(
            '<script type="module" src="/assets/new-entry.js"></script>',
            {
              headers: { "content-type": "text/html" },
            },
          );
        }
        return new Response("export default 42;", {
          headers: { "content-type": "text/javascript" },
        });
      }),
    );
    entry.dispatchEvent(new Event("error"));
    await vi.advanceTimersByTimeAsync(2000);
    expect(readChunkDiagnostic()).toMatchObject({
      automaticReloadAttempted: false,
      automaticReload: { reason: "limit-reached", attempts: 2, maxAttempts: 2 },
      serverReadiness: { outcome: "ready" },
    });
    expect(sessionStorage.getItem(reloadKey)).toBe(guard);
  });
});
