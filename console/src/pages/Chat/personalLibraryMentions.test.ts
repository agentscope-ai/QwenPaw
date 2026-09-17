import { describe, expect, it } from "vitest";
import {
  encodePersonalLibraryMention,
  selectedDocumentIdsPresentInInput,
  findPersonalLibraryMentionToken,
  rewritePersonalLibraryMentionsInInput,
} from "./personalLibraryMentions";

describe("personal library mentions", () => {
  it("encodes a stable document id and keeps a readable display name", () => {
    expect(
      encodePersonalLibraryMention({ id: "doc-1", name: "AI写作需求文档.md" }),
    ).toBe("@[AI写作需求文档.md](personal-library:doc-1)");
  });

  it("finds an unfinished inline @ token at the cursor", () => {
    expect(findPersonalLibraryMentionToken("请审阅 @AI写", 8)).toEqual({
      keyword: "ai写",
      mentionStart: 4,
      cursor: 8,
    });
  });

  it("extracts ids and replaces internal mention syntax before submit", () => {
    const result = rewritePersonalLibraryMentionsInInput([
      {
        role: "user",
        content: [
          {
            type: "text",
            text: "请审阅 @[AI写作需求文档.md](personal-library:doc-1)",
          },
        ],
      },
    ]);

    expect(result.documentIds).toEqual(["doc-1"]);
    expect(result.input[0].content).toEqual([
      { type: "text", text: "请审阅 @AI写作需求文档.md" },
    ]);
  });

  it("keeps a plain readable mention bound to the document selected in this draft", () => {
    expect(
      selectedDocumentIdsPresentInInput(
        [{ role: "user", content: [{ type: "text", text: "请审阅 @需求.md" }] }],
        [{ id: "doc-1", name: "需求.md" }],
      ),
    ).toEqual(["doc-1"]);
  });
});
