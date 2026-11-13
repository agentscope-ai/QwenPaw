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

  it("loads models through a provider-neutral route", async () => {
    await harnessApi.listModels("third-party");

    expect(request).toHaveBeenCalledWith("/harnesses/third-party/models", {
      timeout: 60_000,
    });
  });

  it("discovers Provider-owned MCP through a read-only route", async () => {
    await harnessApi.listMCP("third-party");

    expect(request).toHaveBeenCalledWith("/harnesses/third-party/mcp", {
      timeout: 60_000,
    });
  });

  it("discovers Provider-owned Skills through a read-only route", async () => {
    await harnessApi.listSkills("third-party");

    expect(request).toHaveBeenCalledWith("/harnesses/third-party/skills", {
      timeout: 60_000,
    });
  });
});
