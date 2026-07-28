import { describe, expect, it } from "vitest";
import {
  splitFileReferences,
  splitRichComposerValue,
} from "./fileReferenceFormatting";

describe("splitFileReferences", () => {
  it("marks POSIX and Windows absolute file references", () => {
    expect(
      splitFileReferences(
        "查看 @ /Users/ray/work/hello.txt 和 @ C:\\work\\app.ts",
      ),
    ).toEqual([
      { text: "查看 ", reference: null },
      {
        text: "@ /Users/ray/work/hello.txt",
        reference: {
          kind: "file",
          path: "/Users/ray/work/hello.txt",
        },
      },
      { text: " 和 ", reference: null },
      {
        text: "@ C:\\work\\app.ts",
        reference: {
          kind: "file",
          path: "C:\\work\\app.ts",
        },
      },
    ]);
  });

  it("marks relative file references inserted by Preview", () => {
    expect(splitFileReferences("@ src/app.ts 和 @ LICENSE")).toEqual([
      {
        text: "@ src/app.ts",
        reference: {
          kind: "file",
          path: "src/app.ts",
        },
      },
      { text: " 和 ", reference: null },
      {
        text: "@ LICENSE",
        reference: {
          kind: "file",
          path: "LICENSE",
        },
      },
    ]);
  });

  it("does not alter the underlying text", () => {
    const value = "@ /Users/ray/work/hello.txt 请检查";
    expect(
      splitFileReferences(value)
        .map((part) => part.text)
        .join(""),
    ).toBe(value);
  });

  it("marks editor line references without changing their text", () => {
    const value = "src/app.ts:12-18\n```typescript\nconst app = true;\n```";
    expect(splitFileReferences(value)).toEqual([
      {
        text: "src/app.ts:12-18",
        reference: {
          kind: "editor",
          path: "src/app.ts",
          startLine: 12,
          endLine: 18,
        },
      },
      {
        text: "\n```typescript\nconst app = true;\n```",
        reference: null,
      },
    ]);
  });

  it("marks Windows Editor line references", () => {
    expect(splitFileReferences("C:\\work\\app.ts:4-9")).toEqual([
      {
        text: "C:\\work\\app.ts:4-9",
        reference: {
          kind: "editor",
          path: "C:\\work\\app.ts",
          startLine: 4,
          endLine: 9,
        },
      },
    ]);
  });

  it("does not style ordinary text that resembles a label and number", () => {
    expect(splitFileReferences("chapter:12 plain text")).toEqual([
      { text: "chapter:12 plain text", reference: null },
    ]);
  });
});

describe("splitRichComposerValue", () => {
  it("creates separate line-reference and code-snippet chips", () => {
    const value = "src/app.ts:12-18\n```typescript\nconst app = true;\n```";
    expect(splitRichComposerValue(value)).toEqual([
      {
        kind: "file",
        raw: "src/app.ts:12-18",
        reference: {
          kind: "editor",
          path: "src/app.ts",
          startLine: 12,
          endLine: 18,
        },
      },
      {
        kind: "code",
        raw: "\n```typescript\nconst app = true;\n```",
        language: "typescript",
        code: "const app = true;",
      },
    ]);
  });

  it("preserves the exact raw value used for submission", () => {
    const value = "请检查 src/app.ts:12\n```typescript\napp();\n```\n然后继续";
    expect(
      splitRichComposerValue(value)
        .map((part) => part.raw)
        .join(""),
    ).toBe(value);
  });

  it("keeps unrelated fenced code as ordinary editable text", () => {
    const value = "示例\n```text\nhello\n```";
    expect(splitRichComposerValue(value)).toEqual([
      { kind: "text", raw: value },
    ]);
  });
});
