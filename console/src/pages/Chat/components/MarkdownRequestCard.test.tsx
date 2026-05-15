import { describe, expect, it } from "vitest";
import { requestContentToCards } from "./MarkdownRequestCard.utils";

describe("MarkdownRequestCard", () => {
  it("keeps user text on the markdown renderer", () => {
    const cards = requestContentToCards([
      { type: "text", text: "**bold**\n\n- item", status: "created" },
    ]);

    expect(cards).toHaveLength(1);
    expect(cards[0]).toMatchObject({
      code: "Text",
      data: {
        content: "**bold**\n\n- item",
      },
    });
    expect((cards[0].data as Record<string, unknown>).raw).toBeUndefined();
  });

  it("preserves non-text request cards", () => {
    const cards = requestContentToCards([
      { type: "image", image_url: "/img.png", status: "created" },
      {
        type: "file",
        file_url: "/doc.pdf",
        file_name: "doc.pdf",
        file_size: 42,
        status: "created",
      },
    ]);

    expect(cards).toEqual([
      { code: "Images", data: [{ url: "/img.png" }] },
      {
        code: "Files",
        data: [{ url: "/doc.pdf", name: "doc.pdf", size: 42 }],
      },
    ]);
  });
});
