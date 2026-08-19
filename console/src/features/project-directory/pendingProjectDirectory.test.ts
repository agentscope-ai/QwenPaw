import { beforeEach, describe, expect, it } from "vitest";
import {
  getPendingProjectDirectory,
  migratePendingProjectDirectory,
  setPendingProjectDirectory,
  withPendingProjectDirectory,
} from "./pendingProjectDirectory";

describe("pendingProjectDirectory", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("isolates project directories by agent and session", () => {
    setPendingProjectDirectory("agent-a", "session-a", "/project/a");
    setPendingProjectDirectory("agent-a", "session-b", "/project/b");
    setPendingProjectDirectory("agent-b", "session-a", "/project/c");

    expect(getPendingProjectDirectory("agent-a", "session-a")).toBe(
      "/project/a",
    );
    expect(getPendingProjectDirectory("agent-a", "session-b")).toBe(
      "/project/b",
    );
    expect(getPendingProjectDirectory("agent-b", "session-a")).toBe(
      "/project/c",
    );
  });

  it("migrates a pending directory with the session identity", () => {
    setPendingProjectDirectory("agent-a", "new", "/project/a");

    migratePendingProjectDirectory("agent-a", "new", "local-session");

    expect(getPendingProjectDirectory("agent-a", "new")).toBeNull();
    expect(getPendingProjectDirectory("agent-a", "local-session")).toBe(
      "/project/a",
    );
  });

  it("adds the canonical session project snapshot to request context", () => {
    setPendingProjectDirectory("agent-a", "session-a", "/project/a");

    const result = withPendingProjectDirectory(
      {
        request_context: {
          approval_level: "confirm",
        },
      },
      "agent-a",
      "session-a",
    );

    expect(result.projectDir).toBe("/project/a");
    expect(result.requestBody).toEqual({
      request_context: {
        approval_level: "confirm",
        session_project_dir: "/project/a",
      },
    });
    expect(getPendingProjectDirectory("agent-a", "session-a")).toBe(
      "/project/a",
    );
  });

  it("leaves the request unchanged when the session has no selection", () => {
    const requestBody = { stream: true };

    const result = withPendingProjectDirectory(
      requestBody,
      "agent-a",
      "session-a",
    );

    expect(result).toEqual({ requestBody, projectDir: null });
  });
});
