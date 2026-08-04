import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { request } from "../request";
import { toolCallsApi } from "./toolCalls";

describe("toolCallsApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockReset();
    vi.mocked(request).mockResolvedValue({ status: "ok" });
  });

  it("preventOffload posts no_deadline for offload target", async () => {
    await toolCallsApi.preventOffload("sid-1", "tc-1");
    expect(request).toHaveBeenCalledWith(
      "/tool-calls/sid-1/tc-1/extend-deadline",
      {
        method: "POST",
        body: JSON.stringify({ target: "offload", no_deadline: true }),
      },
    );
  });

  it("extendOffload posts target=offload with seconds", async () => {
    await toolCallsApi.extendOffload("sid-1", "tc-1", 30);
    expect(request).toHaveBeenCalledWith(
      "/tool-calls/sid-1/tc-1/extend-deadline",
      {
        method: "POST",
        body: JSON.stringify({ target: "offload", seconds: 30 }),
      },
    );
  });

  it("extendKill posts target=kill with seconds", async () => {
    await toolCallsApi.extendKill("sid-1", "tc-1", 45);
    expect(request).toHaveBeenCalledWith(
      "/tool-calls/sid-1/tc-1/extend-deadline",
      {
        method: "POST",
        body: JSON.stringify({ target: "kill", seconds: 45 }),
      },
    );
  });

  it("getInfo and cancel use session-scoped paths", async () => {
    await toolCallsApi.getInfo("backend-sid", "tc-9");
    expect(request).toHaveBeenCalledWith("/tool-calls/backend-sid/tc-9");

    await toolCallsApi.cancel("backend-sid", "tc-9");
    expect(request).toHaveBeenCalledWith(
      "/tool-calls/backend-sid/tc-9/cancel",
      { method: "POST" },
    );
  });
});
