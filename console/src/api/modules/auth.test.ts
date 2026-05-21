import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
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

describe("authApi.updateProfile", () => {
  beforeEach(() => {
    localStorage.clear();
  });
  afterEach(() => vi.clearAllMocks());

  it("sends POST to /api/auth/update-profile", async () => {
    mockFetch(200, { token: "t", username: "alice" });
    await authApi.updateProfile("oldpass", "newname");
    expect(fetch).toHaveBeenCalledWith(
      "/api/auth/update-profile",
      expect.anything(),
    );
  });

  it("request body contains current password and new username", async () => {
    mockFetch(200, { token: "t", username: "newname" });
    await authApi.updateProfile("oldpass", "newname");
    const body = JSON.parse((fetch as any).mock.calls[0][1].body);
    expect(body.current_password).toBe("oldpass");
    expect(body.new_username).toBe("newname");
    expect(body.new_password).toBeNull();
  });

  it("reads token from localStorage and injects Authorization header", async () => {
    localStorage.setItem("qwenpaw_auth_token", "my-token");
    mockFetch(200, { token: "t", username: "alice" });
    await authApi.updateProfile("oldpass");
    const headers = (fetch as any).mock.calls[0][1].headers;
    expect(headers.Authorization).toBe("Bearer my-token");
  });

  it("throws detail error on update failure", async () => {
    mockFetch(400, { detail: "Incorrect password" });
    await expect(authApi.updateProfile("wrong")).rejects.toThrow(
      "Incorrect password",
    );
  });
});
