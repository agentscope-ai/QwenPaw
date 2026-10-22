/**
 * utils.helpers.test.ts - file/language helpers and tool-result parsing paths.
 *
 * Complements utils.test.ts (which pins shortFileName, getMediaInfo,
 * extractUrlFromText "saved to" patterns, formatMemorySearch happy paths and
 * formatAgentList rows) and utils.toDisplayUrl.test.ts. This file covers the
 * exports and branches those two leave out:
 *   - countLines / getFileLanguage (both previously uncovered)
 *   - classifyMediaType video and audio arms, reached through getMediaInfo
 *   - extractUrlFromResultBlocks: array results, non-object entries, flat
 *     url/path blocks, oversized inline base64, and the no-match arm
 *   - extractUrlFromText absolute-path arm and its null arm
 *   - formatMemorySearch: unparseable raw, depth-limited nesting, and the
 *     multi-item malformed-text parser
 *   - formatAgentList: unparseable raw and no-agents arms
 *   - looksLikeMarkdown table detection and stringifyResult
 */
import { describe, it, expect, vi } from "vitest";
import type { TFunction } from "i18next";

vi.mock("@/api/modules/chat", () => ({
  chatApi: {
    filePreviewUrl: (p: string) => `/api/files/preview${p}`,
  },
}));

import {
  countLines,
  extractUrlFromText,
  formatAgentList,
  formatMemorySearch,
  getFileExtFromPath,
  getFileLanguage,
  getMediaInfo,
  hasMultimediaPreview,
  looksLikeMarkdown,
  stringifyResult,
} from "./utils";
import type { ToolCallContent } from "./types";

const translate = ((key: string) => key) as unknown as TFunction;

function tc(overrides: Partial<ToolCallContent> = {}): ToolCallContent {
  return {
    type: "tool_call",
    id: "tc-1",
    name: "shell",
    params: {},
    status: "done",
    ...overrides,
  };
}

describe("countLines", () => {
  it("counts newline-separated lines", () => {
    expect(countLines("a\nb\nc")).toBe(3);
  });

  it("counts a single line without a trailing newline as one", () => {
    expect(countLines("only one line")).toBe(1);
  });

  it("counts a trailing newline as an extra empty line", () => {
    expect(countLines("a\n")).toBe(2);
  });

  it("returns 0 for an empty string", () => {
    expect(countLines("")).toBe(0);
  });

  it.each([
    ["null", null],
    ["undefined", undefined],
    ["number", 42],
    ["boolean", true],
    ["object", { text: "a\nb" }],
    ["array", ["a", "b"]],
  ])("returns 0 for the non-string input %s", (_label, value) => {
    expect(countLines(value)).toBe(0);
  });
});

