import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../config", () => ({
  clearAuthToken: vi.fn(),
  getApiToken: () => "hub-token",
  getApiUrl: (path: string) => `/api${path}`,
}));

import { hubApi } from "./hub";

function mockJsonResponse(body: unknown): void {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
  } as Response);
}

describe("hubApi pagination", () => {
  beforeEach(() => {
    localStorage.clear();
    mockJsonResponse({
      items: [],
      page: 1,
      page_size: 20,
      total: 0,
      pages: 1,
    });
  });

  afterEach(() => vi.clearAllMocks());

  it("serializes runtime pagination, search, and state filters", async () => {
    await hubApi.listRuntimes({
      page: 2,
      pageSize: 50,
      query: " failed runtime ",
      state: "failed",
      owner: "owner-a",
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/hub/runtimes?page=2&page_size=50&q=failed+runtime&state=failed&owner=owner-a",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer hub-token",
        }),
      }),
    );
  });

  it("serializes false user status filters", async () => {
    await hubApi.listUsers({ disabled: false });

    expect(fetch).toHaveBeenCalledWith(
      "/api/hub/admin/users?disabled=false",
      expect.anything(),
    );
  });

  it("uses paginated audit and credential endpoints", async () => {
    await hubApi.listCredentials({ page: 3, scope: "tenant" });
    await hubApi.listAuditEvents({ pageSize: 10, action: "runtime.start" });

    expect(fetch).toHaveBeenNthCalledWith(
      1,
      "/api/hub/credentials?page=3&scope=tenant",
      expect.anything(),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      "/api/hub/admin/audit?page_size=10&action=runtime.start",
      expect.anything(),
    );
  });

  it("changes the authenticated user's password without an old password", async () => {
    await hubApi.changePassword("new-safe-password");

    expect(fetch).toHaveBeenCalledWith(
      "/api/hub/me/password",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ new_password: "new-safe-password" }),
      }),
    );
  });

  it("restarts the authenticated user's runtime without a runtime id", async () => {
    await hubApi.restartOwnRuntime();

    expect(fetch).toHaveBeenCalledWith(
      "/api/hub/me/runtime/restart",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("uses a distinct endpoint for administrator disable", async () => {
    await hubApi.disableRuntime("personal-user-a");

    expect(fetch).toHaveBeenCalledWith(
      "/api/hub/runtimes/personal-user-a/disable",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("updates the complete Hub settings document with its revision", async () => {
    const config = {
      version: 1 as const,
      control_plane: {
        public_base_url: "https://hub.example.com",
        registration: { enabled: false, default_role: "user" as const },
      },
      runtime: {
        default_provisioner: "local",
        allowed_provisioners: ["local"],
      },
      tenant_defaults: {
        max_runtimes: 3,
        max_running_runtimes: 2,
      },
      tenants: {},
    };

    await hubApi.updateSettings(4, config);

    expect(fetch).toHaveBeenCalledWith(
      "/api/hub/admin/settings",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ revision: 4, config }),
      }),
    );
  });
});
