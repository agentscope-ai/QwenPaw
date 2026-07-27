import { describe, expect, it } from "vitest";
import {
  atomicDeletionRange,
  splitFileReferences,
} from "./fileReferenceFormatting";

describe("splitFileReferences", () => {
  it("marks POSIX and Windows absolute file references", () => {
    expect(
      splitFileReferences(
        "查看 @ /Users/ray/work/hello.txt 和 @ C:\\work\\app.ts",
      ),
    ).toEqual([
      { text: "查看 ", reference: false },
      { text: "@ /Users/ray/work/hello.txt", reference: true },
      { text: " 和 ", reference: false },
      { text: "@ C:\\work\\app.ts", reference: true },
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
      { text: "src/app.ts:12-18", reference: true },
      {
        text: "\n```typescript\nconst app = true;\n```",
        reference: false,
      },
    ]);
  });

  it("does not style ordinary mentions or unqualified relative paths", () => {
    expect(splitFileReferences("@ ray @ src/app.ts")).toEqual([
      { text: "@ ray @ src/app.ts", reference: false },
    ]);
  });

  it("deletes a complete reference when backspace is pressed at its end", () => {
    const value = "查看 @ /Users/ray/work/hello.txt";
    expect(
      atomicDeletionRange(value, value.length, value.length, "Backspace"),
    ).toEqual({ start: 3, end: value.length });
  });

  it("deletes a complete reference when delete is pressed inside it", () => {
    const value = "@ C:\\work\\app.ts 后续";
    expect(atomicDeletionRange(value, 5, 5, "Delete")).toEqual({
      start: 0,
      end: 16,
    });
  });

  it("expands a partial selection to include the complete reference", () => {
    const value = "前 @ /work/app.ts 后";
    expect(atomicDeletionRange(value, 0, 8, "Backspace")).toEqual({
      start: 0,
      end: 16,
    });
  });

  it("deletes an editor line reference atomically", () => {
    const value = "请看 src/app.ts:12-18";
    expect(
      atomicDeletionRange(value, value.length, value.length, "Backspace"),
    ).toEqual({ start: 3, end: value.length });
  });
});
