import { afterEach, describe, expect, it, vi } from "vitest";
import {
  captureChunkDiagnostic,
  failedResourceUrl,
  readChunkDiagnostic,
  recheckChunkResource,
  saveChunkDiagnostic,
} from "./chunkDiagnostics";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
  sessionStorage.clear();
});

describe("original chunk diagnostics", () => {
  it("keeps original facts while redacting URL credentials and query secrets", () => {
    const error = new TypeError(
      "Failed to fetch dynamically imported module: https://user:secret@example.com/assets/page.js?token=secret&v=123#secret",
    );
    const diagnostic = captureChunkDiagnostic(error);
    expect(diagnostic.originalError.name).toBe("TypeError");
    expect(diagnostic.resourceUrl).toBe(
      "https://example.com/assets/page.js?v=123",
    );
    expect(JSON.stringify(diagnostic)).not.toContain("secret");
    expect(diagnostic.recheck).toBeNull();
    expect(diagnostic.automaticReloadAttempted).toBe(false);
  });

  it("retains unknown URL/status information rather than inventing a cause", () => {
    const diagnostic = captureChunkDiagnostic(
      new TypeError("Importing a module script failed."),
    );
    expect(diagnostic.resourceUrl).toBeNull();
    expect(diagnostic.originalResourceStatus).toBeNull();
    expect(diagnostic.attempts).toBeNull();
    expect(diagnostic.modulePath).toBeNull();
  });

  it("separates an original timing status from a successful later recheck", async () => {
    const url = `${location.origin}/assets/page.js`;
    vi.spyOn(performance, "getEntriesByName").mockReturnValue([
      { responseStatus: 503 } as unknown as PerformanceEntry,
    ]);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(null, { status: 200 })),
    );
    const report = captureChunkDiagnostic(
      new Error(`Failed to fetch dynamically imported module: ${url}`),
    );
    report.recheck = await recheckChunkResource(url);
    expect(report.originalResourceStatus).toBe(503);
    expect(report.recheck.status).toBe(200);
    expect(report.recheck.outcome).toBe("available");
  });

  it("extracts relative JS and CSS resource addresses", () => {
    expect(
      failedResourceUrl(
        new Error("Unable to preload CSS for /assets/page.css"),
      ),
    ).toBe(`${location.origin}/assets/page.css`);
    expect(
      failedResourceUrl(
        new Error("Loading chunk failed (error: /assets/page.js)"),
      ),
    ).toBe(`${location.origin}/assets/page.js`);
  });

  it("persists the latest diagnostic including the pre-refresh attempt", () => {
    const report = captureChunkDiagnostic(new Error("Loading chunk failed"));
    report.automaticReloadAttempted = true;
    saveChunkDiagnostic(report);
    expect(readChunkDiagnostic()).toEqual(report);
  });

  it("tolerates storage restrictions and malformed stored reports", () => {
    sessionStorage.setItem("qwenpaw:chunk-diagnostic", "not-json");
    expect(readChunkDiagnostic()).toBeNull();
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() =>
      saveChunkDiagnostic(
        captureChunkDiagnostic(new Error("Loading chunk failed")),
      ),
    ).not.toThrow();
  });
});

describe("bounded resource rechecks", () => {
  it.each([
    [404, "application/json", "missing"],
    [401, "application/json", "denied"],
    [403, "text/html", "denied"],
    [503, "text/html", "http-error"],
    [200, "text/html; charset=utf-8", "html"],
    [200, "text/javascript", "available"],
  ])(
    "reports observed status %s and content type %s",
    async (status, contentType, outcome) => {
      const fetcher = vi.fn().mockResolvedValue(
        new Response(null, {
          status: Number(status),
          headers: { "content-type": String(contentType) },
        }),
      );
      vi.stubGlobal("fetch", fetcher);
      const result = await recheckChunkResource(
        `${location.origin}/assets/page.js`,
      );
      expect(result).toMatchObject({ status, contentType, outcome });
      expect(fetcher).toHaveBeenCalledWith(
        `${location.origin}/assets/page.js`,
        expect.objectContaining({
          cache: "no-store",
          credentials: "omit",
          signal: expect.any(AbortSignal),
        }),
      );
    },
  );

  it("reports request failure without guessing DNS, TLS, CORS, or proxy causes", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    expect(
      await recheckChunkResource(`${location.origin}/assets/page.js`),
    ).toMatchObject({
      outcome: "request-failed",
      status: null,
      contentType: null,
    });
  });

  it("finishes within the deadline even when a request ignores abort", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn().mockImplementation(() => new Promise(() => {}));
    vi.stubGlobal("fetch", fetcher);
    const check = recheckChunkResource(`${location.origin}/assets/page.js`);
    await vi.advanceTimersByTimeAsync(2000);
    expect(await check).toMatchObject({ outcome: "timeout", status: null });
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
  });

  it("avoids rechecking unknown, foreign-origin, or offline resources", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    expect((await recheckChunkResource(null)).outcome).toBe("unavailable");
    expect(
      (await recheckChunkResource("https://example.com/page.js")).outcome,
    ).toBe("unavailable");
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    expect(
      (await recheckChunkResource(`${location.origin}/assets/page.js`)).outcome,
    ).toBe("unavailable");
    expect(fetcher).not.toHaveBeenCalled();
  });
});
