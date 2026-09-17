import { describe, expect, it } from "vitest";
import type { DirectoryEntry } from "./types";
import { buildDailyMemoryTree, buildMemoryTree } from "./memoryTree";

function file(
  path: string,
  modifiedAt = "2026-01-01T00:00:00Z",
): DirectoryEntry {
  return {
    name: path.split("/").pop() ?? path,
    path,
    kind: "file",
    size: 1,
    modified_at: modifiedAt,
    preview_kind: "text",
  };
}

describe("buildMemoryTree", () => {
  it("builds nested directories and keeps only markdown files", () => {
    const tree = buildMemoryTree([
      file("2026/08/05.md"),
      file("root.md"),
      file("2026/08/ignored.txt"),
    ]);

    expect(tree.map((entry) => entry.name)).toEqual(["2026", "root.md"]);
    expect(tree[0].children?.[0].children?.map((entry) => entry.name)).toEqual([
      "05.md",
    ]);
  });

  it("sorts siblings by their latest descendant modification time", () => {
    const tree = buildMemoryTree([
      file("older/nested.md", "2026-01-02T00:00:00Z"),
      file("latest.md", "2026-01-05T00:00:00Z"),
      file("newer/old.md", "2026-01-01T00:00:00Z"),
      file("newer/new.md", "2026-01-04T00:00:00Z"),
    ]);

    expect(tree.map((entry) => entry.name)).toEqual([
      "latest.md",
      "newer",
      "older",
    ]);
    expect(tree[1].modified_at).toBe("2026-01-04T00:00:00Z");
    expect(tree[1].children?.map((entry) => entry.name)).toEqual([
      "new.md",
      "old.md",
    ]);
  });

  it("uses directory-first natural name ordering when times match", () => {
    const tree = buildMemoryTree([
      file("10/z.md"),
      file("2/a.md"),
      file("b.md"),
      file("a.md"),
    ]);

    expect(tree.map((entry) => entry.name)).toEqual([
      "2",
      "10",
      "a.md",
      "b.md",
    ]);
  });
});

describe("buildDailyMemoryTree", () => {
  it("groups a daily root file with notes in its matching date directory", () => {
    const tree = buildDailyMemoryTree([
      file("2026-08-10/today.md", "2026-08-10T08:00:00Z"),
      file("2026-08-10.md", "2026-08-10T09:00:00Z"),
      file("2026-08-09/session.md", "2026-08-11T08:00:00Z"),
      file("2026-08-09.md", "2026-08-09T09:00:00Z"),
    ]);

    expect(tree.map((entry) => entry.name)).toEqual([
      "2026-08-10",
      "2026-08-09",
    ]);
    expect(tree[0].children?.map((entry) => entry.path)).toEqual([
      "2026-08-10.md",
      "2026-08-10/today.md",
    ]);
    expect(tree[1].children?.map((entry) => entry.path)).toEqual([
      "2026-08-09.md",
      "2026-08-09/session.md",
    ]);
  });

  it("sorts date entries by their path date instead of modification time", () => {
    const tree = buildDailyMemoryTree([
      file("2026-08-08.md", "2026-08-12T00:00:00Z"),
      file("2026-08-10.md", "2026-08-10T00:00:00Z"),
      file("2026-08-09/note.md", "2026-08-11T00:00:00Z"),
    ]);

    expect(tree.map((entry) => entry.name)).toEqual([
      "2026-08-10.md",
      "2026-08-09",
      "2026-08-08.md",
    ]);
  });

  it("keeps non-date memory paths in the tree", () => {
    const tree = buildDailyMemoryTree([
      file("2026-08-10.md"),
      file("notes/topic.md"),
    ]);

    expect(tree.map((entry) => entry.name)).toEqual(["2026-08-10.md", "notes"]);
  });
});