describe("getFileLanguage", () => {
  it.each([
    ["app.ts", "typescript"],
    ["app.tsx", "tsx"],
    ["app.js", "javascript"],
    ["app.jsx", "jsx"],
    ["app.py", "python"],
    ["app.rb", "ruby"],
    ["app.go", "go"],
    ["app.rs", "rust"],
    ["App.java", "java"],
    ["app.php", "php"],
    ["app.lua", "lua"],
    ["app.r", "r"],
    ["app.scala", "scala"],
    ["app.ex", "elixir"],
    ["app.exs", "elixir"],
  ])("maps %s to %s", (fileName, expected) => {
    expect(getFileLanguage(tc({ params: { file_path: fileName } }))).toBe(
      expected,
    );
  });

  it("matches the extension case-insensitively", () => {
    expect(getFileLanguage(tc({ params: { file_path: "MAIN.PY" } }))).toBe(
      "python",
    );
  });

  it("reads the path from the `path` param when file_path is absent", () => {
    expect(getFileLanguage(tc({ params: { path: "src/a.tsx" } }))).toBe("tsx");
  });

  it("prefers file_path over path", () => {
    expect(
      getFileLanguage(tc({ params: { file_path: "a.py", path: "b.ts" } })),
    ).toBe("python");
  });

  it("maps the markup and config extensions too", () => {
    expect(getFileLanguage(tc({ params: { file_path: "notes.md" } }))).toBe(
      "markdown",
    );
    expect(getFileLanguage(tc({ params: { file_path: "conf.ini" } }))).toBe(
      "ini",
    );
    expect(getFileLanguage(tc({ params: { file_path: "run.sh" } }))).toBe(
      "bash",
    );
    expect(getFileLanguage(tc({ params: { file_path: "plan.yml" } }))).toBe(
      "yaml",
    );
  });

  it("returns an empty string for an unmapped extension", () => {
    expect(getFileLanguage(tc({ params: { file_path: "archive.7z" } }))).toBe(
      "",
    );
  });

  it("returns an empty string when only a leading dot is present", () => {
    expect(getFileLanguage(tc({ params: { file_path: ".env" } }))).toBe("");
  });

  it("returns an empty string when the extension is the full name", () => {
    expect(
      getFileLanguage(tc({ params: { file_path: "notes.markdown" } })),
    ).toBe("");
  });

  it("returns an empty string for a path without an extension", () => {
    expect(getFileLanguage(tc({ params: { file_path: "Makefile" } }))).toBe("");
  });

  it("returns an empty string when no path param is present", () => {
    expect(getFileLanguage(tc({ params: { command: "ls" } }))).toBe("");
  });

  it("returns an empty string when params is missing entirely", () => {
    const noParams = {
      ...tc(),
      params: undefined,
    } as unknown as ToolCallContent;

    expect(getFileLanguage(noParams)).toBe("");
  });

  // The helper casts the param to string and calls .toLowerCase() on it, so a
  // numeric path param throws. Pinning the current behaviour so an accidental
  // change of the cast is visible.
  it("throws for a non-string path param", () => {
    expect(() => getFileLanguage(tc({ params: { file_path: 12345 } }))).toThrow(
      TypeError,
    );
  });
});

describe("getFileExtFromPath", () => {
  it("lowercases a plain extension", () => {
    expect(getFileExtFromPath("/tmp/SHOT.PNG")).toBe("png");
  });

  it("stops the extension at a query string", () => {
    expect(getFileExtFromPath("/tmp/a.png?v=2")).toBe("png");
  });

  it("stops the extension at a hash", () => {
    expect(getFileExtFromPath("/tmp/a.mp4#t=10")).toBe("mp4");
  });

  it("returns an empty string when there is no extension", () => {
    expect(getFileExtFromPath("/tmp/Makefile")).toBe("");
  });
});

