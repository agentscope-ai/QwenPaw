import type { editor as MonacoEditor } from "monaco-editor";
import { describe, expect, it } from "vitest";
import { detectCopyMode, formatSelectionForChat } from "./editorCopyFormatting";

function model(value: string, selected: string): MonacoEditor.ITextModel {
  const lines = value.split("\n");
  return {
    getValue: () => value,
    getValueInRange: () => selected,
    getLineContent: (line: number) => lines[line - 1] ?? "",
  } as unknown as MonacoEditor.ITextModel;
}

describe("Editor references copied to Chat", () => {
  it("keeps a whole-file selection as a line reference", () => {
    const copy = detectCopyMode(
      {
        startLineNumber: 1,
        startColumn: 1,
        endLineNumber: 2,
        endColumn: 5,
      },
      model("first\nlast", "first\nlast"),
    );

    expect(copy.mode).toBe("lines-only");
    expect(
      formatSelectionForChat(
        "src/app.ts",
        copy.code,
        copy.startLine,
        copy.endLine,
        copy.mode,
      ),
    ).toBe("src/app.ts:1-2");
  });

  it("adds a fenced code block for a partial-line selection", () => {
    const copy = detectCopyMode(
      {
        startLineNumber: 2,
        startColumn: 7,
        endLineNumber: 2,
        endColumn: 12,
      },
      model("const first = true;\nconst value = false;", "value"),
    );

    expect(copy.mode).toBe("with-code");
    expect(
      formatSelectionForChat(
        "src/app.ts",
        copy.code,
        copy.startLine,
        copy.endLine,
        copy.mode,
      ),
    ).toBe("src/app.ts:2\n```typescript\nvalue\n```");
  });

  it("keeps selected complete lines free of a code block", () => {
    const copy = detectCopyMode(
      {
        startLineNumber: 2,
        startColumn: 1,
        endLineNumber: 3,
        endColumn: 6,
      },
      model("zero\nfirst\nthird\nlast", "first\nthird"),
    );

    expect(copy.mode).toBe("lines-only");
    expect(
      formatSelectionForChat(
        "src/app.ts",
        copy.code,
        copy.startLine,
        copy.endLine,
        copy.mode,
      ),
    ).toBe("src/app.ts:2-3");
  });
});
