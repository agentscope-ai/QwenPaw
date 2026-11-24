/**
 * pawapp.ts - fetch contract layer for the installed PawApp surface.
 *
 * There is no sibling test file for this module, so nothing here duplicates an
 * existing suite. Before this file the module sat at 2/19 statements: only
 * getStaticUrl had ever been exercised (indirectly, through the PawApp host
 * components), while all four async wrappers and every one of their ten
 * branches were untouched.
 *
 * Unlike most api/modules files this one calls global fetch directly rather
 * than going through ../request, so the stubbing target is fetch and the
 * assertions cover URL, method and headers.
 *
 * Two contract details are pinned here because a silent change to either would
 * not be caught anywhere else:
 *   - uninstall reads its error detail with `res.json().catch(() => ({}))`.
 *     The arrow body is its own statement, so it is only reachable when json()
 *     *rejects*; stubbing json() to resolve with {} takes the `?? ` fallback
 *     instead and leaves that statement uncovered. Both routes are asserted,
 *     plus the two arms of the `detail ?? template` expression.
 *   - getStaticUrl percent-encodes appId but splices filePath in verbatim, so
 *     a path separator survives while a space in the app id does not. That
 *     asymmetry is deliberate (static assets keep their nested path) and is
 *     pinned so a future "fix" cannot silently flatten asset paths.
 *
 * Assertions are on URL / method / headers / error text - the frontend
 * contract - never on backend behaviour.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { pawappApi } from "./pawapp";

vi.mock("../config", () => ({
  getApiUrl: (path: string) => `/api${path}`,
  getApiToken: vi.fn(() => ""),
}));
vi.mock("../authHeaders", () => ({
  buildAuthHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));

import { buildAuthHeaders } from "../authHeaders";

/** Minimal Response stand-in: only the fields the module actually reads. */
function stubFetch(init: {
  ok: boolean;
  status?: number;
  statusText?: string;
  json?: () => Promise<unknown>;
}): void {
  const json = init.json ?? (() => Promise.resolve({}));
  const response = {
    ok: init.ok,
    status: init.status ?? (init.ok ? 200 : 500),
    statusText: init.statusText ?? (init.ok ? "OK" : "Internal Server Error"),
    json,
    // On a 409 the product now reads the body twice: once through clone() to
    // probe for a plugin-busy payload (see api/pluginBusy.ts, added by #7565),
    // and once for the error message (responseErrorMessage). clone() must hand
    // back a still-readable body exactly as a real Response does, so this
    // stand-in shares the same json() reader across the clone.
    clone: () => ({ ...response, json }),
  };
  global.fetch = vi.fn().mockResolvedValue(response as unknown as Response);
}

function callArgs(): { url: string; opts: RequestInit } {
  const call = vi.mocked(global.fetch).mock.calls[0];
  return { url: call[0] as string, opts: (call[1] ?? {}) as RequestInit };
}

afterEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

/** Reject-safe helper: resolves with the thrown error, throws if it resolved. */
async function mustReject<T = Error>(run: () => Promise<unknown>): Promise<T> {
  try {
    await run();
  } catch (e) {
    return e as T;
  }
  throw new Error("expected the promise to reject, but it resolved");
}

describe("pawappApi.list", () => {
  it("GETs the collection root with auth headers and no method override", async () => {
    const payload = { apps: [], total: 0 };
    stubFetch({ ok: true, json: () => Promise.resolve(payload) });

    const out = await pawappApi.list();

    const { url, opts } = callArgs();
    expect(url).toBe("/api/pawapps");
    expect(opts.method).toBeUndefined();
    expect(opts.headers).toEqual({ Authorization: "Bearer t" });
    expect(out).toEqual(payload);
  });

  it("passes the resolved body through untouched", async () => {
    const payload = {
      apps: [
        {
          id: "qwenpaw-creator",
          name: "Creator",
          version: "1.0.0",
          description: "",
          author: "",
          category: "",
          icon: "",
          status: "installed",
          home_page: null,
          dir: "/apps/creator",
          settings: [],
          permissions: {},
          backends: {},
        },
      ],
      total: 1,
    };
    stubFetch({ ok: true, json: () => Promise.resolve(payload) });

    await expect(pawappApi.list()).resolves.toEqual(payload);
  });

  it("throws with the statusText when the list call fails", async () => {
    stubFetch({ ok: false, status: 503, statusText: "Service Unavailable" });

    const err = await mustReject(() => pawappApi.list());

    expect(err).toBeInstanceOf(Error);
    expect((err as Error).message).toBe(
      "Failed to list PawApps: Service Unavailable",
    );
  });

  it("does not read the body when the list call fails", async () => {
    const json = vi.fn(() => Promise.resolve({ detail: "ignored" }));
    stubFetch({ ok: false, status: 500, statusText: "Boom", json });

    await mustReject(() => pawappApi.list());

    expect(json).not.toHaveBeenCalled();
  });

  it("asks the auth header builder once per call", async () => {
    stubFetch({ ok: true });

    await pawappApi.list();

    expect(buildAuthHeaders).toHaveBeenCalledTimes(1);
  });
});