describe("getMediaInfo media classification", () => {
  it.each([
    ["png", "image"],
    ["jpg", "image"],
    ["svg", "image"],
    ["mp4", "video"],
    ["mov", "video"],
    ["webm", "video"],
    ["mp3", "audio"],
    ["wav", "audio"],
    ["flac", "audio"],
    ["txt", "file"],
    ["pdf", "file"],
  ])("classifies a .%s result url as %s", (ext, expected) => {
    const media = getMediaInfo(tc({ result: [{ url: `/tmp/out.${ext}` }] }));

    expect(media?.type).toBe(expected);
  });

  it("reads a flat block carrying only `url`", () => {
    const media = getMediaInfo(tc({ result: [{ url: "/tmp/clip.mp4" }] }));

    expect(media).toEqual({
      url: "/api/files/preview/tmp/clip.mp4",
      name: "clip.mp4",
      type: "video",
    });
  });

  it("reads a flat block carrying only `path`", () => {
    const media = getMediaInfo(tc({ result: [{ path: "/tmp/song.mp3" }] }));

    expect(media).toEqual({
      url: "/api/files/preview/tmp/song.mp3",
      name: "song.mp3",
      type: "audio",
    });
  });

  it("prefers url over path within the same block", () => {
    const media = getMediaInfo(
      tc({ result: [{ url: "/tmp/a.png", path: "/tmp/b.txt" }] }),
    );

    expect(media?.name).toBe("a.png");
    expect(media?.type).toBe("image");
  });

  it("accepts a result that is already an array of blocks", () => {
    const media = getMediaInfo(
      tc({ result: [{ type: "image", source: { url: "file:///tmp/x.png" } }] }),
    );

    expect(media?.type).toBe("image");
  });

  it("skips non-object entries while scanning blocks", () => {
    const media = getMediaInfo(
      tc({ result: [null, 42, "text", { url: "/tmp/keep.png" }] }),
    );

    expect(media?.name).toBe("keep.png");
  });

  it("ignores blocks whose url is an empty string", () => {
    const media = getMediaInfo(
      tc({ result: [{ url: "" }, { path: "/tmp/real.png" }] }),
    );

    expect(media?.name).toBe("real.png");
  });

  it("returns null when no block yields a usable url", () => {
    expect(
      getMediaInfo(tc({ result: [{ type: "text", text: "done" }] })),
    ).toBeNull();
  });

  it("returns null when the result carries no url and the param path is relative", () => {
    expect(
      getMediaInfo(tc({ params: { file_path: "out/shot.png" } })),
    ).toBeNull();
  });

  it("returns null for an oversized inline base64 result", () => {
    const payload = `"type": "base64", "data": "${"A".repeat(70 * 1024)}"`;

    expect(getMediaInfo(tc({ result: payload }))).toBeNull();
  });

  it("falls back to the absolute param path when the result is oversized base64", () => {
    const payload = `"type": "base64", "data": "${"A".repeat(70 * 1024)}"`;

    const media = getMediaInfo(
      tc({ params: { file_path: "/tmp/shot.png" }, result: payload }),
    );

    expect(media?.name).toBe("shot.png");
    expect(media?.type).toBe("image");
  });

  it("uses the path basename as the name when the url has no extension", () => {
    const media = getMediaInfo(tc({ result: [{ url: "/tmp/download" }] }));

    expect(media?.name).toBe("download");
    expect(media?.type).toBe("file");
  });

  it("falls back to the literal name `file` when no filename can be derived", () => {
    // shortFileName yields "" for inline data urls, so the "file" fallback arm
    // is only reachable through them.
    const media = getMediaInfo(
      tc({ result: [{ url: "data:image/png;base64,iVBOR" }] }),
    );

    expect(media).toEqual({
      url: "data:image/png;base64,iVBOR",
      name: "file",
      type: "file",
    });
  });

  it("keeps http urls untouched", () => {
    const media = getMediaInfo(
      tc({ result: [{ url: "https://cdn.example.com/a.png" }] }),
    );

    expect(media?.url).toBe("https://cdn.example.com/a.png");
  });

  it("reports a multimedia preview for video but not for a plain file", () => {
    expect(hasMultimediaPreview(tc({ result: [{ url: "/tmp/a.mp4" }] }))).toBe(
      true,
    );
    expect(hasMultimediaPreview(tc({ result: [{ url: "/tmp/a.txt" }] }))).toBe(
      false,
    );
    expect(hasMultimediaPreview(tc({ result: "nothing" }))).toBe(false);
  });
});

describe("extractUrlFromText absolute paths", () => {
  it("finds an absolute image path without a `saved to` prefix", () => {
    expect(extractUrlFromText("wrote /tmp/out/shot.png successfully")).toBe(
      "/tmp/out/shot.png",
    );
  });

  it("finds an absolute audio path", () => {
    expect(extractUrlFromText("/var/data/clip.mp3")).toBe("/var/data/clip.mp3");
  });

  it("finds an absolute video path with dashes and dots", () => {
    expect(extractUrlFromText("/tmp/my-recording.v2.mp4")).toBe(
      "/tmp/my-recording.v2.mp4",
    );
  });

  it("returns null when the text has no media path at all", () => {
    expect(extractUrlFromText("command finished with exit code 0")).toBeNull();
  });

  it("returns null when the text holds no slash at all", () => {
    expect(extractUrlFromText("out.png")).toBeNull();
  });

  // The absolute-path pattern is anchored on a leading "/", so a path that
  // merely contains a separator is matched from that separator onwards.
  it("matches from the last separator of a slash-containing path", () => {
    expect(extractUrlFromText("relative/out.png")).toBe("/out.png");
  });

  it("returns null for an absolute path with a non-media extension", () => {
    expect(extractUrlFromText("/tmp/report.pdf")).toBeNull();
  });

  it("only searches the tail of an oversized inline base64 result", () => {
    const tail = "/tmp/late.png";
    const payload = `"type": "base64", "data": "${"A".repeat(
      70 * 1024,
    )}" ${tail}`;

    expect(extractUrlFromText(payload)).toBe(tail);
  });

  it("does not find a head-only path inside an oversized base64 result", () => {
    const payload = `/tmp/early.png "type": "base64", "data": "${"A".repeat(
      70 * 1024,
    )}"`;

    expect(extractUrlFromText(payload)).toBeNull();
  });
});

