import { describe, expect, it, vi, afterEach } from "vitest";
import { mcpApi } from "./mcp";
import { request } from "../request";

vi.mock("../request", () => ({ request: vi.fn() }));

describe("mcpApi policy endpoints", () => {
  afterEach(() => vi.clearAllMocks());

  it("gets MCP policy from the policy endpoint", async () => {
    vi.mocked(request).mockResolvedValue({
      default_effect: "ask",
      client_overrides: [],
      tool_defaults: [],
      tool_overrides: [],
      unmanaged_rules_count: 0,
    });

    await mcpApi.getMCPPolicy("local_stdio_echo");

    expect(request).toHaveBeenCalledWith(
      "/mcp/policy/local_stdio_echo",
      undefined,
    );
  });

  it("updates MCP policy through the policy endpoint", async () => {
    vi.mocked(request).mockResolvedValue({
      default_effect: "ask",
      client_overrides: [],
      tool_defaults: [],
      tool_overrides: [],
      unmanaged_rules_count: 0,
    });

    await mcpApi.updateMCPPolicy("local_stdio_echo", {
      default_effect: "ask",
      client_overrides: [
        {
          source_type: "channel",
          source_value: "console",
          subject_type: "all",
          subject_value: "",
          effect: "allow",
        },
      ],
      tool_defaults: [{ tool_name: "echo", effect: "ask" }],
      tool_overrides: [
        {
          tool_name: "echo",
          source_type: "channel",
          source_value: "dingtalk",
          subject_type: "user",
          subject_value: "alice",
          effect: "allow",
        },
      ],
      unmanaged_rules_count: 0,
    });

    expect(request).toHaveBeenCalledWith("/mcp/policy/local_stdio_echo", {
      method: "PUT",
      body: JSON.stringify({
        default_effect: "ask",
        client_overrides: [
          {
            source_type: "channel",
            source_value: "console",
            subject_type: "all",
            subject_value: "",
            effect: "allow",
          },
        ],
        tool_defaults: [{ tool_name: "echo", effect: "ask" }],
        tool_overrides: [
          {
            tool_name: "echo",
            source_type: "channel",
            source_value: "dingtalk",
            subject_type: "user",
            subject_value: "alice",
            effect: "allow",
          },
        ],
        unmanaged_rules_count: 0,
      }),
    });
  });

  it("sends optimistic revisions for mutations", async () => {
    vi.mocked(request).mockResolvedValue({});

    await mcpApi.toggleMCPClient("client/key", 7, { agentId: "agent-a" });
    await mcpApi.deleteMCPClient("client/key", 8, { agentId: "agent-a" });
    await mcpApi.updateMCPToolWhitelist("client/key", null, 9, {
      agentId: "agent-a",
    });

    expect(request).toHaveBeenNthCalledWith(
      1,
      "/mcp/toggle/client%2Fkey?expected_revision=7",
      expect.objectContaining({
        method: "PATCH",
        headers: expect.objectContaining({ "X-Agent-Id": "agent-a" }),
      }),
    );
    expect(request).toHaveBeenNthCalledWith(
      2,
      "/mcp/client%2Fkey?expected_revision=8",
      expect.objectContaining({
        method: "DELETE",
        headers: expect.objectContaining({ "X-Agent-Id": "agent-a" }),
      }),
    );
    expect(request).toHaveBeenNthCalledWith(
      3,
      "/mcp/tools/client%2Fkey",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ tools: null, expected_revision: 9 }),
      }),
    );
  });

  it("preserves explicit credential actions on update", async () => {
    vi.mocked(request).mockResolvedValue({});
    const body = {
      expected_revision: 4,
      credential_updates: {
        headers: {
          Authorization: { action: "keep" as const },
          "X-Key": { action: "replace" as const, value: "new-secret" },
        },
        env: { OLD_TOKEN: { action: "delete" as const } },
      },
    };

    await mcpApi.updateMCPClient("remote", body, { agentId: "agent-a" });

    expect(request).toHaveBeenCalledWith(
      "/mcp/remote",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify(body),
        headers: expect.objectContaining({ "X-Agent-Id": "agent-a" }),
      }),
    );
  });

  it("correlates OAuth status and revision-changing actions", async () => {
    vi.mocked(request).mockResolvedValue({});
    await mcpApi.startOAuth("remote", { url: "https://mcp", expected_revision: 4 });
    await mcpApi.getOAuthStatus("remote", "session-1");
    await mcpApi.revokeOAuth("remote", 4);
    expect(request).toHaveBeenNthCalledWith(
      2,
      "/mcp/oauth/status/remote?session_id=session-1",
      undefined,
    );
    expect(request).toHaveBeenNthCalledWith(
      3,
      "/mcp/oauth/remote?expected_revision=4",
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});
