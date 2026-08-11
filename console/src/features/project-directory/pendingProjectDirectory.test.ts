import { beforeEach, describe, expect, it } from "vitest";
import {
  getPendingProjectDirectory,
  getPendingProjectDirs,
  migratePendingProjectDirectory,
  setPendingProjectDirectory,
  withPendingProjectDirectory,
} from "./pendingProjectDirectory";

const KEY = "qwenpaw-session-project-dir:agent-a:session-a";

describe("pendingProjectDirectory", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("isolates project directories by agent and session", () => {
    setPendingProjectDirectory("agent-a", "session-a", [
      { path: "/project/a", label: null },
    ]);
    setPendingProjectDirectory("agent-a", "session-b", [
      { path: "/project/b", label: null },
    ]);
    setPendingProjectDirectory("agent-b", "session-a", [
      { path: "/project/c", label: null },
    ]);

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

  it("stores an ordered list and exposes the primary path", () => {
    setPendingProjectDirectory(
      "agent-a",
      "session-a",
      [
        { path: "/project/first", label: null },
        { path: "/project/second", label: "data" },
      ],
      "My project",
    );

    // The legacy getter returns only the primary path.
    expect(getPendingProjectDirectory("agent-a", "session-a")).toBe(
      "/project/first",
    );
    // The structured getter returns the whole list plus the name.
    expect(getPendingProjectDirs("agent-a", "session-a")).toEqual({
      dirs: [
        { path: "/project/first", label: null },
        { path: "/project/second", label: "data" },
      ],
      name: "My project",
    });
  });

  it("clears the pending value when given null or an empty list", () => {
    setPendingProjectDirectory("agent-a", "session-a", [
      { path: "/project/a", label: null },
    ]);
    setPendingProjectDirectory("agent-a", "session-a", null);
    expect(getPendingProjectDirs("agent-a", "session-a")).toBeNull();

    setPendingProjectDirectory("agent-a", "session-a", [
      { path: "/project/a", label: null },
    ]);
    setPendingProjectDirectory("agent-a", "session-a", []);
    expect(getPendingProjectDirs("agent-a", "session-a")).toBeNull();
  });

  it("reads a legacy plain-string value as a one-entry list", () => {
    // Values written before the list existed are a bare path string.
    sessionStorage.setItem(KEY, "/project/legacy");

    expect(getPendingProjectDirectory("agent-a", "session-a")).toBe(
      "/project/legacy",
    );
    expect(getPendingProjectDirs("agent-a", "session-a")).toEqual({
      dirs: [{ path: "/project/legacy", label: null }],
      name: null,
    });
  });

  it("migrates the full pending list with the session identity", () => {
    setPendingProjectDirectory(
      "agent-a",
      "new",
      [
        { path: "/project/a", label: null },
        { path: "/project/b", label: "extra" },
      ],
      "Name",
    );

    migratePendingProjectDirectory("agent-a", "new", "local-session");

    expect(getPendingProjectDirectory("agent-a", "new")).toBeNull();
    expect(getPendingProjectDirs("agent-a", "local-session")).toEqual({
      dirs: [
        { path: "/project/a", label: null },
        { path: "/project/b", label: "extra" },
      ],
      name: "Name",
    });
  });

  it("adds session_project_dirs and session_project_name to request context", () => {
    setPendingProjectDirectory(
      "agent-a",
      "session-a",
      [
        { path: "/project/a", label: null },
        { path: "/project/b", label: "data" },
      ],
      "My project",
    );

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
        session_project_dirs: [
          { path: "/project/a", label: null },
          { path: "/project/b", label: "data" },
        ],
        session_project_name: "My project",
      },
    });
    // The pending value is left in place; the caller clears it once sent.
    expect(getPendingProjectDirectory("agent-a", "session-a")).toBe(
      "/project/a",
    );
  });

  it("omits session_project_name when no name was set", () => {
    setPendingProjectDirectory("agent-a", "session-a", [
      { path: "/project/a", label: null },
    ]);

    const result = withPendingProjectDirectory({}, "agent-a", "session-a");

    expect(result.projectDir).toBe("/project/a");
    expect(result.requestBody).toEqual({
      request_context: {
        session_project_dirs: [{ path: "/project/a", label: null }],
      },
    });
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
