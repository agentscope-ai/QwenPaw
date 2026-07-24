import { describe, it, expect, vi, afterEach } from "vitest";
import { authApi } from "./auth";

// auth.ts uses fetch directly (not the request wrapper), so mock global fetch
vi.mock("../config", () => ({
  getApiUrl: (path: string) => `/api${path}`,
}));

function mockFetch(status: number, body: unknown) {
  global.fetch = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Bad Request",
    json: () => Promise.resolve(body),
    text: () =>
      Promise.resolve(typeof body === "string" ? body : JSON.stringify(body)),
  } as unknown as Response);
}

describe("authApi.login", () => {
  afterEach(() => vi.clearAllMocks());

  it("returns token and username on successful login", async () => {
    mockFetch(200, { token: "tok-123", username: "alice" });
    const result = await authApi.login("alice", "pass");
    expect(result).toEqual({ token: "tok-123", username: "alice" });
  });

  it("sends POST to /api/auth/login", async () => {
    mockFetch(200, { token: "tok", username: "alice" });
    await authApi.login("alice", "pass");
    expect(fetch).toHaveBeenCalledWith(
      "/api/auth/login",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("request body contains username and password", async () => {
    mockFetch(200, { token: "tok", username: "alice" });
    await authApi.login("alice", "secret");
    const body = JSON.parse((fetch as any).mock.calls[0][1].body);
    expect(body).toEqual({ username: "alice", password: "secret" });
  });

  it("throws error with detail on login failure", async () => {
    mockFetch(401, { detail: "Invalid username or password" });
    await expect(authApi.login("alice", "wrong")).rejects.toThrow(
      "Invalid username or password",
    );
  });

  it("throws default error when response has no detail", async () => {
    mockFetch(401, {});
    await expect(authApi.login("alice", "wrong")).rejects.toThrow(
      "Login failed",
    );
  });
});

describe("authApi.getStatus", () => {
  afterEach(() => vi.clearAllMocks());

  it("returns enabled and mode fields", async () => {
    mockFetch(200, { enabled: true, mode: "nocobase" });
    const result = await authApi.getStatus();
    expect(result).toEqual({ enabled: true, mode: "nocobase" });
  });

  it("throws error when request fails", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: () => Promise.resolve({}),
    } as unknown as Response);
    await expect(authApi.getStatus()).rejects.toThrow(
      "Failed to check auth status",
    );
  });
});
