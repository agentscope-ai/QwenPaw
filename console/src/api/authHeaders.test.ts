import { beforeEach, describe, expect, it } from "vitest";
import { buildAuthHeaders } from "./authHeaders";

describe("buildAuthHeaders identity-scoped agent selection", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it("reads the selected agent only from the authenticated user's namespace", () => {
    localStorage.setItem("qwenpaw_authenticated_user_id", "user-b");
    localStorage.setItem(
      "qwenpaw-agent-storage:user:user-a",
      JSON.stringify({ state: { selectedAgent: "agent-a" } }),
    );
    sessionStorage.setItem(
      "qwenpaw-agent-storage:user:user-b",
      JSON.stringify({ state: { selectedAgent: "agent-b" } }),
    );

    expect(buildAuthHeaders()["X-Agent-Id"]).toBe("agent-b");
  });
});
