/**
 * pendingProjectDirectory — branch coverage supplement: legacy storage
 * shapes (plain string / JSON-encoded string), entry normalisation and the
 * migrate/with-request guards that long-lived sessions depend on.
 */
import { beforeEach, describe, expect, it } from "vitest";
import {
  getPendingProjectDirectory,
  getPendingProjectDirs,
  migratePendingProjectDirectory,
  setPendingProjectDirectory,
  withPendingProjectDirectory,
} from "./pendingProjectDirectory";

const KEY = (agent: string, session: string) =>
  `qwenpaw-session-project-dir:${agent}:${session}`;

describe("pendingProjectDirectory branches", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("reads a multi-entry structured list in order", () => {
    setPendingProjectDirectory("a", "s", [
      { path: "/primary", label: "main" },
      { path: "/secondary", label: null },
    ]);
    const value = getPendingProjectDirs("a", "s");
    expect(value?.dirs).toEqual([
      { path: "/primary", label: "main" },
      { path: "/secondary", label: null },
    ]);
    // primary getter stays on index 0
    expect(getPendingProjectDirectory("a", "s")).toBe("/primary");
  });

  it("returns null for an empty sessionStorage value", () => {
    sessionStorage.setItem(KEY("a", "s"), "");
    expect(getPendingProjectDirs("a", "s")).toBeNull();
  });

  it("reads a legacy plain-string entry as a one-entry list", () => {
    sessionStorage.setItem(KEY("a", "s"), "/legacy/path");
    expect(getPendingProjectDirs("a", "s")).toEqual({
      dirs: [{ path: "/legacy/path", label: null }],
    });
    expect(getPendingProjectDirectory("a", "s")).toBe("/legacy/path");
  });

  it("reads a JSON-encoded string as a legacy path", () => {
    sessionStorage.setItem(KEY("a", "s"), JSON.stringify("/json/legacy"));
    expect(getPendingProjectDirectory("a", "s")).toBe("/json/legacy");
  });

  it("drops malformed entries and keeps valid ones", () => {
    sessionStorage.setItem(
      KEY("a", "s"),
      JSON.stringify({
        dirs: [
          { path: "/good", label: "g" },
          { path: 42 },
          { label: "no-path" },
          "not-an-object",
          { path: "" },
        ],
      }),
    );
    expect(getPendingProjectDirs("a", "s")).toEqual({
      dirs: [{ path: "/good", label: "g" }],
    });
  });

  it("returns null when every entry is malformed", () => {
    sessionStorage.setItem(KEY("a", "s"), JSON.stringify({ dirs: [{ x: 1 }] }));
    expect(getPendingProjectDirs("a", "s")).toBeNull();
  });

  it("returns null for valid JSON that is neither list nor string", () => {
    sessionStorage.setItem(KEY("a", "s"), JSON.stringify(42));
    expect(getPendingProjectDirs("a", "s")).toBeNull();
  });

  it("clears the entry when set with an empty list", () => {
    setPendingProjectDirectory("a", "s", [{ path: "/x", label: null }]);
    setPendingProjectDirectory("a", "s", []);
    expect(sessionStorage.getItem(KEY("a", "s"))).toBeNull();
  });

  it("migrate is a no-op when source and target are identical", () => {
    setPendingProjectDirectory("a", "s", [{ path: "/x", label: null }]);
    migratePendingProjectDirectory("a", "s", "s");
    expect(getPendingProjectDirectory("a", "s")).toBe("/x");
  });

  it("migrate is a no-op when the source has no pending value", () => {
    migratePendingProjectDirectory("a", "missing", "target");
    expect(getPendingProjectDirectory("a", "target")).toBeNull();
  });

  it("carries the whole ordered list into request context", () => {
    setPendingProjectDirectory("a", "s", [
      { path: "/primary", label: null },
      { path: "/secondary", label: "extra" },
    ]);
    const { requestBody, projectDir } = withPendingProjectDirectory(
      { stream: true },
      "a",
      "s",
    );
    expect(projectDir).toBe("/primary");
    expect(requestBody).toEqual({
      stream: true,
      request_context: {
        session_project_dirs: [
          { path: "/primary", label: null },
          { path: "/secondary", label: "extra" },
        ],
      },
    });
  });
});
