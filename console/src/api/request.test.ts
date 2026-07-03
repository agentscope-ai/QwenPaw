import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { request } from "./request";

// mock config so URL is predictable and token is empty by default
vi.mock("./config", () => ({
  getApiUrl: (path: string) => `/api${path}`,
  getApiToken: vi.fn(() => ""),
  clearAuthToken: vi.fn(),
}));

vi.mock("./authHeaders", () => ({
  buildAuthHeaders: vi.fn(() => ({})),
}));

import { clearAuthToken } from "./config";
import { buildAuthHeaders } from "./authHeaders";

// Helper: create a mock Response
function mockFetch(
  status: number,
  body?: unknown,
  contentType = "application/json",
) {
  const responseBody =
    body !== undefined
      ? typeof body === "string"
        ? body
        : JSON.stringify(body)
      : "";

  global.fetch = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText:
      status === 200 ? "OK" : status === 401 ? "Unauthorized" : "Error",
    headers: { get: () => contentType },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(responseBody),
  } as unknown as Response);
}

describe("request", () => {
  beforeEach(() => {
    vi.mocked(buildAuthHeaders).mockReturnValue({});
    Object.defineProperty(window, "location", {
      value: { pathname: "/chat", href: "" },
      writable: true,
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  // ---------------------------------------------------------------------------
  // Successful requests
  // ---------------------------------------------------------------------------

  it("GET request does not set Content-Type", async () => {
    mockFetch(200, { data: "ok" });
    await request("/models");
    const headers: Headers = (fetch as any).mock.calls[0][1].headers;
    expect(headers.has("Content-Type")).toBe(false);
  });

  it("POST request automatically adds Content-Type: application/json", async () => {
    mockFetch(200, { data: "ok" });
    await request("/models", { method: "POST", body: "{}" });
    const headers: Headers = (fetch as any).mock.calls[0][1].headers;
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("PUT request automatically adds Content-Type", async () => {
    mockFetch(200, { status: "ok" });
    await request("/models/active", { method: "PUT", body: "{}" });
    const headers: Headers = (fetch as any).mock.calls[0][1].headers;
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("caller-specified Content-Type is not overridden", async () => {
    mockFetch(200, { status: "ok" });
    await request("/upload", {
      method: "POST",
      headers: { "Content-Type": "multipart/form-data" },
    });
    const headers: Headers = (fetch as any).mock.calls[0][1].headers;
    expect(headers.get("Content-Type")).toBe("multipart/form-data");
  });

  it("correctly parses and returns JSON response", async () => {
    mockFetch(200, { id: 1, name: "test" });
    const result = await request<{ id: number; name: string }>("/models");
    expect(result).toEqual({ id: 1, name: "test" });
  });

  it("returns text for non-JSON Content-Type", async () => {
    mockFetch(200, "plain text response", "text/plain");
    const result = await request("/health");
    expect(result).toBe("plain text response");
  });

  it("204 response returns undefined", async () => {
    mockFetch(204, undefined, "");
    const result = await request("/models/active");
    expect(result).toBeUndefined();
  });

  // ---------------------------------------------------------------------------
  // Error handling
  // ---------------------------------------------------------------------------

  it("calls clearAuthToken and redirects to /login on 401", async () => {
    mockFetch(401);
    await expect(request("/models")).rejects.toThrow("Not authenticated");
    expect(clearAuthToken).toHaveBeenCalledOnce();
    expect(window.location.href).toBe("/login");
  });

  it("does not redirect again when already on /login for 401", async () => {
    window.location.pathname = "/login";
    window.location.href = "";
    mockFetch(401);
    await expect(request("/models")).rejects.toThrow("Not authenticated");
    expect(window.location.href).toBe("");
  });

  it("throws error with status code for non-401 errors", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      headers: { get: () => "application/json" },
      text: () => Promise.resolve("server exploded"),
    } as unknown as Response);

    await expect(request("/models")).rejects.toThrow("server exploded");
  });

  it("injects Authorization header when token is present", async () => {
    vi.mocked(buildAuthHeaders).mockReturnValue({
      Authorization: "Bearer test-token",
    });
    mockFetch(200, {});
    await request("/models");
    const headers: Headers = (fetch as any).mock.calls[0][1].headers;
    expect(headers.get("Authorization")).toBe("Bearer test-token");
  });

  it("request URL is correctly built by getApiUrl", async () => {
    mockFetch(200, {});
    await request("/models/active");
    expect(fetch).toHaveBeenCalledWith(
      "/api/models/active",
      expect.any(Object),
    );
  });

  // ---------------------------------------------------------------------------
  // Timeout handling
  // ---------------------------------------------------------------------------

  it("aborts request after default timeout (30s)", async () => {
    vi.useFakeTimers();
    const abortSpy = vi.spyOn(AbortController.prototype, "abort");

    global.fetch = vi.fn().mockImplementation((_url, options) => {
      return new Promise((_resolve, reject) => {
        // Listen for abort signal
        if (options?.signal) {
          options.signal.addEventListener("abort", () => {
            reject(new DOMException("The operation was aborted", "AbortError"));
          });
        }
      });
    });

    const requestPromise = request("/slow-endpoint");
    vi.advanceTimersByTime(30000);

    await expect(requestPromise).rejects.toThrow("Request timeout");
    expect(abortSpy).toHaveBeenCalled();

    abortSpy.mockRestore();
    vi.useRealTimers();
  });

  it("respects custom timeout option", async () => {
    vi.useFakeTimers();
    const abortSpy = vi.spyOn(AbortController.prototype, "abort");

    global.fetch = vi.fn().mockImplementation((_url, options) => {
      return new Promise((_resolve, reject) => {
        if (options?.signal) {
          options.signal.addEventListener("abort", () => {
            reject(new DOMException("The operation was aborted", "AbortError"));
          });
        }
      });
    });

    const requestPromise = request("/slow-endpoint", { timeout: 5000 });
    vi.advanceTimersByTime(5000);

    await expect(requestPromise).rejects.toThrow("Request timeout");
    expect(abortSpy).toHaveBeenCalled();

    abortSpy.mockRestore();
    vi.useRealTimers();
  });

  it("completes successfully before timeout", async () => {
    vi.useFakeTimers();
    mockFetch(200, { data: "ok" });

    const requestPromise = request("/fast-endpoint", { timeout: 10000 });
    vi.advanceTimersByTime(100);

    const result = await requestPromise;
    expect(result).toEqual({ data: "ok" });

    vi.useRealTimers();
  });

  it("passes AbortSignal to fetch", async () => {
    mockFetch(200, { data: "ok" });
    await request("/models");

    const fetchOptions = (fetch as any).mock.calls[0][1];
    expect(fetchOptions.signal).toBeDefined();
    expect(fetchOptions.signal).toBeInstanceOf(AbortSignal);
  });

  it("retries on timeout when retries option is set", async () => {
    vi.useFakeTimers();
    let attemptCount = 0;

    global.fetch = vi.fn().mockImplementation((_url, options) => {
      attemptCount++;
      return new Promise((_resolve, reject) => {
        if (options?.signal) {
          options.signal.addEventListener("abort", () => {
            reject(new DOMException("The operation was aborted", "AbortError"));
          });
        }
      });
    });

    const requestPromise = request("/flaky-endpoint", {
      timeout: 1000,
      retries: 2,
      retryDelay: 100,
    });

    // First attempt timeout
    vi.advanceTimersByTime(1000);
    await vi.advanceTimersByTimeAsync(100); // retry delay

    // Second attempt timeout
    vi.advanceTimersByTime(1000);
    await vi.advanceTimersByTimeAsync(100); // retry delay

    // Third attempt timeout
    vi.advanceTimersByTime(1000);

    await expect(requestPromise).rejects.toThrow("Request timeout");
    expect(attemptCount).toBe(3); // initial + 2 retries

    vi.useRealTimers();
  });

  it("succeeds on retry after initial timeout", async () => {
    vi.useFakeTimers();
    let attemptCount = 0;

    global.fetch = vi.fn().mockImplementation((_url, options) => {
      attemptCount++;
      return new Promise((resolve, reject) => {
        if (attemptCount === 1) {
          // First attempt: timeout
          if (options?.signal) {
            options.signal.addEventListener("abort", () => {
              reject(
                new DOMException("The operation was aborted", "AbortError"),
              );
            });
          }
        } else {
          // Second attempt: success
          resolve({
            ok: true,
            status: 200,
            statusText: "OK",
            headers: { get: () => "application/json" },
            json: () => Promise.resolve({ data: "success" }),
            text: () => Promise.resolve(JSON.stringify({ data: "success" })),
          } as unknown as Response);
        }
      });
    });

    const requestPromise = request("/flaky-endpoint", {
      timeout: 1000,
      retries: 1,
      retryDelay: 100,
    });

    // First attempt timeout
    vi.advanceTimersByTime(1000);
    await vi.advanceTimersByTimeAsync(100); // retry delay

    const result = await requestPromise;
    expect(result).toEqual({ data: "success" });
    expect(attemptCount).toBe(2);

    vi.useRealTimers();
  });

  // ---------------------------------------------------------------------------
  // External AbortSignal handling
  // ---------------------------------------------------------------------------

  it("does not send request when caller signal is already aborted", async () => {
    mockFetch(200, { data: "ok" });

    const controller = new AbortController();
    controller.abort();

    await expect(
      request("/models", { signal: controller.signal }),
    ).rejects.toThrow("aborted");

    expect(fetch).not.toHaveBeenCalled();
  });

  it("does not retry when caller manually aborts (not timeout)", async () => {
    let attemptCount = 0;

    global.fetch = vi.fn().mockImplementation((_url, options) => {
      attemptCount++;
      return new Promise((_resolve, reject) => {
        if (options?.signal) {
          options.signal.addEventListener("abort", () => {
            reject(new DOMException("The operation was aborted", "AbortError"));
          });
        }
      });
    });

    const callerController = new AbortController();
    const requestPromise = request("/cancel-endpoint", {
      timeout: 30000,
      retries: 3,
      signal: callerController.signal,
    });

    // Simulate caller aborting immediately (not a timeout)
    callerController.abort();

    await expect(requestPromise).rejects.toThrow("aborted");
    expect(attemptCount).toBe(1); // no retries for external abort
  });

  it("cleans up abort listener on caller signal after successful request", async () => {
    mockFetch(200, { data: "ok" });

    const callerController = new AbortController();
    const removeSpy = vi.spyOn(callerController.signal, "removeEventListener");

    await request("/models", { signal: callerController.signal });

    expect(removeSpy).toHaveBeenCalledWith("abort", expect.any(Function));
    removeSpy.mockRestore();
  });
});
