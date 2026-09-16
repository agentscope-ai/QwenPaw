import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { authApi } from "./auth";

// auth.ts uses fetch directly (not the request wrapper), so mock global fetch
vi.mock("../config", () => ({
  getApiUrl: (path: string) => `/api${path}`,
  getApiToken: () => localStorage.getItem("qwenpaw_auth_token") || "",
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

describe("authApi.register", () => {
  afterEach(() => vi.clearAllMocks());

  it("returns token and username on successful registration", async () => {
    mockFetch(200, { token: "tok-new", username: "bob" });
    const result = await authApi.register("bob", "pass123");
    expect(result.token).toBe("tok-new");
  });

  it("sends POST to /api/auth/register", async () => {
    mockFetch(200, { token: "t", username: "bob" });
    await authApi.register("bob", "pass");
    expect(fetch).toHaveBeenCalledWith("/api/auth/register", expect.anything());
  });

  it("throws detail error on registration failure", async () => {
    mockFetch(409, { detail: "Username already exists" });
    await expect(authApi.register("bob", "pass")).rejects.toThrow(
      "Username already exists",
    );
  });

  it('throws "Registration failed" when response has no detail', async () => {
    mockFetch(500, {});
    await expect(authApi.register("bob", "pass")).rejects.toThrow(
      "Registration failed",
    );
  });
});

describe("authApi.getStatus", () => {
  afterEach(() => vi.clearAllMocks());

  it("returns enabled and has_users fields", async () => {
    mockFetch(200, { enabled: true, has_users: false });
    const result = await authApi.getStatus();
    expect(result).toEqual({ enabled: true, has_users: false });
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

describe("authApi multi-user sessions", () => {
  afterEach(() => vi.clearAllMocks());

  it("refreshes with browser credentials and no JavaScript cookie access", async () => {
    mockFetch(200, { token: "new-access", username: "alice" });
    await authApi.refresh();
    expect(fetch).toHaveBeenCalledWith(
      "/api/auth/refresh",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
  });

  it("logs out through the HttpOnly refresh cookie", async () => {
    mockFetch(200, { revoked: true });
    await authApi.logout();
    expect(fetch).toHaveBeenCalledWith(
      "/api/auth/logout",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
  });

  it("loads current user and preferences with the memory bearer token", async () => {
    mockFetch(200, {
      user: { id: "1", username: "alice", platform_role: "member" },
      preferences: { language: "en", timezone: "UTC" },
    });
    const result = await authApi.getMe();
    expect(result.preferences.timezone).toBe("UTC");
  });

  it("updates the current user's enterprise profile", async () => {
    mockFetch(200, {
      user: { id: "1", username: "alice", department: "研发部" },
    });
    await authApi.updateProfile({ username: "alice", department: "研发部" });

    expect(fetch).toHaveBeenCalledWith(
      "/api/me/profile",
      expect.objectContaining({ method: "PATCH" }),
    );
  });

  it("changes password with both current and new passwords", async () => {
    mockFetch(200, { revoked_sessions: 2 });
    await authApi.changePassword("old-password", "new-password");

    const options = (fetch as any).mock.calls[0][1];
    expect(fetch).toHaveBeenCalledWith(
      "/api/me/change-password",
      expect.objectContaining({ method: "POST" }),
    );
    expect(JSON.parse(options.body)).toEqual({
      current_password: "old-password",
      new_password: "new-password",
    });
  });
});

describe("authApi.updateLegacyProfile", () => {
  beforeEach(() => {
    localStorage.clear();
  });
  afterEach(() => vi.clearAllMocks());

  it("sends POST to /api/auth/update-profile", async () => {
    mockFetch(200, { token: "t", username: "alice" });
    await authApi.updateLegacyProfile("oldpass", "newname");
    expect(fetch).toHaveBeenCalledWith(
      "/api/auth/update-profile",
      expect.anything(),
    );
  });

  it("request body contains current password and new username", async () => {
    mockFetch(200, { token: "t", username: "newname" });
    await authApi.updateLegacyProfile("oldpass", "newname");
    const body = JSON.parse((fetch as any).mock.calls[0][1].body);
    expect(body.current_password).toBe("oldpass");
    expect(body.new_username).toBe("newname");
    expect(body.new_password).toBeNull();
  });

  it("reads token from localStorage and injects Authorization header", async () => {
    localStorage.setItem("qwenpaw_auth_token", "my-token");
    mockFetch(200, { token: "t", username: "alice" });
    await authApi.updateLegacyProfile("oldpass");
    const headers = (fetch as any).mock.calls[0][1].headers;
    expect(headers.Authorization).toBe("Bearer my-token");
  });

  it("throws detail error on update failure", async () => {
    mockFetch(400, { detail: "Incorrect password" });
    await expect(authApi.updateLegacyProfile("wrong")).rejects.toThrow(
      "Incorrect password",
    );
  });
});
