import { describe, expect, it } from "vitest";
import { workspaceRoots } from "./directorySources";

describe("directorySources", () => {
  // `normalizeDirectoryPath` and `directoriesMatch` are gone: the client no
  // longer decides whether two paths name one directory. It could not — the
  // rule belongs to the filesystem, not to the platform the flag was derived
  // from — so the server answers it by inode and sends `is_workspace`. What
  // those two functions existed for is asserted below, through the behaviour
  // they fed.
  it("offers only the configuration root when both paths match", () => {
    expect(workspaceRoots([{ path: "/ws", is_workspace: true }])).toEqual([
      "workspace",
    ]);
    expect(workspaceRoots([{ path: "/repo", is_workspace: false }])).toEqual([
      "project",
      "workspace",
    ]);
  });

  it("does not give the workspace a second root of its own", () => {
    // One directory addressable two ways appeared twice in the switcher and
    // split its editor tabs. The path spellings deliberately differ in case
    // here: the client must take the server's word rather than compare them.
    expect(
      workspaceRoots([
        { path: "/srv/Repo", is_workspace: false },
        { path: "/srv/ws", is_workspace: true },
      ]),
    ).toEqual(["project", "workspace"]);
  });

  it("keeps two bound directories that differ only in case", () => {
    // A case-sensitive volume allows both. The old client-side fold reported
    // them as one root and dropped the second.
    expect(
      workspaceRoots([
        { path: "/srv/Repo", is_workspace: false },
        { path: "/srv/repo", is_workspace: false },
      ]),
    ).toEqual(["project", "project:/srv/repo", "workspace"]);
  });

  it("reports no roots until the directory list has been fetched", () => {
    expect(workspaceRoots([])).toEqual([]);
  });
});
