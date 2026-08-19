import { describe, expect, it } from "vitest";
import {
  directoriesMatch,
  normalizeDirectoryPath,
  workspaceRoots,
} from "./directorySources";

describe("directorySources", () => {
  it("normalizes separators and trailing slashes", () => {
    expect(normalizeDirectoryPath("/repo/qwenpaw/")).toBe("/repo/qwenpaw");
    expect(normalizeDirectoryPath("C:\\Repo\\QwenPaw\\")).toBe(
      "c:/repo/qwenpaw",
    );
  });

  it("compares Windows paths without case sensitivity", () => {
    expect(directoriesMatch("C:\\Repo\\QwenPaw", "c:/repo/qwenpaw/")).toBe(
      true,
    );
  });

  it("offers only the configuration root when both paths match", () => {
    expect(workspaceRoots(true)).toEqual(["workspace"]);
    expect(workspaceRoots(false)).toEqual(["project", "workspace"]);
  });
});
