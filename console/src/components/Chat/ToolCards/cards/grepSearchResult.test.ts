import { describe, expect, it } from "vitest";
import {
  displayPartsForGrepPath,
  groupGrepFileHits,
  hasOpenableGrepPaths,
  parseGrepResultLines,
  parseGrepResultLinesForOpen,
  resolveGrepOpenPath,
  resolveGrepSearchRoot,
  toOpenableFileTarget,
} from "./grepSearchResult";

describe("toOpenableFileTarget", () => {
  it("accepts relative project paths with a line", () => {
    expect(toOpenableFileTarget("src/main.py", 12)).toEqual({
      source: "workspace",
      path: "src/main.py",
      root: "project",
      line: 12,
      endLine: 12,
    });
  });

  it("rejects absolute and parent paths", () => {
    expect(toOpenableFileTarget("/tmp/main.py", 1)).toBeNull();
    expect(toOpenableFileTarget("../secret.py", 1)).toBeNull();
  });

  it("resolves single-file search basename via params.path", () => {
    expect(
      toOpenableFileTarget("foo.py", 12, { searchPath: "src/foo.py" }),
    ).toMatchObject({ path: "src/foo.py", line: 12 });
  });

  it("joins directory search roots with display paths", () => {
    expect(
      toOpenableFileTarget("util.py", 3, { searchPath: "src" }),
    ).toMatchObject({ path: "src/util.py", line: 3 });
  });

  it("maps absolute params.path through projectDirectory", () => {
    expect(
      toOpenableFileTarget("foo.py", 2, {
        searchPath: "/Users/demo/project/src/foo.py",
        projectDirectory: "/Users/demo/project",
      }),
    ).toMatchObject({ path: "src/foo.py", line: 2 });
  });

  it("returns null when absolute params.path is outside the project", () => {
    expect(
      toOpenableFileTarget("foo.py", 2, {
        searchPath: "/Users/demo/other/foo.py",
        projectDirectory: "/Users/demo/project",
      }),
    ).toBeNull();
  });
});

describe("resolveGrepSearchRoot / resolveGrepOpenPath", () => {
  it("leaves omitted search path unresolved", () => {
    expect(resolveGrepSearchRoot(undefined)).toBeUndefined();
    expect(resolveGrepOpenPath("src/main.py", undefined)).toBe("src/main.py");
  });

  it("normalizes ./ and trailing slashes on search roots", () => {
    expect(resolveGrepSearchRoot("./src/")).toBe("src");
    expect(resolveGrepOpenPath("main.py", "src")).toBe("src/main.py");
  });

  it("does not double-join when display already includes the root", () => {
    expect(resolveGrepOpenPath("src/main.py", "src")).toBe("src/main.py");
  });
});

describe("parseGrepResultLines", () => {
  it("parses show_file=True match lines", () => {
    const lines = parseGrepResultLines(
      "src/main.py:12:> def main():\nsrc/main.py:13:  pass",
    );
    expect(lines).toEqual([
      {
        kind: "match",
        path: "src/main.py",
        line: 12,
        hit: true,
        content: "def main():",
        raw: "src/main.py:12:> def main():",
      },
      {
        kind: "match",
        path: "src/main.py",
        line: 13,
        hit: false,
        content: "pass",
        raw: "src/main.py:13:  pass",
      },
    ]);
    expect(hasOpenableGrepPaths(lines)).toBe(true);
  });

  it("parses show_file=False grouped results", () => {
    const lines = parseGrepResultLines(
      ["a.txt", "1:> match_a", "---", "b.txt", "1:> match_b"].join("\n"),
    );
    expect(lines).toEqual([
      { kind: "file_header", path: "a.txt", raw: "a.txt" },
      {
        kind: "match_no_path",
        path: "a.txt",
        line: 1,
        hit: true,
        content: "match_a",
        raw: "1:> match_a",
      },
      { kind: "separator", raw: "---" },
      { kind: "file_header", path: "b.txt", raw: "b.txt" },
      {
        kind: "match_no_path",
        path: "b.txt",
        line: 1,
        hit: true,
        content: "match_b",
        raw: "1:> match_b",
      },
    ]);
  });

  it("uses fallbackPath for single-file show_file=False output", () => {
    const lines = parseGrepResultLines("2:> line two", {
      fallbackPath: "src/foo.py",
    });
    expect(lines).toEqual([
      {
        kind: "match_no_path",
        path: "src/foo.py",
        line: 2,
        hit: true,
        content: "line two",
        raw: "2:> line two",
      },
    ]);
    expect(hasOpenableGrepPaths(lines)).toBe(true);
  });

  it("keeps status footers as plain text", () => {
    const lines = parseGrepResultLines(
      "src/app.py:1:> hi\n\n(Results truncated due to size.)",
    );
    expect(lines[0]).toMatchObject({ kind: "match", path: "src/app.py" });
    expect(lines[1]).toEqual({ kind: "text", raw: "" });
    expect(lines[2]).toEqual({
      kind: "text",
      raw: "(Results truncated due to size.)",
    });
  });

  it("does not treat empty results as linkable", () => {
    const lines = parseGrepResultLines("No matches found for pattern: foo");
    expect(hasOpenableGrepPaths(lines)).toBe(false);
  });
});

