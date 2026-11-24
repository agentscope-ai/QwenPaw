/**
 * Tests for hostFetch, the auth-aware fetch wrapper plugins use.
 *
 * Four call sites depend on it (hostSdk/install.ts plus the pawapp-sdk
 * host/api/task modules), so two behaviours are contractual:
 *   - the caller's path must be resolved through getApiUrl, not passed
 *     straight to fetch, otherwise the /api prefix is lost;
 *   - buildAuthHeaders must run on every call and caller-supplied headers
 *     must win on a collision, so a plugin can override Content-Type
 *     without dropping the Authorization token.
 *
 * getApiUrl and buildAuthHeaders are mocked: this suite pins the wrapper's
 * delegation contract, while the real URL/token derivation is covered by
 * the api/config and authHeaders suites.
 */
// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  apiUrl: vi.fn(),
  authHeaders: vi.fn(),
}));

vi.mock("../../api/config", () => ({
  getApiUrl: mocks.apiUrl,
}));
vi.mock("../../api/authHeaders", () => ({
  buildAuthHeaders: mocks.authHeaders,
}));

import { hostFetch } from "./fetch";

function stubFetch(): ReturnType<typeof vi.fn> {
  const fake = vi.fn().mockResolvedValue({ ok: true, status: 200 });
  vi.stubGlobal("fetch", fake);
  return fake;
}

beforeEach(() => {
  mocks.apiUrl.mockImplementation((path: string) => `/api${path}`);
  mocks.authHeaders.mockReturnValue({ Authorization: "Bearer token-abc" });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("hostFetch", () => {
  it("resolves the path through getApiUrl instead of passing it through", async () => {
    const fake = stubFetch();

    await hostFetch("/console/chat");

    expect(mocks.apiUrl).toHaveBeenCalledWith("/console/chat");
    expect(fake).toHaveBeenCalledWith(
      "/api/console/chat",
      expect.objectContaining({ headers: expect.any(Object) }),
    );
  });

  it("injects the auth headers on every call", async () => {
    const fake = stubFetch();

    await hostFetch("/skills");

    expect(mocks.authHeaders).toHaveBeenCalled();
    expect(fake.mock.calls[0][1].headers).toEqual({
      Authorization: "Bearer token-abc",
    });
  });

  it("lets caller headers win on a collision but keeps the token otherwise", async () => {
    const fake = stubFetch();
    mocks.authHeaders.mockReturnValue({
      Authorization: "Bearer token-abc",
      "X-Agent-Id": "agent-1",
    });

    await hostFetch("/chat", {
      headers: { Authorization: "Bearer overridden", "Content-Type": "text/x" },
    });

    expect(fake.mock.calls[0][1].headers).toEqual({
      Authorization: "Bearer overridden",
      "X-Agent-Id": "agent-1",
      "Content-Type": "text/x",
    });
  });

  it("tolerates an init object without headers", async () => {
    const fake = stubFetch();

    await hostFetch("/models", { method: "POST" });

    expect(fake.mock.calls[0][1].headers).toEqual({
      Authorization: "Bearer token-abc",
    });
  });

  it("tolerates explicit undefined headers", async () => {
    const fake = stubFetch();

    await hostFetch("/models", { method: "GET", headers: undefined });

    expect(fake.mock.calls[0][1].headers).toEqual({
      Authorization: "Bearer token-abc",
    });
  });

  it("works with no init argument at all", async () => {
    const fake = stubFetch();

    await hostFetch("/health");

    expect(fake).toHaveBeenCalledTimes(1);
    expect(fake.mock.calls[0][1].headers).toEqual({
      Authorization: "Bearer token-abc",
    });
  });

  it("passes the other init fields through untouched", async () => {
    const fake = stubFetch();

    await hostFetch("/upload", {
      method: "PUT",
      body: "payload",
      mode: "cors",
    });

    expect(fake.mock.calls[0][1]).toEqual(
      expect.objectContaining({
        method: "PUT",
        body: "payload",
        mode: "cors",
      }),
    );
  });

  it("sends no auth header when there is no token", async () => {
    const fake = stubFetch();
    mocks.authHeaders.mockReturnValue({});

    await hostFetch("/public");

    expect(fake.mock.calls[0][1].headers).toEqual({});
  });

  it("returns the very response fetch produced, unwrapped", async () => {
    const fake = stubFetch();
    const body = new Response("echo", { status: 200 });
    fake.mockResolvedValue(body);

    const res = await hostFetch("/anything");

    // Identity, not a copy: callers chain .json() / .body off the real Response.
    expect(res).toBe(body);
    expect(res.status).toBe(200);
    expect(await res.text()).toBe("echo");
  });

  it("propagates a network rejection instead of swallowing it", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));

    await expect(hostFetch("/boom")).rejects.toThrow("offline");
  });
});
