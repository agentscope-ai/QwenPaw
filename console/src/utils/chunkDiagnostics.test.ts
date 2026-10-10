import { afterEach, describe, expect, it, vi } from "vitest";
import {
  captureChunkDiagnostic,
  failedResourceUrl,
  readBeforeAutomaticReloadDiagnostic,
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

  it.each([
    "token=[secret-value]",
    "token=(secret-value)",
    "token=%5Bsecret-value%5D",
    "token=%28secret-value%29",
    "token=outer(secret-value(inner))",
    "filters[]=[secret-value]&v=123",
  ])("redacts complete query values in %s", (query) => {
    const url = `https://example.com/assets/page.js?${query}`;
    const error = new TypeError(
      `Failed to fetch dynamically imported module: ${url}`,
    );
    error.stack = `TypeError: ${error.message}\n    at load (${url}:12:34)`;
    const report = captureChunkDiagnostic(error);
    expect(failedResourceUrl(error)).toBe(url);
    expect(report.originalError.message).not.toContain("secret-value");
    expect(report.originalError.stack).not.toContain("secret-value");
    expect(report.originalError.stack).toMatch(/\)$/);
    expect(report.resourceUrl).toBe(
      `https://example.com/assets/page.js${
        query.includes("v=123") ? "?v=123" : ""
      }`,
    );
    saveChunkDiagnostic(report);
    expect(JSON.stringify(readChunkDiagnostic())).not.toContain("secret-value");
  });

  it("distinguishes URL brackets from surrounding error syntax", () => {
    const url = "http://[::1]/assets/page(test).js?token=[secret-value]";
    const error = new Error(`Loading chunk failed (error: ${url}).`);
    expect(failedResourceUrl(error)).toBe(url);
    const report = captureChunkDiagnostic(error);
    expect(report.resourceUrl).toBe("http://[::1]/assets/page(test).js");
    expect(report.originalError.message).toBe(
      "Loading chunk failed (error: http://[::1]/assets/page(test).js).",
    );
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

  it("retains legacy pre-refresh reports when saving later failures", () => {
    const previous = captureChunkDiagnostic(new Error("Initial failure"));
    previous.automaticReloadAttempted = true;
    sessionStorage.setItem(
      "qwenpaw:chunk-diagnostic",
      JSON.stringify(previous),
    );
    expect(readBeforeAutomaticReloadDiagnostic(previous.page)).toEqual(
      previous,
    );
    const current = captureChunkDiagnostic(new Error("Failure after refresh"));
    saveChunkDiagnostic(current);
    saveChunkDiagnostic(current);
    expect(readChunkDiagnostic()).toEqual(current);
    expect(readBeforeAutomaticReloadDiagnostic(current.page)).toEqual(previous);
    expect(
      readBeforeAutomaticReloadDiagnostic(`${current.page}other`),
    ).toBeNull();
  });

  it("replaces the preserved report when a newer automatic refresh occurs", () => {
    const previous = captureChunkDiagnostic(new Error("Old build failure"));
    previous.automaticReloadAttempted = true;
    saveChunkDiagnostic(previous);
    const current = captureChunkDiagnostic(new Error("New build failure"));
    current.automaticReloadAttempted = true;
    saveChunkDiagnostic(current);
    expect(readBeforeAutomaticReloadDiagnostic(current.page)).toEqual(current);
  });

  it("still saves the latest report if preserving the earlier report fails", () => {
    const previous = captureChunkDiagnostic(new Error("Initial failure"));
    previous.automaticReloadAttempted = true;
    sessionStorage.setItem(
      "qwenpaw:chunk-diagnostic",
      JSON.stringify(previous),
    );
    const setItem = Storage.prototype.setItem;
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (
      this: Storage,
      key: string,
      value: string,
    ) {
      if (key === "qwenpaw:chunk-diagnostic-before-reload") {
        throw new DOMException("Storage full", "QuotaExceededError");
      }
      setItem.call(this, key, value);
    });
    const current = captureChunkDiagnostic(new Error("Later failure"));
    saveChunkDiagnostic(current);
    expect(readChunkDiagnostic()).toEqual(current);
  });

  it("tolerates storage restrictions and malformed stored reports", () => {
    sessionStorage.setItem("qwenpaw:chunk-diagnostic", "not-json");
    sessionStorage.setItem(
      "qwenpaw:chunk-diagnostic-before-reload",
      "not-json",
    );
    expect(readChunkDiagnostic()).toBeNull();
    expect(readBeforeAutomaticReloadDiagnostic(location.href)).toBeNull();
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
  it("waits for the entire body before reporting a resource as available", async () => {
    const content = "export default 42;";
    let finish!: (body: ArrayBuffer) => void;
    const body = new Promise<ArrayBuffer>((resolve) => {
      finish = resolve;
    });
    const response = new Response(content, {
      headers: { "content-type": "application/javascript" },
    });
    vi.spyOn(response, "arrayBuffer").mockReturnValue(body);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    let completed = false;
    const check = recheckChunkResource(
      `${location.origin}/assets/page.js`,
    ).then((report) => {
      completed = true;
      return report;
    });
    await Promise.resolve();
    await Promise.resolve();
    expect(completed).toBe(false);
    finish(new TextEncoder().encode(content).buffer);
    expect(await check).toMatchObject({
      outcome: "available",
      status: 200,
      bodyBytes: content.length,
    });
  });

  it("reports a truncated body as failed even after receiving a 200 response", async () => {
    const response = new Response(null, {
      headers: { "content-type": "application/javascript" },
    });
    vi.spyOn(response, "arrayBuffer").mockRejectedValue(
      new TypeError("Response body terminated"),
    );
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    expect(
      await recheckChunkResource(`${location.origin}/assets/page.js`),
    ).toMatchObject({
      outcome: "request-failed",
      status: 200,
      contentType: "application/javascript",
      bodyBytes: null,
    });
  });

  it("bounds body download and retains its timeout when the body finishes late", async () => {
    vi.useFakeTimers();
    let finish!: (body: ArrayBuffer) => void;
    const response = new Response(null, {
      headers: { "content-type": "application/javascript" },
    });
    vi.spyOn(response, "arrayBuffer").mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    const check = recheckChunkResource(`${location.origin}/assets/page.js`);
    await vi.advanceTimersByTimeAsync(2000);
    const report = await check;
    expect(report).toMatchObject({
      outcome: "timeout",
      status: 200,
      bodyBytes: null,
    });
    finish(new ArrayBuffer(42));
    await vi.advanceTimersByTimeAsync(0);
    expect(report).toMatchObject({ outcome: "timeout", bodyBytes: null });
  });

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
