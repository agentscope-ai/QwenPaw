import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getApiToken, setApiAuthMode } from "./config";
import {
  adoptAccessSession,
  clearAccessSession,
  getAccessSessionGeneration,
} from "./authSession";
import { request } from "./request";

describe("authentication recovery through the real request and refresh path", () => {
  it("never reuses a captured token after the current identity has been cleared", async () => {
    clearAccessSession(false);
    const fetcher = vi.fn(async (_url: string, options: RequestInit) => {
      expect(new Headers(options.headers).has("Authorization")).toBe(false);
      return Response.json({ ok: true });
    });
    vi.stubGlobal("fetch", fetcher);
    await request("/public", {
      headers: { Authorization: "Bearer previously-signed-in" },
    });
  });
  beforeEach(() => {
    clearAccessSession(false);
    setApiAuthMode("multi_user");
    Object.defineProperty(window, "location", {
      value: { pathname: "/chat", search: "", hash: "", href: "" },
      configurable: true,
    });
    adoptAccessSession(
      { token: "still-recoverable", username: "fixture" },
      false,
    );
  });
  afterEach(() => {
    clearAccessSession(false);
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it.each([503, "offline"] as const)(
    "keeps the session and page when refresh temporarily fails (%s)",
    async (failure) => {
      const generation = getAccessSessionGeneration();
      vi.stubGlobal(
        "fetch",
        vi.fn(async (url: string) => {
          if (url.endsWith("/auth/refresh")) {
            if (failure === "offline") throw new TypeError("Failed to fetch");
            return new Response(
              JSON.stringify({ detail: "Temporarily unavailable" }),
              { status: failure },
            );
          }
          return new Response("{}", { status: 401 });
        }),
      );
      await expect(request("/models")).rejects.toBeInstanceOf(Error);
      expect(getAccessSessionGeneration()).toBe(generation);
      expect(getApiToken()).toBe("still-recoverable");
      expect(window.location.href).toBe("");
    },
  );

  it("replaces a caller's captured bearer token after successful renewal", async () => {
    const generation = getAccessSessionGeneration();
    let refreshes = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, options: RequestInit) => {
        if (url.endsWith("/auth/refresh")) {
          refreshes++;
          return Response.json({ token: "renewed", username: "fixture" });
        }
        const headers = new Headers(options.headers);
        expect(headers.get("X-Agent-Id")).toBe("original-agent");
        return headers.get("Authorization") === "Bearer renewed"
          ? Response.json({ ok: true })
          : new Response("{}", { status: 401 });
      }),
    );
    await expect(
      request("/workspace/files", {
        headers: {
          Authorization: "Bearer still-recoverable",
          "X-Agent-Id": "original-agent",
        },
      }),
    ).resolves.toEqual({ ok: true });
    expect(refreshes).toBe(1);
    expect(getAccessSessionGeneration()).toBe(generation);
    expect(window.location.href).toBe("");
  });

  it("retries a late old-token 401 with the already renewed token without rotating again", async () => {
    let finish!: (response: Response) => void;
    const fetcher = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            finish = resolve;
          }),
      )
      .mockResolvedValue(Response.json({ ok: true }));
    vi.stubGlobal("fetch", fetcher);
    const pending = request("/models");
    adoptAccessSession(
      { token: "another-tab-renewed", username: "fixture" },
      false,
    );
    finish(new Response("{}", { status: 401 }));
    await expect(pending).resolves.toEqual({ ok: true });
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(
      new Headers(fetcher.mock.calls[1][1].headers).get("Authorization"),
    ).toBe("Bearer another-tab-renewed");
  });

  it("coalesces simultaneous old-token failures and preserves caller scope on all retries", async () => {
    let rotations = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, options: RequestInit) => {
        if (url.endsWith("/auth/refresh")) {
          rotations++;
          return Response.json({ token: "new", username: "fixture" });
        }
        const headers = new Headers(options.headers);
        expect(headers.get("X-Agent-Id")).toBe("fixed-agent");
        return headers.get("Authorization") === "Bearer new"
          ? Response.json({ ok: true })
          : new Response("{}", { status: 401 });
      }),
    );
    const values = await Promise.all(
      ["/files", "/console/push-messages", "/runtime-status/current"].map(
        (path) =>
          request(path, {
            headers: {
              Authorization: "Bearer still-recoverable",
              "X-Agent-Id": "fixed-agent",
            },
          }),
      ),
    );
    expect(values).toEqual([{ ok: true }, { ok: true }, { ok: true }]);
    expect(rotations).toBe(1);
  });

  it("only signs out when the refresh endpoint explicitly rejects the session", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response('{"detail":"Session expired"}', { status: 401 }),
      ),
    );
    await expect(request("/models")).rejects.toMatchObject({
      status: 401,
      rawMessage: "Not authenticated",
    });
    expect(getApiToken()).toBe("");
    expect(window.location.href).toBe("/login?redirect=%2Fchat");
  });

  it("does not sign out for a business endpoint's 401 after successful renewal", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url.endsWith("/auth/refresh")
          ? Response.json({ token: "valid-new", username: "fixture" })
          : new Response("{}", { status: 401 }),
      ),
    );
    await expect(request("/models")).rejects.toMatchObject({
      status: 401,
      rawMessage: "Not authenticated",
    });
    expect(getApiToken()).toBe("valid-new");
    expect(window.location.href).toBe("");
  });

  it("retries a failed proactive refresh after backoff without requiring another login", async () => {
    vi.useFakeTimers();
    const generation = getAccessSessionGeneration();
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(new Response("{}", { status: 503 }))
      .mockImplementation(async () =>
        Response.json({
          token: "recovered",
          username: "fixture",
          access_expires_at: new Date(Date.now() + 900_000).toISOString(),
        }),
      );
    vi.stubGlobal("fetch", fetcher);
    adoptAccessSession(
      {
        token: "still-recoverable",
        username: "fixture",
        access_expires_at: new Date(Date.now() + 900_000).toISOString(),
      },
      false,
    );
    await vi.advanceTimersByTimeAsync(840_000);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(getAccessSessionGeneration()).toBe(generation);
    await vi.advanceTimersByTimeAsync(5_000);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(getApiToken()).toBe("recovered");
  });

  it("does not clear a new identity when an earlier refresh finishes after logout", async () => {
    let finish!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url.endsWith("/auth/refresh")
          ? new Promise<Response>((resolve) => {
              finish = resolve;
            })
          : new Response("{}", { status: 401 }),
      ),
    );
    const pending = request("/models");
    await vi.waitFor(() => expect(finish).toBeTypeOf("function"));
    clearAccessSession(false);
    adoptAccessSession({ token: "different-login", username: "other" }, false);
    finish(new Response("{}", { status: 401 }));
    await expect(pending).rejects.toThrow("Authentication context changed");
    expect(getApiToken()).toBe("different-login");
    expect(window.location.href).toBe("");
  });
});