describe("formatMemorySearch fallbacks", () => {
  it("returns the raw text when it is not JSON", () => {
    expect(formatMemorySearch("plain prose, not json", translate)).toBe(
      "plain prose, not json",
    );
  });

  it("returns the raw text when nesting exceeds the depth limit", () => {
    let value: unknown = { path: "deep.md", score: 1, snippet: "s" };
    for (let i = 0; i < 8; i += 1) {
      value = { output: value };
    }
    const raw = JSON.stringify(value);

    expect(formatMemorySearch(raw, translate)).toBe(raw);
  });

  it("returns the raw text when the payload has neither items nor a text block", () => {
    const raw = JSON.stringify({ output: { status: "ok" } });

    expect(formatMemorySearch(raw, translate)).toBe(raw);
  });

  it("returns the raw text for a JSON null payload", () => {
    expect(formatMemorySearch("null", translate)).toBe("null");
  });

  it("renders a single object that is itself a search item", () => {
    const raw = JSON.stringify({
      output: {
        path: "solo.md",
        start_line: 4,
        end_line: 9,
        score: 0.75,
        snippet: "body",
      },
    });

    const rendered = formatMemorySearch(raw, translate);

    expect(rendered).toContain("solo.md");
    expect(rendered).toContain("L4-9");
    expect(rendered).toContain("0.75");
    expect(rendered).toContain("body");
  });

  it("joins text from several nested blocks", () => {
    const raw = JSON.stringify({
      output: [
        { type: "text", text: "first part" },
        { type: "image", url: "/tmp/a.png" },
        { type: "text", text: "second part" },
      ],
    });

    expect(formatMemorySearch(raw, translate)).toBe("first part\nsecond part");
  });

  it("returns the raw text when every text block is empty", () => {
    const raw = JSON.stringify({ output: [{ type: "text", text: "" }] });

    expect(formatMemorySearch(raw, translate)).toBe(raw);
  });

  it("renders dashes for items missing line numbers and score", () => {
    const raw = JSON.stringify([{ path: "noMeta.md", snippet: "  trimmed  " }]);

    const rendered = formatMemorySearch(raw, translate);

    expect(rendered).toContain("noMeta.md");
    expect(rendered).toContain("-");
    expect(rendered).toContain("trimmed");
  });

  it("renders `unknown` when the path key is present but empty", () => {
    const raw = JSON.stringify([{ path: "", score: 0.5, snippet: "s" }]);

    const rendered = formatMemorySearch(raw, translate);

    expect(rendered).toContain("### 1. unknown");
    expect(rendered).toContain("0.50");
    expect(rendered).toContain("s");
  });

  it("returns the raw text when an item has no path key at all", () => {
    // isMemorySearchResultItem requires "path" in candidate, so a path-less
    // item is not recognised as a search result and the raw JSON is returned.
    const raw = JSON.stringify([{ score: 0.5, snippet: "s" }]);

    expect(formatMemorySearch(raw, translate)).toBe(raw);
  });

  it("omits the snippet block when the snippet is empty", () => {
    const raw = JSON.stringify([{ path: "a.md", score: 0.5 }]);

    const rendered = formatMemorySearch(raw, translate);

    expect(rendered).toContain("a.md");
    expect(rendered).toContain("0.50");
    expect(rendered.endsWith("0.50")).toBe(true);
  });

  it("parses multiple malformed items whose snippets contain real newlines", () => {
    const malformed =
      '[{"path": "a.md", "start_line": 1, "end_line": 2, "score": 0.5, "snippet": "line one\nline two"}, ' +
      '{"path": "b.md", "start_line": 3, "end_line": 4, "score": 0.25, "snippet": "second"}]';
    const raw = JSON.stringify({ output: [{ type: "text", text: malformed }] });

    const rendered = formatMemorySearch(raw, translate);

    expect(rendered).toContain("### 1. a.md");
    expect(rendered).toContain("### 2. b.md");
    expect(rendered).toContain("L1-2");
    expect(rendered).toContain("L3-4");
    expect(rendered).toContain("0.50");
    expect(rendered).toContain("0.25");
    expect(rendered).toContain("line one\nline two");
    expect(rendered).toContain("---");
    expect(rendered).not.toContain('"path"');
  });

  it("returns the inner text when it parses to neither items nor malformed items", () => {
    const raw = JSON.stringify({
      output: [{ type: "text", text: "just a summary" }],
    });

    expect(formatMemorySearch(raw, translate)).toBe("just a summary");
  });

  it("unwraps escaped newline sequences before parsing malformed items", () => {
    const malformed =
      '[{"path": "c.md", "start_line": 7, "end_line": 8, "score": 0.9, "snippet": "alpha\\nbeta"}]';
    const raw = JSON.stringify({ output: [{ type: "text", text: malformed }] });

    const rendered = formatMemorySearch(raw, translate);

    expect(rendered).toContain("c.md");
    expect(rendered).toContain("alpha\nbeta");
  });
});

