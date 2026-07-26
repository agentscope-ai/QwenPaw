/**
 * Tests for api/modules/tools.ts
 *
 * Contract-guard style: verify return pass-through and URL-encoding of
 * tool names.  `ToolInfo` post-toggle / post-update responses are
 * echoed back so the UI can refresh; we verify that contract.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { toolsApi } from "./tools";
import { request } from "../request";

describe("toolsApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("listTools resolves to a ToolInfo[]", async () => {
    const tools = [
      {
        name: "web_search",
        enabled: true,
        description: "search the web",
        async_execution: false,
        icon: "search",
      },
    ];
    vi.mocked(request).mockResolvedValue(tools);
    const result = await toolsApi.listTools();
    expect(result).toEqual(tools);
  });

  it("toggleTool returns the updated ToolInfo with the new enabled state", async () => {
    const updated = {
      name: "calc",
      enabled: false,
      description: "",
      async_execution: false,
      icon: "calc",
    };
    vi.mocked(request).mockResolvedValue(updated);
    const r = await toolsApi.toggleTool("calc");
    expect(r).toEqual(updated);
  });

  it("updateAsyncExecution returns the updated ToolInfo", async () => {
    const updated = {
      name: "calc",
      enabled: true,
      description: "",
      async_execution: true,
      icon: "calc",
    };
    vi.mocked(request).mockResolvedValue(updated);
    const r = await toolsApi.updateAsyncExecution("calc", true);
    expect(r).toEqual(updated);
    // ensure request was actually invoked once (not short-circuited)
    expect(request).toHaveBeenCalledTimes(1);
  });

  it("getToolConfig returns the tool's current config values", async () => {
    const cfg = { api_key: "k", timeout: 30 };
    vi.mocked(request).mockResolvedValue(cfg);
    const r = await toolsApi.getToolConfig("web_search");
    expect(r).toBe(cfg);
  });

  it("updateToolConfig returns { status, message } on success", async () => {
    vi.mocked(request).mockResolvedValue({
      status: "ok",
      message: "saved",
    });
    await expect(
      toolsApi.updateToolConfig("web_search", { api_key: "k" }),
    ).resolves.toEqual({ status: "ok", message: "saved" });
  });

  it("encodes a tool name containing a slash when toggling", async () => {
    vi.mocked(request).mockResolvedValue({
      name: "ns/tool",
      enabled: true,
      description: "",
      async_execution: false,
      icon: "",
    });
    await toolsApi.toggleTool("ns/tool");
    const arg = vi.mocked(request).mock.calls[0][0] as string;
    expect(arg).toContain("ns%2Ftool");
  });

  it("propagates request errors for listTools", async () => {
    vi.mocked(request).mockRejectedValue(new Error("500"));
    await expect(toolsApi.listTools()).rejects.toThrow("500");
  });
});