describe("pawappApi.get", () => {
  it("GETs the keyed path", async () => {
    const payload = { id: "creator", name: "Creator" };
    stubFetch({ ok: true, json: () => Promise.resolve(payload) });

    const out = await pawappApi.get("creator");

    expect(callArgs().url).toBe("/api/pawapps/creator");
    expect(out).toEqual(payload);
  });

  it("percent-encodes an app id containing a space", async () => {
    stubFetch({ ok: true });

    await pawappApi.get("my app");

    expect(callArgs().url).toBe("/api/pawapps/my%20app");
  });

  it("percent-encodes an app id containing a slash so it cannot escape the path", async () => {
    stubFetch({ ok: true });

    await pawappApi.get("team/app");

    expect(callArgs().url).toBe("/api/pawapps/team%2Fapp");
  });

  it("percent-encodes a non-ASCII app id", async () => {
    stubFetch({ ok: true });

    await pawappApi.get("应用");

    expect(callArgs().url).toBe("/api/pawapps/%E5%BA%94%E7%94%A8");
  });

  it("throws with the raw app id and the statusText when the lookup fails", async () => {
    stubFetch({ ok: false, status: 404, statusText: "Not Found" });

    const err = await mustReject(() => pawappApi.get("team/app"));

    expect((err as Error).message).toBe(
      "Failed to get PawApp team/app: Not Found",
    );
  });
});

describe("pawappApi.getIframeUrl", () => {
  it("GETs the iframe sub-resource", async () => {
    const payload = { app_id: "creator", iframe_url: "/apps/creator/" };
    stubFetch({ ok: true, json: () => Promise.resolve(payload) });

    const out = await pawappApi.getIframeUrl("creator");

    expect(callArgs().url).toBe("/api/pawapps/creator/iframe");
    expect(out).toEqual(payload);
  });

  it("passes a null iframe_url through rather than coalescing it", async () => {
    const payload = { app_id: "creator", iframe_url: null, error: "no entry" };
    stubFetch({ ok: true, json: () => Promise.resolve(payload) });

    await expect(pawappApi.getIframeUrl("creator")).resolves.toEqual(payload);
  });

  it("percent-encodes the app id in the iframe path", async () => {
    stubFetch({ ok: true });

    await pawappApi.getIframeUrl("a b/c");

    expect(callArgs().url).toBe("/api/pawapps/a%20b%2Fc/iframe");
  });

  it("throws with the statusText when the iframe lookup fails", async () => {
    stubFetch({ ok: false, status: 502, statusText: "Bad Gateway" });

    const err = await mustReject(() => pawappApi.getIframeUrl("creator"));

    expect((err as Error).message).toBe(
      "Failed to get iframe URL for creator: Bad Gateway",
    );
  });

  it("keeps the iframe error text distinct from the get error text", async () => {
    stubFetch({ ok: false, status: 502, statusText: "Bad Gateway" });

    const iframeErr = await mustReject(() => pawappApi.getIframeUrl("creator"));
    const getErr = await mustReject(() => pawappApi.get("creator"));

    expect((iframeErr as Error).message).not.toBe((getErr as Error).message);
  });
});