describe("formatAgentList fallbacks", () => {
  it("returns the raw text when it is not JSON", () => {
    expect(formatAgentList("no agents here", translate)).toBe("no agents here");
  });

  it("returns the raw text when the payload holds no agent entries", () => {
    const raw = JSON.stringify({ output: { count: 0 } });

    expect(formatAgentList(raw, translate)).toBe(raw);
  });

  it("returns the raw text for an empty agent list", () => {
    const raw = JSON.stringify({ agents: [] });

    expect(formatAgentList(raw, translate)).toBe(raw);
  });

  it("returns the raw text when nesting exceeds the depth limit", () => {
    let value: unknown = { name: "deep", description: "d" };
    for (let i = 0; i < 8; i += 1) {
      value = { output: value };
    }
    const raw = JSON.stringify(value);

    expect(formatAgentList(raw, translate)).toBe(raw);
  });

  it("returns the raw text for an array holding no agent-shaped entry", () => {
    const raw = JSON.stringify([{ kind: "other" }, null, "text"]);

    expect(formatAgentList(raw, translate)).toBe(raw);
  });

  it("renders a single object that is itself an agent entry", () => {
    const raw = JSON.stringify({
      output: {
        name: "solo",
        id: "a-1",
        description: "does things",
        status: "ok",
      },
    });

    const rendered = formatAgentList(raw, translate);

    expect(rendered).toContain("| solo | `a-1` | does things | ok |");
    expect(rendered).toContain("| --- | --- | --- | --- |");
  });

  it("falls back across the display_name, agent_id and missing-field arms", () => {
    const raw = JSON.stringify({
      agents: [
        { display_name: "Only Display", agent_id: "a-2", description: "d" },
        { id: "a-3" },
      ],
    });

    const rendered = formatAgentList(raw, translate);

    expect(rendered).toContain("| Only Display | `a-2` | d |  |");
    expect(rendered).not.toContain("a-3");
  });

  it("rejects entries that have identifying fields but no description", () => {
    const raw = JSON.stringify({ agents: [{ name: "no-desc", id: "x" }] });

    expect(formatAgentList(raw, translate)).toBe(raw);
  });

  it("accepts an entry identified by id alone plus a description", () => {
    const raw = JSON.stringify({ agents: [{ id: "a-9", description: "d9" }] });

    expect(formatAgentList(raw, translate)).toContain(
      "| a-9 | `a-9` | d9 |  |",
    );
  });

  it("rejects non-object entries", () => {
    const raw = JSON.stringify([null, 7, "agent"]);

    expect(formatAgentList(raw, translate)).toBe(raw);
  });
});

