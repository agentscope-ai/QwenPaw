import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { waitForChunkServerReady } from "./chunkServerReadiness";

const originalUrl = location.href;
const reloadKey = "qwenpaw:chunk-reload-build";
let caller: AbortController;

function serverResponse(input: RequestInfo | URL): Response {
  const path = new URL(String(input)).pathname;
  if (path === "/api/version") {
    return Response.json({
      version: "2.2.2",
      privateData: "must-not-be-recorded",
    });
  }
  if (path === "/console/chat") {
    return new Response(
      '<script type="module" src="/assets/current.js"></script>',
      {
        headers: { "content-type": "text/html; charset=utf-8" },
      },
    );
  }
  if (path === "/assets/current.js") {
    return new Response("export default 42;", {
      headers: { "content-type": "application/javascript; charset=utf-8" },
    });
  }
  return new Response(null, { status: 404 });
}

beforeEach(() => {
  vi.useFakeTimers();
  history.replaceState(null, "", "/console/chat?token=secret#secret");
  caller = new AbortController();
  sessionStorage.clear();
  sessionStorage.setItem(reloadKey, "unchanged allowance");
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => serverResponse(input)),
  );
});

afterEach(() => {
  caller.abort();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  history.replaceState(null, "", originalUrl);
});

describe("local server readiness", () => {
  it("requires three spaced successful rounds and keeps probe facts privacy safe", async () => {
    let complete = false;
    const check = waitForChunkServerReady(null, caller.signal).then(
      (report) => {
        complete = true;
        return report;
      },
    );
    await vi.advanceTimersByTimeAsync(1999);
    expect(complete).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(await check).toEqual({
      outcome: "ready",
      attempts: 3,
      consecutiveSuccesses: 3,
      elapsedMs: 2000,
      lastStatus: 200,
    });
    expect(sessionStorage.getItem(reloadKey)).toBe("unchanged allowance");
    for (const [input, options] of vi.mocked(fetch).mock.calls) {
      expect(String(input)).not.toContain("secret");
      expect(options).toMatchObject({
        cache: "no-store",
        credentials: "omit",
        redirect: "error",
      });
    }
    expect(JSON.stringify(await check)).not.toContain("must-not-be-recorded");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("starts a new streak after an intermittent connection refusal", async () => {
    let versionRequests = 0;
    vi.mocked(fetch).mockImplementation(async (input) => {
      if (String(input).endsWith("/api/version") && ++versionRequests === 2) {
        throw new TypeError("Failed to fetch");
      }
      return serverResponse(input);
    });
    const check = waitForChunkServerReady(null, caller.signal);
    await vi.advanceTimersByTimeAsync(3999);
    expect(versionRequests).toBe(4);
    await vi.advanceTimersByTimeAsync(1);
    expect(await check).toMatchObject({
      outcome: "ready",
      attempts: 5,
      elapsedMs: 4000,
    });
  });

  it.each([
    [200, "text/html", '{"version":"2.2.2"}'],
    [200, "application/json", '{"status":"ok"}'],
    [200, "application/json", '{"version":" "}'],
    [200, "application/json", "invalid JSON"],
    [401, "application/json", '{"version":"2.2.2"}'],
    [503, "application/json", '{"version":"2.2.2"}'],
  ])(
    "does not accept a version response with status %s, type %s, and body %s",
    async (status, contentType, body) => {
      vi.mocked(fetch).mockImplementation(
        async () =>
          new Response(String(body), {
            status: Number(status),
            headers: { "content-type": String(contentType) },
          }),
      );
      const check = waitForChunkServerReady(null, caller.signal);
      await vi.advanceTimersByTimeAsync(30_000);
      expect(await check).toMatchObject({
        outcome: "timeout",
        consecutiveSuccesses: 0,
        elapsedMs: 30_000,
      });
      expect(
        vi
          .mocked(fetch)
          .mock.calls.every(([url]) => String(url).endsWith("/api/version")),
      ).toBe(true);
      expect(sessionStorage.getItem(reloadKey)).toBe("unchanged allowance");
      expect(vi.getTimerCount()).toBe(0);
    },
  );

  it.each([
    ["text/html", "<html>not JavaScript</html>"],
    ["application/octet-stream", "export default 42;"],
    ["text/javascript", ""],
  ])(
    "rejects an entry with content type %s and body %s",
    async (contentType, body) => {
      vi.mocked(fetch).mockImplementation(async (input) => {
        if (String(input).endsWith("/assets/current.js")) {
          return new Response(body, {
            headers: { "content-type": contentType },
          });
        }
        return serverResponse(input);
      });
      const check = waitForChunkServerReady(null, caller.signal);
      await vi.advanceTimersByTimeAsync(30_000);
      expect(await check).toMatchObject({
        outcome: "timeout",
        consecutiveSuccesses: 0,
      });
    },
  );

  it.each([
    "https://other.example/entry.js",
    "data:text/javascript,export default 42;",
    "http://user:secret@localhost:3000/entry.js",
  ])("does not request an unsafe entry: %s", async (entry) => {
    vi.mocked(fetch).mockImplementation(async (input) => {
      if (String(input).endsWith("/console/chat")) {
        return new Response(`<script type="module" src="${entry}"></script>`, {
          headers: { "content-type": "text/html" },
        });
      }
      return serverResponse(input);
    });
    const check = waitForChunkServerReady(null, caller.signal);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(await check).toMatchObject({ outcome: "timeout" });
    expect(
      vi.mocked(fetch).mock.calls.every(([url]) => {
        const path = new URL(String(url)).pathname;
        return path === "/api/version" || path === "/console/chat";
      }),
    ).toBe(true);
  });

  it("resolves relative entries against the fresh HTML base and skips the HMR client", async () => {
    vi.mocked(fetch).mockImplementation(async (input) => {
      if (String(input).endsWith("/console/chat")) {
        return new Response(
          '<base href="/assets/"><script type="module" src="/@vite/client"></script><script type="module" src="current.js"></script>',
          {
            headers: { "content-type": "text/html" },
          },
        );
      }
      return serverResponse(input);
    });
    const check = waitForChunkServerReady(null, caller.signal);
    await vi.advanceTimersByTimeAsync(2000);
    expect(await check).toMatchObject({ outcome: "ready" });
    expect(
      vi
        .mocked(fetch)
        .mock.calls.some(([url]) => String(url).endsWith("/@vite/client")),
    ).toBe(false);
  });

  it("bounds requests that ignore abort and ignores responses arriving after timeout", async () => {
    let finish!: (response: Response) => void;
    vi.mocked(fetch).mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve;
        }),
    );
    const check = waitForChunkServerReady(null, caller.signal);
    await vi.advanceTimersByTimeAsync(2500);
    expect(vi.mocked(fetch).mock.calls[0][1]?.signal?.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(27_500);
    const report = await check;
    expect(report).toMatchObject({
      outcome: "timeout",
      elapsedMs: 30_000,
      lastStatus: null,
    });
    const requests = vi.mocked(fetch).mock.calls.length;
    finish(Response.json({ version: "2.2.2" }));
    await vi.advanceTimersByTimeAsync(5000);
    expect(report).toMatchObject({ outcome: "timeout", lastStatus: null });
    expect(fetch).toHaveBeenCalledTimes(requests);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("waits for complete entry bodies and bounds stalled downloads despite 200 headers", async () => {
    let finish!: (body: string) => void;
    const body = new Promise<string>((resolve) => {
      finish = resolve;
    });
    vi.mocked(fetch).mockImplementation(async (input) => {
      const response = serverResponse(input);
      if (String(input).endsWith("/assets/current.js")) {
        vi.spyOn(response, "text").mockReturnValue(body);
      }
      return response;
    });
    const check = waitForChunkServerReady(null, caller.signal);
    await vi.advanceTimersByTimeAsync(30_000);
    const report = await check;
    expect(report).toMatchObject({
      outcome: "timeout",
      consecutiveSuccesses: 0,
      lastStatus: 200,
    });
    finish("export default 42;");
    await vi.advanceTimersByTimeAsync(0);
    expect(report).toMatchObject({
      outcome: "timeout",
      consecutiveSuccesses: 0,
    });
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each(["request", "interval"])(
    "cancels a pending %s without leaving timers or probes",
    async (phase) => {
      if (phase === "request") {
        vi.mocked(fetch).mockImplementation(
          () => new Promise<Response>(() => {}),
        );
      }
      const check = waitForChunkServerReady(null, caller.signal);
      await vi.advanceTimersByTimeAsync(0);
      const requests = vi.mocked(fetch).mock.calls.length;
      caller.abort();
      expect(await check).toMatchObject({ outcome: "cancelled" });
      await vi.advanceTimersByTimeAsync(35_000);
      expect(fetch).toHaveBeenCalledTimes(requests);
      expect(vi.getTimerCount()).toBe(0);
    },
  );

  it("makes no request for an already cancelled recovery", async () => {
    caller.abort();
    expect(await waitForChunkServerReady(null, caller.signal)).toMatchObject({
      outcome: "cancelled",
      attempts: 0,
    });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("leaves foreign-origin chunk recovery to the existing reload policy", async () => {
    expect(
      await waitForChunkServerReady(
        "https://other.example/page.js",
        caller.signal,
      ),
    ).toMatchObject({ outcome: "not-applicable", attempts: 0 });
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each(["http://127.0.0.1:8088", "http://[::1]:8088"])(
    "supports the loopback origin %s without assuming a port",
    async (origin) => {
      vi.stubGlobal("window", {
        location: new URL(`${origin}/console/chat`),
        setTimeout,
        clearTimeout,
      });
      const check = waitForChunkServerReady(null, caller.signal);
      await vi.advanceTimersByTimeAsync(2000);
      expect(await check).toMatchObject({ outcome: "ready" });
      expect(
        vi
          .mocked(fetch)
          .mock.calls.every(([url]) => new URL(String(url)).origin === origin),
      ).toBe(true);
    },
  );

  it("preserves recovery for deployments that do not use the local backend", async () => {
    vi.stubGlobal("window", {
      location: new URL("https://console.example/chat"),
    });
    expect(await waitForChunkServerReady(null, caller.signal)).toMatchObject({
      outcome: "not-applicable",
    });
    expect(fetch).not.toHaveBeenCalled();
  });
});
