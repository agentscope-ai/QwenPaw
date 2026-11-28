import { Lexer, marked } from "marked";
import { describe, expect, it, vi } from "vitest";
import {
  latestHistoryMarkdownChunk,
  splitHistoryMarkdown,
  segmentMarkdown,
} from "./historyMarkdownChunks";

describe("historyMarkdownChunks", () => {
  it("keeps ordinary Markdown in one chunk", () => {
    expect(splitHistoryMarkdown("# Result\n\nComplete", 100)).toEqual([
      "# Result\n\nComplete",
    ]);
  });

  it("splits large Markdown without dropping content", () => {
    const content = Array.from(
      { length: 20 },
      (_, index) => `## Section ${index}\n\n${"x".repeat(20)}\n\n`,
    ).join("");
    const chunks = splitHistoryMarkdown(content, 80);

    expect(chunks.length).toBeGreaterThan(1);
    expect(chunks.join("")).toBe(content);
    expect(chunks.map((chunk) => marked.parse(chunk)).join("")).toBe(
      marked.parse(content),
    );
    expect(latestHistoryMarkdownChunk(content, 80)).toBe(
      chunks[chunks.length - 1],
    );
  });
});

it.each([
  "```ts\n" + "const x = 1;\n\n".repeat(100) + "```\n\nAfter\n\nEnd",
  "| A | B |\n| --- | --- |\n" + "| value | value |\n".repeat(100),
  "1. first\n\n   continuation\n\n2. second\n\nEnd",
  "[reference][id]\n\n" +
    "paragraph\n\n".repeat(100) +
    "[id]: https://example.com",
  "footnote[^1]\n\n" + "paragraph\n\n".repeat(100) + "[^1]: note",
  "$$\na + b\n\nc + d\n$$",
])("retains complete syntax for large semantic units", (content) => {
  const chunks = splitHistoryMarkdown(content, 40);
  expect(chunks.join("")).toBe(content);
  expect(chunks.map((chunk) => marked.parse(chunk)).join("")).toBe(
    marked.parse(content),
  );
});

it("reuses append-only segments and resets replaced global syntax", () => {
  const content = "A complete paragraph.\n\n".repeat(1000);
  const previous = segmentMarkdown(content, 1000);
  const lex = vi.spyOn(Lexer, "lex");
  const next = segmentMarkdown(content + "Next paragraph", 1000, previous);
  expect(lex.mock.calls[0][0].length).toBeLessThan(1200);
  expect(next.chunks.slice(0, -1)).toEqual(previous.chunks.slice(0, -1));
  expect(next.chunks.join("")).toBe(content + "Next paragraph");
  lex.mockRestore();
  const replaced = segmentMarkdown("replacement\n\n".repeat(100), 40, next);
  expect(replaced.chunks.join("")).toBe(replaced.source);
  const references = segmentMarkdown(
    next.source + "\n\n[id]: https://example.com",
    40,
    next,
  );
  expect(references.chunks).toEqual([references.source]);
});
