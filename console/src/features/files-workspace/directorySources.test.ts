import { afterEach, describe, expect, it } from "vitest";
import {
  directoriesMatch,
  normalizeDirectoryPath,
  workspaceRoots,
} from "./directorySources";
import { setPathCaseInsensitive } from "../project-directory/pathEquivalence";

describe("directorySources", () => {
  // The flag is module-level state adopted from the server response, so
  // every case-sensitivity test has to put it back.
  afterEach(() => setPathCaseInsensitive(false));

  it("normalizes separators and trailing slashes", () => {
    expect(normalizeDirectoryPath("/repo/qwenpaw/")).toBe("/repo/qwenpaw");
    expect(normalizeDirectoryPath("C:\\Repo\\QwenPaw\\")).toBe(
      "C:/Repo/QwenPaw",
    );
  });

  it("keeps a UNC prefix while stripping trailing separators", () => {
    expect(normalizeDirectoryPath("\\\\server\\share\\repo\\")).toBe(
      "//server/share/repo",
    );
  });

  it("folds case only when the server says the filesystem does", () => {
    // Default is case-sensitive: two directories that a case-sensitive
    // server really does distinguish must not collapse into one root.
    expect(directoriesMatch("/srv/Repo", "/srv/repo")).toBe(false);
    setPathCaseInsensitive(true);
    expect(directoriesMatch("/srv/Repo", "/srv/repo")).toBe(true);
  });

  it("compares Windows paths case-insensitively when the server folds", () => {
    setPathCaseInsensitive(true);
    expect(directoriesMatch("C:\\Repo\\QwenPaw", "c:/repo/qwenpaw/")).toBe(
      true,
    );
    // The old local rule folded drive letters only, so one UNC share showed
    // up as two roots and split its editor tabs.
    expect(
      directoriesMatch("\\\\SERVER\\Share\\Repo", "//server/share/repo"),
    ).toBe(true);
  });

  it("offers only the configuration root when both paths match", () => {
    expect(workspaceRoots([{ path: "/ws" }], "/ws")).toEqual(["workspace"]);
    expect(workspaceRoots([{ path: "/repo" }], "/ws")).toEqual([
      "project",
      "workspace",
    ]);
  });
});