describe("pawappApi.uninstall", () => {
  it("sends DELETE to the keyed path and resolves with undefined on success", async () => {
    stubFetch({ ok: true, status: 204 });

    const out = await pawappApi.uninstall("creator");

    const { url, opts } = callArgs();
    expect(url).toBe("/api/pawapps/creator");
    expect(opts.method).toBe("DELETE");
    expect(opts.headers).toEqual({ Authorization: "Bearer t" });
    expect(out).toBeUndefined();
  });

  it("percent-encodes the app id in the delete path", async () => {
    stubFetch({ ok: true });

    await pawappApi.uninstall("a b/c");

    expect(callArgs().url).toBe("/api/pawapps/a%20b%2Fc");
  });

  it("prefers the server detail string over the status template", async () => {
    stubFetch({
      ok: false,
      status: 409,
      statusText: "Conflict",
      json: () => Promise.resolve({ detail: "app is running" }),
    });

    const err = await mustReject(() => pawappApi.uninstall("creator"));

    expect((err as Error).message).toBe("app is running");
  });

  it("falls back to the status template when the body carries no detail", async () => {
    stubFetch({
      ok: false,
      status: 409,
      statusText: "Conflict",
      json: () => Promise.resolve({ message: "not a detail key" }),
    });

    const err = await mustReject(() => pawappApi.uninstall("creator"));

    expect((err as Error).message).toBe("Uninstall failed (409)");
  });

  it("falls back to the status template when the body is empty JSON", async () => {
    stubFetch({
      ok: false,
      status: 500,
      json: () => Promise.resolve({}),
    });

    const err = await mustReject(() => pawappApi.uninstall("creator"));

    expect((err as Error).message).toBe("Uninstall failed (500)");
  });

  it("treats a null detail as absent and uses the status template", async () => {
    stubFetch({
      ok: false,
      status: 422,
      json: () => Promise.resolve({ detail: null }),
    });

    const err = await mustReject(() => pawappApi.uninstall("creator"));

    expect((err as Error).message).toBe("Uninstall failed (422)");
  });

  it("still reports the status template when reading the body itself fails", async () => {
    stubFetch({
      ok: false,
      status: 502,
      statusText: "Bad Gateway",
      json: () => Promise.reject(new Error("body stream aborted")),
    });

    const err = await mustReject(() => pawappApi.uninstall("creator"));

    expect((err as Error).message).toBe("Uninstall failed (502)");
  });

  it("does not leak the body parse error when json rejects", async () => {
    stubFetch({
      ok: false,
      status: 502,
      json: () => Promise.reject(new Error("body stream aborted")),
    });

    const err = await mustReject(() => pawappApi.uninstall("creator"));

    expect((err as Error).message).not.toContain("body stream aborted");
  });

  it("embeds the numeric status rather than the statusText in the fallback", async () => {
    stubFetch({
      ok: false,
      status: 418,
      statusText: "I am a teapot",
      json: () => Promise.resolve({}),
    });

    const err = await mustReject(() => pawappApi.uninstall("creator"));

    expect((err as Error).message).toBe("Uninstall failed (418)");
    expect((err as Error).message).not.toContain("teapot");
  });

  it("reads a 409 body twice: a busy-probe clone plus the error message", async () => {
    const json = vi.fn(() => Promise.resolve({ detail: "nope" }));
    stubFetch({ ok: false, status: 409, json });

    const err = await mustReject(() => pawappApi.uninstall("creator"));

    // Since #7565 uninstall routes through requestWithPluginBusyConfirmation,
    // which clones the body to probe for a plugin-busy payload before the
    // error message is read from the original response. Two reads is the
    // intended contract (dropping the busy probe, or the clone that keeps the
    // original body readable, would change this count), and the server detail
    // must still surface through the second read.
    expect(json).toHaveBeenCalledTimes(2);
    expect((err as Error).message).toBe("nope");
  });

  it("does not read the body at all on success", async () => {
    const json = vi.fn(() => Promise.resolve({ detail: "unused" }));
    stubFetch({ ok: true, status: 204, json });

    await pawappApi.uninstall("creator");

    expect(json).not.toHaveBeenCalled();
  });
});

describe("pawappApi.getStaticUrl", () => {
  it("builds a static asset URL without issuing a request", async () => {
    stubFetch({ ok: true });

    const url = pawappApi.getStaticUrl("creator", "icon.png");

    expect(url).toBe("/api/pawapps/creator/static/icon.png");
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("percent-encodes the app id but keeps the asset path verbatim", () => {
    const url = pawappApi.getStaticUrl("my app", "assets/logo.png");

    expect(url).toBe("/api/pawapps/my%20app/static/assets/logo.png");
  });

  it("keeps a nested asset path unflattened", () => {
    const url = pawappApi.getStaticUrl("creator", "a/b/c/d.txt");

    expect(url).toBe("/api/pawapps/creator/static/a/b/c/d.txt");
    expect(url).not.toContain("%2F");
  });

  it("preserves non-ASCII characters in the asset path", () => {
    const url = pawappApi.getStaticUrl("creator", "图标.png");

    expect(url).toBe("/api/pawapps/creator/static/图标.png");
  });

  it("is synchronous and returns a plain string", () => {
    const url = pawappApi.getStaticUrl("creator", "icon.png");

    expect(typeof url).toBe("string");
    expect(url).not.toBeInstanceOf(Promise);
  });
});
