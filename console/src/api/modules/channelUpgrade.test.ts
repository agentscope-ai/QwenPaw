import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../config", () => ({
  getApiUrl: (path: string) => `http://channels.test/api${path}`,
  clearAuthToken: vi.fn(),
}));
vi.mock("../authHeaders", () => ({
  buildAuthHeaders: () => ({
    Authorization: "Bearer fixture",
    "X-Agent-Id": "channels-agent",
  }),
}));

import { channelApi } from "./channel";

const operation = {
  id: "channel-review",
  plugin_id: "matrix",
  status: "needs_confirmation",
  changes: [
    {
      name: "markdown-it-py",
      current_version: "2.2.0",
      target_version: "3.0.0",
    },
  ],
  affected_instances: [],
  requires_restart: false,
  message: "Review replacement",
  error: null,
  retryable: true,
};

afterEach(() => vi.unstubAllGlobals());

describe("channel dependency repair transport", () => {
  it.each(["install", "repair"] as const)(
    "retains structured upgrade review from channel %s",
    async (action) => {
      const fetcher = vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: {
              code: "DEPENDENCY_UPGRADE_REQUIRED",
              message: "Review replacement",
              operation,
            },
          }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
      );
      vi.stubGlobal("fetch", fetcher);
      await expect(
        channelApi.repairChannel({
          action,
          plugin_id: "matrix/channel",
          source: "/retained/matrix",
        }),
      ).rejects.toMatchObject({
        status: 409,
        code: "DEPENDENCY_UPGRADE_REQUIRED",
        operation,
      });
      const [url, options] = fetcher.mock.calls[0] as [string, RequestInit];
      expect(url).toBe(
        `http://channels.test/api/plugins/${
          action === "install"
            ? "install"
            : "matrix%2Fchannel/repair-dependencies"
        }`,
      );
      expect(options.method).toBe("POST");
      const headers = new Headers(options.headers);
      expect(headers.get("Authorization")).toBe("Bearer fixture");
      expect(headers.get("X-Agent-Id")).toBe("channels-agent");
      if (action === "install")
        expect(JSON.parse(options.body as string).source).toBe(
          "/retained/matrix",
        );
    },
  );

  it("keeps ordinary dependency repair success data intact", async () => {
    const repaired = {
      id: "matrix",
      status: "inactive",
      enabled: false,
      diagnostics: [],
      message: "Repaired",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(repaired), {
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    await expect(
      channelApi.repairChannel({ action: "repair", plugin_id: "matrix" }),
    ).resolves.toEqual(repaired);
  });
});
