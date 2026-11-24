/**
 * Contract tests for `governanceRequest`, the single runtime export of
 * `api/modules/hubGovernance.ts`.
 *
 * Division of labour: this file is the only test file for the module (the
 * module previously had none). The rest of the module is pure `interface`
 * declarations that carry no runtime statements, so `governanceRequest` is the
 * whole surface worth pinning.
 *
 * What is asserted here is the frontend contract only: which URL is built,
 * which method and headers go out, when a body is serialised, and how a failed
 * response is mapped onto an `Error`. Backend behaviour is out of scope.
 *
 * Note on the fallback message: the module passes "Hub request failed" to
 * `responseErrorMessage`, which reads the payload through `formatApiError`.
 * So the message that reaches the caller depends on the shape of `detail`
 * (string / validation array / object), and every one of those arms is pinned
 * below rather than assumed.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getApiToken, getApiUrl } from "../config";
import { governanceRequest } from "./hubGovernance";

vi.mock("../config", () => ({
  getApiUrl: vi.fn((path: string) => `http://test.local${path}`),
  getApiToken: vi.fn(() => "tok-abc"),
}));

interface MockResponseInit {
  ok: boolean;
  status: number;
  /** Resolved value of `response.json()`. Ignored when `jsonRejects`. */
  json?: unknown;
  /** When true `response.json()` rejects, exercising the `.catch(() => null)` arm. */
  jsonRejects?: boolean;
}

function mockResponse(init: MockResponseInit): Response {
  return {
    ok: init.ok,
    status: init.status,
    json: init.jsonRejects
      ? () => Promise.reject(new Error("body is not JSON"))
      : () => Promise.resolve(init.json),
  } as unknown as Response;
}

/** Typed access to the fetch mock so assertions read the recorded call. */
function fetchMock() {
  return global.fetch as unknown as ReturnType<typeof vi.fn>;
}

/** Pull the `RequestInit` out of the first recorded fetch call. */
function lastInit(): RequestInit {
  const calls = fetchMock().mock.calls;
  return calls[calls.length - 1][1] as RequestInit;
}

/** Pull the URL out of the first recorded fetch call. */
function lastUrl(): string {
  const calls = fetchMock().mock.calls;
  return calls[calls.length - 1][0] as string;
}

/**
 * `await expect(fn()).rejects` widens the rejection to a union type, which
 * makes property access a compile error. This helper narrows it back and - more
 * importantly - fails loudly when the promise unexpectedly resolves, so a
 * broken assertion can never pass by accident.
 */
async function mustReject<T>(fn: () => Promise<unknown>): Promise<T> {
  try {
    await fn();
  } catch (error) {
    return error as T;
  }
  throw new Error("expected the call to reject, but it resolved");
}

