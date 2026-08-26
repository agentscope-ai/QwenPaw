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

  it("updates the complete Hub settings document with its revision", async () => {
    const config = {
      version: 1 as const,
      control_plane: {
        public_base_url: "https://hub.example.com",
        registration: { enabled: false, default_role: "user" as const },
        security: {
          ip_blacklist: [],
          trusted_proxy_ips: [],
          login_rate_limit: {
            enabled: true,
            max_attempts: 10,
            window_seconds: 300,
            block_seconds: 900,
          },
          registration_rate_limit: {
            enabled: true,
            max_attempts: 5,
            window_seconds: 3600,
            block_seconds: 3600,
          },
        },
        proxy: {
          max_request_size_mb: 1024,
          request_idle_timeout_seconds: 60,
          response_header_timeout_seconds: 300,
          connect_timeout_seconds: 10,
          websocket_max_message_size_mb: 16,
        },
      },
      runtime: {
        provisioner: "local" as const,
        docker: {
          source: "docker_hub" as const,
          image: "docker.io/agentscope/qwenpaw:latest",
          pull_policy: "if_not_present" as const,
          cpu_limit: 2,
          memory_limit_mb: 4096,
          pids_limit: 1024,
          shm_size_mb: 512,
        },
      },
      capacity: {
        max_running_runtimes: 2,
      },
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
