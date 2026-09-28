import { beforeEach, describe, expect, it, vi } from "vitest";
import { terminalApi } from "./terminalApi";
import { request } from "../../api/request";
import { setPendingProjectDirectory } from "../project-directory/pendingProjectDirectory";

vi.mock("../../api/request", () => ({
  request: vi.fn().mockResolvedValue({}),
}));

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
});

describe("terminal request scope", () => {
  it("resolves a changed new-chat directory at creation time", async () => {
    const api = terminalApi(
      { kind: "session", agentId: "a", sessionId: "new" },
      "group",
    );
    setPendingProjectDirectory("a", "new", [
      { path: "/chosen-later", label: null },
    ]);
    await api.create();
    expect(request).toHaveBeenCalledWith(
      "/terminals/group",
      expect.objectContaining({
        headers: {
          "X-Agent-Id": "a",
          "X-Session-Project-Dir": "/chosen-later",
        },
      }),
    );
  });

  it("uses the server chat directory for a saved conversation", async () => {
    const api = terminalApi(
      { kind: "session", agentId: "a", sessionId: "chat", chatId: "real" },
      "group",
    );
    await api.create();
    expect(request).toHaveBeenCalledWith(
      "/terminals/group",
      expect.objectContaining({
        headers: { "X-Agent-Id": "a", "X-Chat-Id": "real" },
      }),
    );
  });

  it("does not create a terminal in a fallback directory while loading a chat", async () => {
    const api = terminalApi(
      { kind: "session", agentId: "a", sessionId: "loading" },
      "group",
    );
    await expect(api.create()).rejects.toThrow("loading");
    expect(request).not.toHaveBeenCalled();
  });
});