describe("governanceRequest - request shape", () => {
  beforeEach(() => {
    global.fetch = vi.fn();
    vi.mocked(getApiUrl).mockClear();
    vi.mocked(getApiToken).mockClear();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("prefixes the path with /hub/ through getApiUrl", async () => {
    fetchMock().mockResolvedValue(
      mockResponse({ ok: true, status: 200, json: {} }),
    );

    await governanceRequest("policy");

    expect(getApiUrl).toHaveBeenCalledWith("/hub/policy");
    expect(lastUrl()).toBe("http://test.local/hub/policy");
  });

  it("keeps a nested path verbatim instead of re-normalising it", async () => {
    fetchMock().mockResolvedValue(
      mockResponse({ ok: true, status: 200, json: {} }),
    );

    await governanceRequest("usage/details?period=2026-09");

    expect(getApiUrl).toHaveBeenCalledWith("/hub/usage/details?period=2026-09");
  });

  it("defaults to GET when no method is passed", async () => {
    fetchMock().mockResolvedValue(
      mockResponse({ ok: true, status: 200, json: {} }),
    );

    await governanceRequest("models");

    expect(lastInit().method).toBe("GET");
  });

  it("honours an explicitly passed method", async () => {
    fetchMock().mockResolvedValue(
      mockResponse({ ok: true, status: 200, json: {} }),
    );

    await governanceRequest("models", "PATCH", { default_model_id: "m1" });

    expect(lastInit().method).toBe("PATCH");
  });

  it("sends the bearer token from getApiToken plus a JSON content type", async () => {
    fetchMock().mockResolvedValue(
      mockResponse({ ok: true, status: 200, json: {} }),
    );

    await governanceRequest("members");

    expect(getApiToken).toHaveBeenCalled();
    expect(lastInit().headers).toEqual({
      Authorization: "Bearer tok-abc",
      "Content-Type": "application/json",
    });
  });

  it("still sends the JSON content type on a GET without a body", async () => {
    fetchMock().mockResolvedValue(
      mockResponse({ ok: true, status: 200, json: {} }),
    );

    await governanceRequest("members");

    expect(lastInit().headers).toMatchObject({
      "Content-Type": "application/json",
    });
  });

  it("omits the body entirely when no body argument is given", async () => {
    fetchMock().mockResolvedValue(
      mockResponse({ ok: true, status: 200, json: {} }),
    );

    await governanceRequest("invites");

    expect(lastInit().body).toBeUndefined();
  });

  it("omits the body when the caller passes undefined explicitly", async () => {
    fetchMock().mockResolvedValue(
      mockResponse({ ok: true, status: 200, json: {} }),
    );

    await governanceRequest("invites", "GET", undefined);

    expect(lastInit().body).toBeUndefined();
  });

  it("serialises a body object with JSON.stringify", async () => {
    fetchMock().mockResolvedValue(
      mockResponse({ ok: true, status: 200, json: {} }),
    );
    const body = { default_model_id: "m1", timezone: "Asia/Shanghai" };

    await governanceRequest("policy", "PUT", body);

    expect(lastInit().body).toBe(JSON.stringify(body));
  });

  it("serialises a null body rather than dropping it", async () => {
    fetchMock().mockResolvedValue(
      mockResponse({ ok: true, status: 200, json: {} }),
    );

    await governanceRequest("policy", "PUT", null);

    // `body === undefined` is the only guard, so null is a real payload here.
    expect(lastInit().body).toBe("null");
  });

  it("serialises a falsy-but-defined body such as 0 and empty string", async () => {
    fetchMock().mockResolvedValue(
      mockResponse({ ok: true, status: 200, json: {} }),
    );

    await governanceRequest("policy", "PUT", 0);
    expect(lastInit().body).toBe("0");

    await governanceRequest("policy", "PUT", "");
    expect(lastInit().body).toBe('""');
  });

  it("serialises an array body", async () => {
    fetchMock().mockResolvedValue(
      mockResponse({ ok: true, status: 200, json: {} }),
    );
    const body = { user_ids: ["u1", "u2"] };

    await governanceRequest("members/u1/models", "PUT", body);

    expect(lastInit().body).toBe(JSON.stringify(body));
  });
});

describe("governanceRequest - success responses", () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("resolves the parsed JSON payload", async () => {
    const payload = { revision: 7, default_model_id: null };
    fetchMock().mockResolvedValue(
      mockResponse({ ok: true, status: 200, json: payload }),
    );

    await expect(governanceRequest("policy")).resolves.toEqual(payload);
  });

  it("returns undefined for a 204 without touching json()", async () => {
    const json = vi.fn(() => Promise.resolve({ unexpected: true }));
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      json,
    } as unknown as Response);

    await expect(
      governanceRequest("members/u1", "DELETE"),
    ).resolves.toBeUndefined();
    expect(json).not.toHaveBeenCalled();
  });

  it("propagates a json() rejection on the success path", async () => {
    fetchMock().mockResolvedValue(
      mockResponse({ ok: true, status: 200, jsonRejects: true }),
    );

    await expect(governanceRequest("policy")).rejects.toThrow(
      "body is not JSON",
    );
  });
});