describe("looksLikeMarkdown", () => {
  it("detects a pipe table with a separator row", () => {
    expect(looksLikeMarkdown("| a | b |\n| --- | --- |\n| 1 | 2 |")).toBe(true);
  });

  it("detects a pipe table with an aligned separator row", () => {
    expect(looksLikeMarkdown("| a | b |\n|:--|--:|\n| 1 | 2 |")).toBe(true);
  });

  it("does not treat a lone pipe as a table", () => {
    expect(looksLikeMarkdown("a | b")).toBe(false);
  });

  it.each([
    ["atx heading", "# Title"],
    ["h6 heading", "###### Deep"],
    ["dash bullet", "- item"],
    ["star bullet", "* item"],
    ["ordered list", "1. first"],
    ["bold lead", "**bold** text"],
  ])("detects %s", (_label, text) => {
    expect(looksLikeMarkdown(text)).toBe(true);
  });

  it("detects markdown starting on a later line", () => {
    expect(looksLikeMarkdown("intro line\n## Section")).toBe(true);
  });

  it("returns false for plain prose", () => {
    expect(looksLikeMarkdown("just a sentence about testing")).toBe(false);
  });

  it("returns false for an empty string", () => {
    expect(looksLikeMarkdown("")).toBe(false);
  });
});

describe("stringifyResult", () => {
  it("extracts joined text from a serialized MCP block array", () => {
    const serialized = JSON.stringify([
      { type: "text", text: "first" },
      { type: "text", text: "second" },
    ]);

    expect(stringifyResult(serialized)).toBe("first\nsecond");
  });

  it("extracts joined text from an array of MCP blocks", () => {
    expect(
      stringifyResult([
        { type: "text", text: "a" },
        { type: "image", url: "/tmp/a.png" },
        { type: "text", text: "b" },
      ]),
    ).toBe("a\nb");
  });

  it("returns the serialized string when its blocks carry no text", () => {
    const serialized = JSON.stringify([{ type: "image", url: "/tmp/a.png" }]);

    expect(stringifyResult(serialized)).toBe(serialized);
  });

  it("returns the original string when a bracketed payload is not valid JSON", () => {
    expect(stringifyResult("[not json at all")).toBe("[not json at all");
  });

  it("returns the original string when a bracketed payload is not an array", () => {
    expect(stringifyResult('["a"')).toBe('["a"');
  });

  it("keeps leading whitespace of a plain string result", () => {
    expect(stringifyResult("  padded text  ")).toBe("  padded text  ");
  });

  it("returns a non-bracketed string unchanged", () => {
    expect(stringifyResult("exit code 0")).toBe("exit code 0");
  });

  it("returns an array of blocks without text as pretty JSON", () => {
    expect(stringifyResult([{ type: "image", url: "/tmp/a.png" }])).toBe(
      JSON.stringify([{ type: "image", url: "/tmp/a.png" }], null, 2),
    );
  });

  it("pretty-prints an object result", () => {
    expect(stringifyResult({ ok: true, n: 2 })).toBe(
      JSON.stringify({ ok: true, n: 2 }, null, 2),
    );
  });

  it("pretty-prints a number result", () => {
    expect(stringifyResult(42)).toBe("42");
  });

  it("keeps a false result instead of blanking it", () => {
    expect(stringifyResult(false)).toBe("false");
  });

  it("keeps a zero result instead of blanking it", () => {
    expect(stringifyResult(0)).toBe("0");
  });

  it("returns an empty string for null", () => {
    expect(stringifyResult(null)).toBe("");
  });

  it("returns an empty string for undefined", () => {
    expect(stringifyResult(undefined)).toBe("");
  });
});
