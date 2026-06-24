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

    expect(request).toHaveBeenCalledWith("/mcp/policy/local_stdio_echo");
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
});
