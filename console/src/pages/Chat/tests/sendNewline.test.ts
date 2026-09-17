/**
 * sendNewline.test.ts — regression for #4216 (newline lost on send)
 *
 * When the user types a message containing newlines (\n) and sends it,
 * the content must preserve the newline characters in the request body.
 *
 * The send path goes through:
 *   1. User types in textarea (value contains \n)
 *   2. SDK formats input as content array [{ type: "text", text: "..." }]
 *   3. customFetch in Chat/index.tsx normalizes URLs and sends
 *
 * We test the pure functions in the pipeline that handle text content:
 *   - extractUserMessageText preserves newlines in string content
 *   - extractUserMessageText joins array content with \n
 *   - normalizeContentUrls does not alter text content
 *   - setTextareaValue preserves newlines
 */
import { describe, it, expect, vi } from "vitest";
import {
  extractUserMessageText,
  extractTextFromMessage,
  normalizeContentUrls,
  setTextareaValue,
} from "../utils";

vi.mock("@/api/modules/chat", () => ({
  chatApi: {
    filePreviewUrl: vi.fn((p: string) => `http://localhost:8000${p}`),
  },
}));

describe("Send path newline preservation (#4216)", () => {
  describe("extractUserMessageText", () => {
    it("preserves newlines in string content", () => {
      const msg = { content: "line1\nline2\nline3" };
      expect(extractUserMessageText(msg)).toBe("line1\nline2\nline3");
    });

    it("preserves newlines when content is an array with single text item", () => {
      const msg = {
        content: [{ type: "text", text: "first\nsecond\nthird" }],
      };
      expect(extractUserMessageText(msg)).toBe("first\nsecond\nthird");
    });

    it("joins multiple text items with newlines", () => {
      const msg = {
        content: [
          { type: "text", text: "paragraph1" },
          { type: "text", text: "paragraph2" },
        ],
      };
      expect(extractUserMessageText(msg)).toBe("paragraph1\nparagraph2");
    });

    it("preserves trailing newlines in text content", () => {
      const msg = { content: "code block\n\n" };
      expect(extractUserMessageText(msg)).toBe("code block\n\n");
    });

    it("preserves leading newlines in text content", () => {
      const msg = { content: "\n\nindented" };
      expect(extractUserMessageText(msg)).toBe("\n\nindented");
    });

    it("handles mixed content types without losing newlines in text", () => {
      const msg = {
        content: [
          { type: "text", text: "before\n" },
          { type: "image_url", image_url: "http://example.com/img.png" },
          { type: "text", text: "\nafter" },
        ],
      };
      const result = extractUserMessageText(msg);
      expect(result).toContain("before\n");
      expect(result).toContain("\nafter");
    });
  });

  describe("extractTextFromMessage", () => {
    it("extracts text with newlines from card-based message format", () => {
      const msg = {
        cards: [
          {
            data: {
              input: [
                {
                  content: [{ type: "text", text: "line1\nline2" }],
                },
              ],
            },
          },
        ],
      };
      expect(extractTextFromMessage(msg)).toBe("line1\nline2");
    });
  });

  describe("normalizeContentUrls", () => {
    it("does not modify text content with newlines", () => {
      const part = { type: "text", text: "hello\nworld\nfoo" };
      const result = normalizeContentUrls(part);
      expect(result.text).toBe("hello\nworld\nfoo");
    });

    it("preserves newlines in text while converting URLs in other parts", () => {
      const parts = [
        { type: "text", text: "check this\nfile" },
        { type: "image", image_url: "http://host/files/preview/img.png" },
      ];
      const result = parts.map(normalizeContentUrls);
      expect(result[0].text).toBe("check this\nfile");
      expect(result[1].image_url).toBe("/img.png");
    });
  });

  describe("setTextareaValue", () => {
    it("preserves newlines when setting textarea value", () => {
      document.body.innerHTML = `
        <div class="sender"><textarea></textarea></div>
      `;
      const textarea = document.querySelector(
        "textarea",
      ) as HTMLTextAreaElement;
      const multilineValue = "line1\nline2\nline3";

      setTextareaValue(textarea, multilineValue);

      expect(textarea.value).toBe("line1\nline2\nline3");
      document.body.innerHTML = "";
    });

    it("dispatches input event with newline content", () => {
      document.body.innerHTML = `
        <div class="sender"><textarea></textarea></div>
      `;
      const textarea = document.querySelector(
        "textarea",
      ) as HTMLTextAreaElement;
      const onInput = vi.fn();
      textarea.addEventListener("input", onInput);

      setTextareaValue(textarea, "first\nsecond");

      expect(onInput).toHaveBeenCalledOnce();
      expect(textarea.value).toBe("first\nsecond");
      document.body.innerHTML = "";
    });
  });
});