describe("parseGrepResultLinesForOpen", () => {
  it("keeps default-root project-relative paths", () => {
    const lines = parseGrepResultLinesForOpen(
      "src/main.py:12:> def main():",
      {},
    );
    expect(lines[0]).toMatchObject({
      kind: "match",
      path: "src/main.py",
      line: 12,
    });
    expect(
      toOpenableFileTarget((lines[0] as { path: string }).path, 12),
    ).toMatchObject({ path: "src/main.py" });
  });

  it("rewrites single-file basename display paths", () => {
    const lines = parseGrepResultLinesForOpen("foo.py:12:> hit", {
      searchPath: "src/foo.py",
    });
    expect(lines[0]).toMatchObject({ path: "src/foo.py", line: 12 });
  });

  it("rewrites directory-relative display paths", () => {
    const lines = parseGrepResultLinesForOpen("util.py:3:> helper", {
      searchPath: "src",
    });
    expect(lines[0]).toMatchObject({ path: "src/util.py", line: 3 });
  });

  it("opens single-file show_file=False via params.path", () => {
    const lines = parseGrepResultLinesForOpen("2:> line two", {
      searchPath: "src/foo.py",
    });
    expect(hasOpenableGrepPaths(lines)).toBe(true);
    expect(lines[0]).toMatchObject({
      kind: "match_no_path",
      path: "src/foo.py",
      line: 2,
    });
    expect(groupGrepFileHits(lines)).toEqual([
      {
        path: "src/foo.py",
        line: 2,
        hitCount: 1,
        matches: [{ line: 2, content: "line two" }],
      },
    ]);
  });

  it("rewrites show_file=False directory headers under params.path", () => {
    const lines = parseGrepResultLinesForOpen(
      ["util.py", "3:> helper", "---", "pkg/a.py", "1:> a"].join("\n"),
      { searchPath: "src" },
    );
    expect(groupGrepFileHits(lines).map((hit) => hit.path)).toEqual([
      "src/util.py",
      "src/pkg/a.py",
    ]);
  });

  it("drops openable paths when absolute searchPath cannot be mapped", () => {
    const lines = parseGrepResultLinesForOpen("foo.py:2:> hit", {
      searchPath: "/Users/demo/other/foo.py",
      projectDirectory: "/Users/demo/project",
    });
    expect(hasOpenableGrepPaths(lines)).toBe(false);
  });
});

describe("groupGrepFileHits", () => {
  it("collapses matches to one row per file with first hit line", () => {
    const lines = parseGrepResultLines(
      [
        "src/main.py:12:> def main():",
        "src/main.py:13:  pass",
        "src/util.py:3:> def main_helper():",
      ].join("\n"),
    );
    expect(groupGrepFileHits(lines)).toEqual([
      {
        path: "src/main.py",
        line: 12,
        hitCount: 1,
        matches: [{ line: 12, content: "def main():" }],
      },
      {
        path: "src/util.py",
        line: 3,
        hitCount: 1,
        matches: [{ line: 3, content: "def main_helper():" }],
      },
    ]);
  });

  it("keeps multiple hit lines under the same file for expand", () => {
    const lines = parseGrepResultLines(
      [
        "src/main.py:12:> def main():",
        "src/main.py:40:> def main_helper():",
      ].join("\n"),
    );
    expect(groupGrepFileHits(lines)).toEqual([
      {
        path: "src/main.py",
        line: 12,
        hitCount: 2,
        matches: [
          { line: 12, content: "def main():" },
          { line: 40, content: "def main_helper():" },
        ],
      },
    ]);
  });

  it("groups show_file=False headers and match lines", () => {
    const lines = parseGrepResultLines(
      [
        "pkg/a.txt",
        "1:> match_a",
        "2:> match_a2",
        "---",
        "pkg/b.txt",
        "1:> match_b",
      ].join("\n"),
    );
    expect(groupGrepFileHits(lines)).toEqual([
      {
        path: "pkg/a.txt",
        line: 1,
        hitCount: 2,
        matches: [
          { line: 1, content: "match_a" },
          { line: 2, content: "match_a2" },
        ],
      },
      {
        path: "pkg/b.txt",
        line: 1,
        hitCount: 1,
        matches: [{ line: 1, content: "match_b" }],
      },
    ]);
  });
});

describe("displayPartsForGrepPath", () => {
  it("splits basename and directory", () => {
    expect(displayPartsForGrepPath("hello_omp/hello_omp/__main__.py")).toEqual({
      name: "__main__.py",
      directory: "hello_omp/hello_omp",
    });
    expect(displayPartsForGrepPath("readme.md")).toEqual({
      name: "readme.md",
      directory: "",
    });
  });
});
