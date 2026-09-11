import { beforeEach, describe, expect, it, vi } from "vitest";

import { authApi } from "../api/modules/auth";
import { resolveAuthGate, resolveBackendMode } from "./gate";

vi.mock("../api/modules/auth", () => ({
  authApi: { getStatus: vi.fn() },
}));

const getStatus = vi.mocked(authApi.getStatus);

describe("authentication gate", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  it("detects Hub and standard backends explicitly", async () => {
    getStatus.mockResolvedValueOnce({
      enabled: true,
      has_users: true,
      mode: "hub",
    });
    await expect(resolveBackendMode()).resolves.toBe("hub");

    getStatus.mockResolvedValueOnce({ enabled: false, has_users: false });
    await expect(resolveBackendMode()).resolves.toBe("standard");
  });

  it("fails closed when backend mode cannot be detected", async () => {
    getStatus.mockRejectedValueOnce(new Error("offline"));
    await expect(resolveBackendMode()).rejects.toThrow("offline");
  });

  it("allows an explicitly disabled authentication mode", async () => {
    getStatus.mockResolvedValueOnce({ enabled: false, has_users: false });
    await expect(resolveAuthGate()).resolves.toBe("ok");
  });

  it("requires login when the current window has no token", async () => {
    getStatus.mockResolvedValueOnce({ enabled: true, has_users: true });
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    await expect(resolveAuthGate()).resolves.toBe("auth-required");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("reuses backend status during startup authentication", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    await expect(
      resolveAuthGate({ enabled: true, has_users: true, mode: "hub" }),
    ).resolves.toBe("auth-required");

    expect(getStatus).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("fails closed when authentication status is unavailable", async () => {
    getStatus.mockRejectedValueOnce(new Error("status unavailable"));
    await expect(resolveAuthGate()).rejects.toThrow("status unavailable");
  });

  it("accepts only a token verified by the backend", async () => {
    localStorage.setItem("qwenpaw_auth_token", "window-a-token");
    getStatus.mockResolvedValueOnce({ enabled: true, has_users: true });
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(null, { status: 200 }));

    await expect(resolveAuthGate()).resolves.toBe("ok");
    expect(fetchSpy).toHaveBeenCalledWith("/api/auth/verify", {
      headers: { Authorization: "Bearer window-a-token" },
    });
  });

  it("clears a rejected token and requires login", async () => {
    localStorage.setItem("qwenpaw_auth_token", "expired-token");
    getStatus.mockResolvedValueOnce({ enabled: true, has_users: true });
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(null, { status: 401 }),
    );

    await expect(resolveAuthGate()).resolves.toBe("auth-required");
    expect(localStorage.getItem("qwenpaw_auth_token")).toBeNull();
  });

  it("fails closed and preserves the token on a service error", async () => {
    localStorage.setItem("qwenpaw_auth_token", "retry-token");
    getStatus.mockResolvedValueOnce({ enabled: true, has_users: true });
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(null, { status: 503 }),
    );

    await expect(resolveAuthGate()).rejects.toThrow(
      "Authentication service returned 503",
    );
    expect(localStorage.getItem("qwenpaw_auth_token")).toBe("retry-token");
  });

  it("preserves the token when verification cannot reach the backend", async () => {
    localStorage.setItem("qwenpaw_auth_token", "window-b-token");
    getStatus.mockResolvedValueOnce({ enabled: true, has_users: true });
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("offline"));

    await expect(resolveAuthGate()).rejects.toThrow("offline");
    expect(localStorage.getItem("qwenpaw_auth_token")).toBe("window-b-token");
  });
});