describe("governanceRequest - failure mapping", () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("throws the module fallback when the error body is not JSON", async () => {
    fetchMock().mockResolvedValue(
      mockResponse({ ok: false, status: 502, jsonRejects: true }),
    );

    const error = await mustReject<Error>(() => governanceRequest("policy"));

    expect(error).toBeInstanceOf(Error);
    expect(error.message).toBe("Hub request failed");
  });

  it("throws the module fallback when the error body has no detail", async () => {
    fetchMock().mockResolvedValue(
      mockResponse({ ok: false, status: 403, json: {} }),
    );

    await expect(governanceRequest("policy")).rejects.toThrow(
      "Hub request failed",
    );
  });

  it("prefers a string detail over the fallback", async () => {
    fetchMock().mockResolvedValue(
      mockResponse({
        ok: false,
        status: 409,
        json: { detail: "revision conflict" },
      }),
    );

    await expect(governanceRequest("policy", "PUT", {})).rejects.toThrow(
      "revision conflict",
    );
  });

  it("ignores an empty string detail and falls back", async () => {
    fetchMock().mockResolvedValue(
      mockResponse({ ok: false, status: 500, json: { detail: "" } }),
    );

    await expect(governanceRequest("policy")).rejects.toThrow(
      "Hub request failed",
    );
  });

  it("joins a validation detail array with semicolons", async () => {
    fetchMock().mockResolvedValue(
      mockResponse({
        ok: false,
        status: 422,
        json: {
          detail: [
            { loc: ["body", "member_token_limit"], msg: "must be positive" },
            { loc: ["body", "timezone"], msg: "unknown timezone" },
          ],
        },
      }),
    );

    await expect(governanceRequest("policy", "PUT", {})).rejects.toThrow(
      "member_token_limit: must be positive; timezone: unknown timezone",
    );
  });

  it("drops the body segment from a validation detail path", async () => {
    fetchMock().mockResolvedValue(
      mockResponse({
        ok: false,
        status: 422,
        json: { detail: [{ loc: ["body"], msg: "invalid payload" }] },
      }),
    );

    await expect(governanceRequest("policy", "PUT", {})).rejects.toThrow(
      "invalid payload",
    );
  });

  it("keeps a numeric path segment in a validation detail message", async () => {
    fetchMock().mockResolvedValue(
      mockResponse({
        ok: false,
        status: 422,
        json: {
          detail: [{ loc: ["body", "user_ids", 1], msg: "unknown user" }],
        },
      }),
    );

    await expect(
      governanceRequest("members/u1/models", "PUT", {}),
    ).rejects.toThrow("user_ids.1: unknown user");
  });

  it("falls back when a validation detail array yields no usable message", async () => {
    fetchMock().mockResolvedValue(
      mockResponse({
        ok: false,
        status: 422,
        json: { detail: [{ loc: ["body"], msg: "" }, null, "plain-string"] },
      }),
    );

    await expect(governanceRequest("policy")).rejects.toThrow(
      "Hub request failed",
    );
  });

  it("reads msg from a detail object that has no loc", async () => {
    fetchMock().mockResolvedValue(
      mockResponse({
        ok: false,
        status: 400,
        json: { detail: { msg: "quota exceeded" } },
      }),
    );

    await expect(governanceRequest("policy")).rejects.toThrow("quota exceeded");
  });

  it("falls back for a non-object error payload", async () => {
    fetchMock().mockResolvedValue(
      mockResponse({ ok: false, status: 500, json: "gateway blew up" }),
    );

    await expect(governanceRequest("policy")).rejects.toThrow(
      "Hub request failed",
    );
  });

  it("falls back when the error payload is null", async () => {
    fetchMock().mockResolvedValue(
      mockResponse({ ok: false, status: 500, json: null }),
    );

    await expect(governanceRequest("policy")).rejects.toThrow(
      "Hub request failed",
    );
  });

  it("maps a 404 the same way as any other non-ok status", async () => {
    fetchMock().mockResolvedValue(
      mockResponse({
        ok: false,
        status: 404,
        json: { detail: "no such organization" },
      }),
    );

    await expect(governanceRequest("org")).rejects.toThrow(
      "no such organization",
    );
  });

  it("propagates a network level fetch rejection untouched", async () => {
    fetchMock().mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(governanceRequest("policy")).rejects.toThrow(
      "Failed to fetch",
    );
  });
});

describe("governanceRequest - generic typing", () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("narrows the resolved value to the caller supplied type", async () => {
    interface Catalog {
      revision: number;
      models: { id: string }[];
    }
    const payload: Catalog = { revision: 3, models: [{ id: "m1" }] };
    fetchMock().mockResolvedValue(
      mockResponse({ ok: true, status: 200, json: payload }),
    );

    const result = await governanceRequest<Catalog>("catalog");

    // Property access below only compiles because the generic was honoured.
    expect(result.models[0].id).toBe("m1");
    expect(result.revision).toBe(3);
  });

  it("types a 204 as the generic parameter even though it is undefined", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue({ ok: true, status: 204 } as unknown as Response);

    const result = await governanceRequest<{ cleared: boolean }>(
      "invites/batch",
      "DELETE",
    );

    expect(result).toBeUndefined();
  });
});
