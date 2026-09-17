import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { request } from "../request";
import { harnessApi } from "./harness";

describe("harnessApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("loads the provider catalog with a startup timeout", async () => {
    await harnessApi.list();

    expect(request).toHaveBeenCalledWith("/harnesses", {
      timeout: 60_000,
    });
  });

  it("starts Codex OAuth without exposing credentials", async () => {
    await harnessApi.login("codex", false, {
      binary: "/Applications/ChatGPT.app/Contents/Resources/codex",
    });

    expect(request).toHaveBeenCalledWith("/harnesses/codex/login", {
      method: "POST",
      body: JSON.stringify({
        device_code: false,
        settings: {
          binary: "/Applications/ChatGPT.app/Contents/Resources/codex",
        },
      }),
      timeout: 60_000,
    });
  });

  it("logs Codex out through the harness API", async () => {
    await harnessApi.logout("codex");

    expect(request).toHaveBeenCalledWith("/harnesses/codex/logout", {
      method: "POST",
      body: JSON.stringify({ settings: {} }),
    });
  });

  it("probes Codex with unsaved binary settings", async () => {
    await harnessApi.status("codex", { binary: "/custom/codex" });

    expect(request).toHaveBeenCalledWith("/harnesses/codex/status", {
      method: "POST",
      body: JSON.stringify({
        settings: { binary: "/custom/codex" },
      }),
      timeout: 60_000,
    });
  });

  it("loads models through a provider-neutral route", async () => {
    await harnessApi.listModels("codex");

    expect(request).toHaveBeenCalledWith("/harnesses/codex/models", {
      timeout: 60_000,
    });
  });

  it("discovers Provider-owned MCP through a read-only route", async () => {
    await harnessApi.listMCP("codex");

    expect(request).toHaveBeenCalledWith("/harnesses/codex/mcp", {
      timeout: 60_000,
    });
  });

  it("discovers Provider-owned Skills through a read-only route", async () => {
    await harnessApi.listSkills("qoder");

    expect(request).toHaveBeenCalledWith("/harnesses/qoder/skills", {
      timeout: 60_000,
    });
  });
});
