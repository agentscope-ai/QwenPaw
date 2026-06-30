import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { commandsApi } from "./commands";
import { request } from "../request";

// Silence console.log from sendApprovalCommand implementation.
vi.spyOn(console, "log").mockImplementation(() => {});

describe("commandsApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("checkCommand returns boolean is_control_command (true)", async () => {
    vi.mocked(request).mockResolvedValue({
      is_control_command: true,
      command_token: "/approve",
    });
    const result = await commandsApi.checkCommand("/approve");
    expect(request).toHaveBeenCalledWith("/commands/check", {
      method: "POST",
      body: JSON.stringify({ text: "/approve" }),
    });
    expect(result).toBe(true);
  });

  it("checkCommand returns false for non-control text", async () => {
    vi.mocked(request).mockResolvedValue({
      is_control_command: false,
      command_token: null,
    });
    const result = await commandsApi.checkCommand("hello there");
    expect(result).toBe(false);
  });

  it("sendApprovalCommand approve sends reason when provided", async () => {
    const resp = { success: true, message: "ok" };
    vi.mocked(request).mockResolvedValue(resp);
    const result = await commandsApi.sendApprovalCommand(
      "approve",
      "req-1",
      "sess-1",
      "looks good",
    );
    expect(request).toHaveBeenCalledWith("/approval/approve", {
      method: "POST",
      body: JSON.stringify({
        request_id: "req-1",
        session_id: "sess-1",
        reason: "looks good",
      }),
    });
    expect(result).toEqual(resp);
  });

  it("sendApprovalCommand deny omits reason (undefined)", async () => {
    const resp = { success: true, message: "denied" };
    vi.mocked(request).mockResolvedValue(resp);
    const result = await commandsApi.sendApprovalCommand(
      "deny",
      "req-2",
      "sess-2",
    );
    expect(request).toHaveBeenCalledWith("/approval/deny", {
      method: "POST",
      body: JSON.stringify({
        request_id: "req-2",
        session_id: "sess-2",
        reason: undefined,
      }),
    });
    expect(result).toEqual(resp);
  });
});
